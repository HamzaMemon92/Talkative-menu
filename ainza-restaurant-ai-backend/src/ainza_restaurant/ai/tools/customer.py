from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.ai.context import AIActorType, AIToolContext
from ainza_restaurant.ai.customer_intent import MealRecommendationGoal
from ainza_restaurant.ai.errors import AIToolScopeError
from ainza_restaurant.ai.models import AIToolSafetyLevel
from ainza_restaurant.ai.recommendations import MealRecommendationService
from ainza_restaurant.ai.tools.definitions import AIToolDefinition
from ainza_restaurant.availability.service import AvailabilityService
from ainza_restaurant.billing.service import BillingService
from ainza_restaurant.customer_menu.schemas import CustomerMenuFilters, CustomerMenuRead
from ainza_restaurant.customer_menu.service import CustomerMenuService
from ainza_restaurant.dining.models import DiningSession, RestaurantTable
from ainza_restaurant.domain.enums import (
    AvailabilityStatus,
    DietaryClassification,
    HalalOverride,
    ItemType,
    SpiceLevel,
)
from ainza_restaurant.ordering.schemas import (
    CartBatchAddItem,
    CartItemCreate,
    CartItemPatch,
    CartItemRead,
    CartItemRemoveRequest,
    CartOfferSelect,
    CartSubmitRequest,
)
from ainza_restaurant.ordering.service import CartService, money


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AIMenuFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: UUID | None = None
    cuisine_id: UUID | None = None
    item_type: ItemType | None = None
    dietary_classification: DietaryClassification | None = None
    vegan_status: AvailabilityStatus | None = None
    jain_status: AvailabilityStatus | None = None
    halal_status: HalalOverride | None = None
    spice_level: SpiceLevel | None = None
    available: bool | None = None
    is_featured: bool | None = None
    is_todays_special: bool | None = None
    price_min: Decimal | None = Field(default=None, ge=Decimal("0"))
    price_max: Decimal | None = Field(default=None, ge=Decimal("0"))

    @model_validator(mode="after")
    def validate_price_range(self) -> AIMenuFilters:
        if self.price_min is not None and self.price_max is not None:
            if self.price_min > self.price_max:
                raise ValueError("price_min must not exceed price_max")
        return self

    def to_customer_filters(self) -> CustomerMenuFilters:
        return CustomerMenuFilters(**self.model_dump())


class MenuSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text_query: str | None = Field(default=None, min_length=1, max_length=200)
    query: str | None = Field(default=None, min_length=1, max_length=200)
    filters: AIMenuFilters | None = None
    limit: int = Field(default=10, ge=1, le=20)

    @model_validator(mode="after")
    def require_search_constraint(self) -> MenuSearchInput:
        has_filters = bool(self.filters and self.filters.model_dump(exclude_none=True))
        if self.text_query is None and self.query is None and not has_filters:
            raise ValueError("menu_search requires text_query or filters")
        return self

    @property
    def search_text(self) -> str | None:
        return self.text_query or self.query


class MealRecommendationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    party_size: int | None = Field(default=None, ge=1, le=20)
    budget_min: Decimal | None = Field(default=None, ge=Decimal("0"))
    budget_max: Decimal | None = Field(default=None, ge=Decimal("0"))
    filters: AIMenuFilters | None = None
    recommendation_goal: MealRecommendationGoal = MealRecommendationGoal.GENERAL_RECOMMENDATION
    excluded_dish_names: list[str] = Field(
        default_factory=list,
        max_length=10,
        description=(
            "Dish names to exclude from the recommendation. Use when the customer says "
            "'instead of X' or 'without X'. Matched case-insensitively against dish names."
        ),
    )

    @model_validator(mode="after")
    def validate_budget_range(self) -> MealRecommendationInput:
        if self.budget_min is not None and self.budget_max is not None:
            if self.budget_min > self.budget_max:
                raise ValueError("budget_min must not exceed budget_max")
        return self


class DishIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dish_id: UUID


class CartAddItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dish_id: UUID
    variant_id: UUID | None = None
    quantity: int = Field(gt=0, le=99)
    modifier_option_ids: list[UUID] = Field(default_factory=list)
    customer_note: str | None = Field(default=None, max_length=500)
    expected_cart_version: int | None = Field(default=None, ge=1)


class CartBatchAddInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CartBatchAddItem] = Field(min_length=1, max_length=20)
    expected_cart_version: int | None = Field(default=None, ge=1)


class CartUpdateItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cart_item_id: UUID
    quantity: int | None = Field(default=None, gt=0, le=99)
    modifier_option_ids: list[UUID] | None = None
    customer_note: str | None = Field(default=None, max_length=500)
    expected_cart_version: int | None = Field(default=None, ge=1)


class CartRemoveItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cart_item_id: UUID
    expected_cart_version: int | None = Field(default=None, ge=1)


class CartSelectOfferInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: UUID | None = None
    expected_cart_version: int | None = Field(default=None, ge=1)


class CartSubmitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote_token: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=120)


class SelectionQuoteItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dish_id: UUID
    variant_id: UUID | None = None
    quantity: int = Field(gt=0, le=99)
    modifier_option_ids: list[UUID] = Field(default_factory=list)


class MenuQuoteSelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SelectionQuoteItemInput] = Field(min_length=1, max_length=20)
    offer_id: UUID | None = None


async def _customer_session_token(session: AsyncSession, context: AIToolContext) -> str:
    if context.dining_session_token is None:
        raise AIToolScopeError("customer dining session token is required")
    row = (
        await session.execute(
            select(DiningSession.id)
            .join(RestaurantTable, RestaurantTable.id == DiningSession.table_id)
            .where(
                DiningSession.public_session_token == context.dining_session_token,
                RestaurantTable.outlet_id == context.outlet_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise AIToolScopeError("customer dining session does not belong to context outlet")
    return context.dining_session_token


async def menu_get(session: AsyncSession, context: AIToolContext, payload: BaseModel) -> object:
    cast(NoArgs, payload)
    return _menu_overview_for_model(await CustomerMenuService(session).get_menu(context.outlet_id))


def _menu_overview_for_model(menu: CustomerMenuRead) -> dict[str, object]:
    """Keep the model's menu overview factual without replaying API-only detail."""
    return {
        "restaurant": menu.restaurant.name,
        "outlet": menu.outlet.name,
        "currency_code": menu.outlet.currency_code,
        "categories": [
            {
                "name": category.name,
                "dishes": [
                    {
                        "id": dish.id,
                        "name": dish.name,
                        "price": str(dish.pricing.effective_price),
                        "dietary": dish.dietary_classification.value,
                        "vegan": dish.vegan_status.value,
                        "jain": dish.jain_status.value,
                        "halal": dish.halal_status.value,
                        "spice": dish.spice_level.value,
                        "allergen_info": dish.allergen_information_status.value,
                        "available": dish.available,
                        "variants": [
                            {
                                "name": variant.name,
                                "price": str(variant.effective_price),
                            }
                            for variant in dish.variants
                        ],
                    }
                    for dish in category.dishes
                ],
            }
            for category in menu.categories
        ],
        "featured_dishes": [dish.name for dish in menu.featured_dishes],
        "offers": [offer.name for offer in menu.offers],
        "detail_lookup": (
            "Use menu_get_dish for ingredients, modifiers, images, and full dish details."
        ),
    }


async def menu_search(session: AsyncSession, context: AIToolContext, payload: BaseModel) -> object:
    data = cast(MenuSearchInput, payload)
    results = await CustomerMenuService(session).search(
        context.outlet_id,
        q=data.search_text,
        filters=data.filters.to_customer_filters() if data.filters else None,
    )
    return results[: data.limit]


async def meal_recommend(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> dict[str, object]:
    data = cast(MealRecommendationInput, payload)
    return await MealRecommendationService(session).recommend(
        context.outlet_id,
        party_size=data.party_size,
        budget_min=data.budget_min,
        budget_max=data.budget_max,
        filters=data.filters.to_customer_filters() if data.filters else None,
        goal=data.recommendation_goal,
        excluded_dish_names=data.excluded_dish_names,
    )


async def menu_get_dish(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    data = cast(DishIdInput, payload)
    return await CustomerMenuService(session).get_dish(context.outlet_id, data.dish_id)


async def dish_get_availability(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> dict[str, object]:
    data = cast(DishIdInput, payload)
    await CustomerMenuService(session).get_dish(context.outlet_id, data.dish_id)
    availability = await AvailabilityService(session).dish_availability(data.dish_id)
    return availability.model_dump(mode="json", exclude={"blocking_causes"})


async def offers_get_effective(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    cast(NoArgs, payload)
    menu = await CustomerMenuService(session).get_menu(context.outlet_id)
    return menu.offers


async def menu_quote_selection(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> dict[str, object]:
    data = cast(MenuQuoteSelectionInput, payload)
    token = await _customer_session_token(session, context)
    cart_service = CartService(session)
    service_context = await cart_service._context(token)
    lines: list[CartItemRead] = []
    unavailable: list[str] = []
    subtotal = Decimal("0.00")
    for item in data.items:
        target = await cart_service._validated_target(
            service_context, item.dish_id, item.variant_id, item.modifier_option_ids
        )
        variant = target.variant
        available = await cart_service._dish_available(target.dish)
        pricing = await cart_service._pricing(target.dish, variant, target.modifiers, item.quantity)
        subtotal = money(subtotal + pricing.line_subtotal)
        if not available:
            unavailable.append(str(item.dish_id))
        lines.append(
            CartItemRead(
                id=item.dish_id,
                dish_id=target.dish.id,
                dish_name=target.dish.name,
                variant_id=variant.id if variant else None,
                variant_name=variant.name if variant else None,
                quantity=item.quantity,
                customer_note=None,
                available=available,
                availability_status="available" if available else "sold_out",
                pricing=pricing,
                modifiers=[],
            )
        )
    offer = await cart_service._offer_for_cart(service_context.outlet.id, data.offer_id)
    selected_offer = await cart_service._selected_offer_read(offer, lines)
    subtotal_after = money(max(subtotal - selected_offer.discount_amount, type(subtotal)("0")))
    return {
        "currency_code": service_context.outlet.currency_code,
        "items": [line.model_dump(mode="json") for line in lines],
        "available": not unavailable,
        "unavailable_dish_ids": unavailable,
        "subtotal_before_offer": str(subtotal),
        "selected_offer": selected_offer.model_dump(mode="json"),
        "subtotal_after_discount": str(subtotal_after),
        "tax_calculated": False,
    }


async def cart_get(session: AsyncSession, context: AIToolContext, payload: BaseModel) -> object:
    cast(NoArgs, payload)
    token = await _customer_session_token(session, context)
    return await CartService(session).get_cart(token)


async def cart_add_item(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    data = cast(CartAddItemInput, payload)
    token = await _customer_session_token(session, context)
    return await CartService(session).add_item(
        token,
        CartItemCreate(
            dish_id=data.dish_id,
            variant_id=data.variant_id,
            quantity=data.quantity,
            modifier_option_ids=data.modifier_option_ids,
            customer_note=data.customer_note,
            expected_version=data.expected_cart_version,
        ),
    )


async def cart_add_items(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    data = cast(CartBatchAddInput, payload)
    token = await _customer_session_token(session, context)
    result = await CartService(session).add_items_batch(
        token, data.items, expected_version=data.expected_cart_version
    )
    return result.model_dump(mode="json")


async def cart_update_item(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    data = cast(CartUpdateItemInput, payload)
    token = await _customer_session_token(session, context)
    return await CartService(session).patch_item(
        token,
        data.cart_item_id,
        CartItemPatch(
            quantity=data.quantity,
            modifier_option_ids=data.modifier_option_ids,
            customer_note=data.customer_note,
            expected_version=data.expected_cart_version,
        ),
    )


async def cart_remove_item(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    data = cast(CartRemoveItemInput, payload)
    token = await _customer_session_token(session, context)
    return await CartService(session).remove_item(
        token,
        data.cart_item_id,
        expected_version=CartItemRemoveRequest(
            expected_version=data.expected_cart_version
        ).expected_version,
    )


async def cart_select_offer(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    data = cast(CartSelectOfferInput, payload)
    token = await _customer_session_token(session, context)
    return await CartService(session).select_offer(
        token,
        CartOfferSelect(offer_id=data.offer_id, expected_version=data.expected_cart_version),
    )


async def cart_submit(session: AsyncSession, context: AIToolContext, payload: BaseModel) -> object:
    data = cast(CartSubmitInput, payload)
    token = await _customer_session_token(session, context)
    return await CartService(session).submit_cart(
        token,
        CartSubmitRequest(
            confirm=True,
            quote_token=data.quote_token,
            idempotency_key=data.idempotency_key,
        ),
    )


async def orders_get_session(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    cast(NoArgs, payload)
    token = await _customer_session_token(session, context)
    return await CartService(session).list_orders(token)


async def bill_get_preview(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    cast(NoArgs, payload)
    token = await _customer_session_token(session, context)
    return await BillingService(session).get_preview(token)


async def customer_total_summary(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> dict[str, object]:
    cast(NoArgs, payload)
    token = await _customer_session_token(session, context)
    cart = await CartService(session).get_cart(token)
    bill = await BillingService(session).get_preview(token)
    has_submitted_orders = bool(bill.round_summaries)
    cart_has_items = bool(cart.items)
    state = (
        "BOTH"
        if cart_has_items and has_submitted_orders
        else "CART_ONLY"
        if cart_has_items
        else "SUBMITTED_ONLY"
        if has_submitted_orders
        else "EMPTY"
    )
    return {
        "state": state,
        "cart_has_items": cart_has_items,
        "cart_item_count": cart.quantity_count,
        "cart_total": cart.subtotal_after_discount if cart_has_items else None,
        "has_submitted_orders": has_submitted_orders,
        "submitted_bill_total": bill.invoice_total if has_submitted_orders else None,
        "currency_code": cart.currency_code,
    }


CUSTOMER = frozenset({AIActorType.CUSTOMER})

CUSTOMER_TOOLS = [
    AIToolDefinition(
        name="menu_get",
        description=(
            "Return a compact authoritative customer-visible menu overview for the server-bound "
            "outlet. Use menu_get_dish for modifiers, ingredients, images, or full dish details. "
            "Preserves UNKNOWN dietary, spice, halal, and allergen metadata."
        ),
        input_model=NoArgs,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=menu_get,
    ),
    AIToolDefinition(
        name="menu_search",
        description=(
            "Deterministically search the server-bound customer menu; no embeddings or AI ranking. "
            "Use text_query for dish/name concepts and filters for canonical dietary, vegan, Jain, "
            "spice, halal, and availability constraints. "
            "query remains a legacy alias for text_query."
        ),
        input_model=MenuSearchInput,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=menu_search,
    ),
    AIToolDefinition(
        name="meal_recommend",
        description=(
            "Build a read-only, deterministic meal suggestion from available customer-visible "
            "dishes. The backend owns prices, availability, totals, and budget enforcement."
        ),
        input_model=MealRecommendationInput,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=meal_recommend,
    ),
    AIToolDefinition(
        name="menu_get_dish",
        description=(
            "Return one customer-visible dish by backend dish_id within the server-bound outlet."
        ),
        input_model=DishIdInput,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=menu_get_dish,
    ),
    AIToolDefinition(
        name="dish_get_availability",
        description=(
            "Return customer-safe effective availability for a visible dish "
            "without internal reason notes."
        ),
        input_model=DishIdInput,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=dish_get_availability,
    ),
    AIToolDefinition(
        name="offers_get_effective",
        description="Return currently effective customer-safe offers for the server-bound outlet.",
        input_model=NoArgs,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=offers_get_effective,
    ),
    AIToolDefinition(
        name="menu_quote_selection",
        description=(
            "Quote a planned selection using backend pricing without mutating the cart. "
            "Use actual backend dish IDs and use before making budget-fit claims."
        ),
        input_model=MenuQuoteSelectionInput,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=menu_quote_selection,
    ),
    AIToolDefinition(
        name="cart_get",
        description="Return live cart state for the server-bound dining session.",
        input_model=NoArgs,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=cart_get,
    ),
    AIToolDefinition(
        name="cart_add_item",
        description=(
            "Add an explicitly requested item by backend IDs only; backend services "
            "calculate price and availability."
        ),
        input_model=CartAddItemInput,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.REVERSIBLE_MUTATION,
        requires_confirmation=False,
        handler=cart_add_item,
    ),
    AIToolDefinition(
        name="cart_add_items",
        description=(
            "Atomically add an ordered batch of explicitly requested items. "
            "Required items abort the batch on failure; conditional items are skipped."
        ),
        input_model=CartBatchAddInput,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.REVERSIBLE_MUTATION,
        requires_confirmation=False,
        handler=cart_add_items,
    ),
    AIToolDefinition(
        name="cart_update_item",
        description=(
            "Update a cart item in the server-bound dining session; no price fields are accepted."
        ),
        input_model=CartUpdateItemInput,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.REVERSIBLE_MUTATION,
        requires_confirmation=False,
        handler=cart_update_item,
    ),
    AIToolDefinition(
        name="cart_remove_item",
        description="Remove a cart item from the server-bound dining session.",
        input_model=CartRemoveItemInput,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.REVERSIBLE_MUTATION,
        requires_confirmation=False,
        handler=cart_remove_item,
    ),
    AIToolDefinition(
        name="cart_select_offer",
        description="Select or clear at most one offer using deterministic cart service logic.",
        input_model=CartSelectOfferInput,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.REVERSIBLE_MUTATION,
        requires_confirmation=False,
        handler=cart_select_offer,
    ),
    AIToolDefinition(
        name="cart_submit",
        description=(
            "Submit the current cart. Requires external human confirmation outside model arguments."
        ),
        input_model=CartSubmitInput,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.CONSEQUENTIAL_MUTATION,
        requires_confirmation=True,
        handler=cart_submit,
    ),
    AIToolDefinition(
        name="orders_get_session",
        description="Return immutable submitted order rounds for the server-bound dining session.",
        input_model=NoArgs,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=orders_get_session,
    ),
    AIToolDefinition(
        name="bill_get_preview",
        description=(
            "Return deterministic Task 010 bill preview; AI does not calculate tax or totals."
        ),
        input_model=NoArgs,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=bill_get_preview,
    ),
    AIToolDefinition(
        name="customer_total_summary",
        description=(
            "Return the authoritative current cart and submitted-order money state. "
            "Do not calculate or combine monetary values in the model."
        ),
        input_model=NoArgs,
        allowed_actor_types=CUSTOMER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=customer_total_summary,
    ),
]
