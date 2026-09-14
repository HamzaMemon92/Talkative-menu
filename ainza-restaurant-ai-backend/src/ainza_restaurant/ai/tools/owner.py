from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.ai.context import AIActorType, AIToolContext
from ainza_restaurant.ai.errors import AIToolScopeError
from ainza_restaurant.ai.models import AIToolSafetyLevel
from ainza_restaurant.ai.tools.definitions import AIToolDefinition
from ainza_restaurant.audit.service import AuditService
from ainza_restaurant.availability.schemas import AvailabilityProposalCreate
from ainza_restaurant.availability.service import AvailabilityService
from ainza_restaurant.customer_menu.service import CustomerMenuService
from ainza_restaurant.domain.enums import (
    AuditActionType,
    AvailabilityAction,
    AvailabilityDurationMode,
    AvailabilityReasonCode,
    AvailabilityTargetType,
    DietaryClassification,
    ItemType,
    ReviewStatus,
)
from ainza_restaurant.menu.models import Category, Dish
from ainza_restaurant.menu.schemas import CategoryCreate, DishCreate
from ainza_restaurant.menu.service import MenuService


class OwnerAvailabilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool | None = None
    category_id: UUID | None = None


class OwnerCreateAvailabilityProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: AvailabilityTargetType
    target_id: UUID
    action: AvailabilityAction
    duration_mode: AvailabilityDurationMode | None = None
    requested_until: datetime | None = None
    reason_code: AvailabilityReasonCode | None = None
    reason_note: str | None = None


class OwnerProposalIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: UUID


class OwnerPricePreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dish_name: str = Field(min_length=1, max_length=200)
    new_price: Decimal = Field(ge=Decimal("0"))


class OwnerPriceChangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dish_name: str = Field(min_length=1, max_length=200)
    new_price: Decimal = Field(ge=Decimal("0"))


class OwnerAddDishInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_name: str = Field(min_length=1, max_length=120)
    dish_name: str = Field(min_length=1, max_length=200)
    price: Decimal = Field(ge=Decimal("0"))
    description: str | None = Field(default=None, max_length=1000)


class OwnerPublishMenuInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = True


async def owner_get_availability(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    data = cast(OwnerAvailabilityInput, payload)
    return await AvailabilityService(session).outlet_availability(
        context.outlet_id,
        available=data.available,
        category_id=data.category_id,
    )


async def owner_create_availability_proposal(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    data = cast(OwnerCreateAvailabilityProposalInput, payload)
    return await AvailabilityService(session).create_proposal(
        context.outlet_id,
        AvailabilityProposalCreate(
            target_type=data.target_type,
            target_id=data.target_id,
            action=data.action,
            duration_mode=data.duration_mode,
            requested_until=data.requested_until,
            reason_code=data.reason_code,
            reason_note=data.reason_note,
        ),
    )


async def owner_get_availability_proposal(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    data = cast(OwnerProposalIdInput, payload)
    proposal = await AvailabilityService(session).get_proposal(data.proposal_id)
    if proposal.outlet_id != context.outlet_id:
        raise AIToolScopeError("availability proposal does not belong to context outlet")
    return proposal


async def owner_confirm_availability_proposal(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    data = cast(OwnerProposalIdInput, payload)
    proposal = await AvailabilityService(session).get_proposal(data.proposal_id)
    if proposal.outlet_id != context.outlet_id:
        raise AIToolScopeError("availability proposal does not belong to context outlet")
    result = await AvailabilityService(session).confirm_proposal(data.proposal_id, confirm=True)
    await AuditService(session).record(
        outlet_id=context.outlet_id,
        action_type=AuditActionType.AVAILABILITY_OVERRIDE,
        target_type="PROPOSAL",
        target_id=str(data.proposal_id),
        previous_value={"status": "pending"},
        new_value={"status": "confirmed", "action": proposal.action.value},
        source="owner_ai",
    )
    return result


async def owner_preview_price_change(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> dict[str, object]:
    data = cast(OwnerPricePreviewInput, payload)
    menu = await CustomerMenuService(session).get_menu(context.outlet_id)
    matching = [
        d for cat in menu.categories for d in cat.dishes if data.dish_name.lower() in d.name.lower()
    ]
    if not matching:
        return {
            "error": "dish_not_found",
            "message": f"Could not find dish matching '{data.dish_name}'",
        }

    exact_matches = [d for d in matching if d.name.lower() == data.dish_name.lower()]
    if len(exact_matches) == 1:
        dish = exact_matches[0]
    elif len(matching) > 1:
        candidates = [d.name for d in matching]
        return {
            "error": "ambiguous_dish",
            "message": (
                f"Multiple dishes match '{data.dish_name}': {', '.join(candidates)}. "
                "Please specify the exact dish name."
            ),
            "candidates": candidates,
        }
    else:
        dish = matching[0]

    old_price = (
        getattr(dish, "base_price", None)
        or (dish.pricing.effective_price if hasattr(dish, "pricing") and dish.pricing else None)
        or Decimal("0.00")
    )

    return {
        "action": "price_change_preview",
        "dish_name": dish.name,
        "old_price": str(old_price),
        "new_price": str(data.new_price),
        "confirmation_required": True,
        "preview": (
            f"Change {dish.name} price: INR {old_price} -> INR {data.new_price}. "
            "Please confirm to apply."
        ),
    }


async def owner_apply_price_change(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> dict[str, object]:
    data = cast(OwnerPriceChangeInput, payload)
    menu_service = MenuService(session)
    draft_menu = await menu_service.create_draft_revision(context.outlet_id)

    # Find the dish in the draft menu
    stmt = select(Dish).where(
        Dish.menu_id == draft_menu.id,
        Dish.name.ilike(f"%{data.dish_name}%"),
    )
    dishes = (await session.scalars(stmt)).all()
    if not dishes:
        return {
            "error": "dish_not_found_in_draft",
            "message": f"Dish '{data.dish_name}' not found in draft menu.",
        }

    exact_matches = [d for d in dishes if d.name.lower() == data.dish_name.lower()]
    if len(exact_matches) == 1:
        dish = exact_matches[0]
    elif len(dishes) > 1:
        candidates = [d.name for d in dishes]
        return {
            "error": "ambiguous_dish",
            "message": (
                f"Multiple dishes match '{data.dish_name}': {', '.join(candidates)}. "
                "Please specify the exact dish name."
            ),
            "candidates": candidates,
        }
    else:
        dish = dishes[0]

    old_price, new_price = await menu_service.update_dish_price(dish.id, data.new_price)
    await AuditService(session).record(
        outlet_id=context.outlet_id,
        action_type=AuditActionType.PRICE_CHANGE,
        target_type="DISH",
        target_id=str(dish.id),
        previous_value={"price": str(old_price), "dish_name": dish.name},
        new_value={"price": str(new_price), "dish_name": dish.name},
        source="owner_ai",
    )
    return {
        "status": "updated_in_draft",
        "dish_name": dish.name,
        "old_price": str(old_price),
        "new_price": str(new_price),
        "message": (
            f"Price of {dish.name} updated to INR {new_price} in draft menu. Ready to publish."
        ),
    }


async def owner_add_dish(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> dict[str, object]:
    data = cast(OwnerAddDishInput, payload)
    menu_service = MenuService(session)
    draft_menu = await menu_service.create_draft_revision(context.outlet_id)

    # Find or create category in draft menu
    cat_stmt = select(Category).where(
        Category.menu_id == draft_menu.id,
        Category.name.ilike(f"%{data.category_name}%"),
    )
    category = await session.scalar(cat_stmt)
    if category is None:
        category = await menu_service.create_category(
            draft_menu.id, CategoryCreate(name=data.category_name)
        )

    dish = await menu_service.create_dish(
        draft_menu.id,
        DishCreate(
            category_id=category.id,
            name=data.dish_name,
            base_price=data.price,
            description=data.description,
            item_type=ItemType.FOOD,
            dietary_classification=DietaryClassification.UNKNOWN,
            review_status=ReviewStatus.CONFIRMED,
        ),
    )
    await AuditService(session).record(
        outlet_id=context.outlet_id,
        action_type=AuditActionType.DISH_CREATE,
        target_type="DISH",
        target_id=str(dish.id),
        new_value={"name": dish.name, "price": str(dish.base_price), "category": category.name},
        source="owner_ai",
    )
    return {
        "status": "created_in_draft",
        "dish_id": str(dish.id),
        "dish_name": dish.name,
        "price": str(dish.base_price),
        "category_name": category.name,
        "message": (
            f"Added '{dish.name}' to {category.name} for INR {dish.base_price} in draft menu."
        ),
    }


async def owner_publish_menu(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> dict[str, object]:
    data = cast(OwnerPublishMenuInput, payload)
    if not data.confirm:
        return {"status": "cancelled", "message": "Publish cancelled."}

    menu_service = MenuService(session)
    published = await menu_service.publish_draft_revision(context.outlet_id)
    await AuditService(session).record(
        outlet_id=context.outlet_id,
        action_type=AuditActionType.MENU_PUBLISH,
        target_type="MENU",
        target_id=str(published.id),
        source="owner_ai",
    )
    return {
        "status": "published",
        "menu_id": str(published.id),
        "message": "Draft menu revision published successfully as live menu.",
    }


OWNER = frozenset({AIActorType.OWNER})

OWNER_TOOLS = [
    AIToolDefinition(
        name="owner_get_availability",
        description="Return outlet-scoped availability for the server-bound owner outlet.",
        input_model=OwnerAvailabilityInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=owner_get_availability,
    ),
    AIToolDefinition(
        name="owner_create_availability_proposal",
        description=(
            "Create an availability proposal preview for the server-bound outlet. "
            "This does not immediately change availability."
        ),
        input_model=OwnerCreateAvailabilityProposalInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.REVERSIBLE_MUTATION,
        requires_confirmation=False,
        handler=owner_create_availability_proposal,
    ),
    AIToolDefinition(
        name="owner_get_availability_proposal",
        description="Read an outlet-scoped availability proposal.",
        input_model=OwnerProposalIdInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=owner_get_availability_proposal,
    ),
    AIToolDefinition(
        name="owner_confirm_availability_proposal",
        description=(
            "Confirm an availability proposal. Requires external human confirmation "
            "outside model-generated arguments."
        ),
        input_model=OwnerProposalIdInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.CONSEQUENTIAL_MUTATION,
        requires_confirmation=True,
        handler=owner_confirm_availability_proposal,
    ),
    AIToolDefinition(
        name="owner_preview_price_change",
        description=(
            "Preview a dish price change without modifying menu. "
            "Returns old vs new price for confirmation."
        ),
        input_model=OwnerPricePreviewInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=owner_preview_price_change,
    ),
    AIToolDefinition(
        name="owner_apply_price_change",
        description=(
            "Apply price change in draft menu. Consequential mutation requiring confirmation."
        ),
        input_model=OwnerPriceChangeInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.CONSEQUENTIAL_MUTATION,
        requires_confirmation=True,
        handler=owner_apply_price_change,
    ),
    AIToolDefinition(
        name="owner_add_dish",
        description="Add a new dish to the draft menu with category, name, and price.",
        input_model=OwnerAddDishInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.REVERSIBLE_MUTATION,
        requires_confirmation=False,
        handler=owner_add_dish,
    ),
    AIToolDefinition(
        name="owner_publish_menu",
        description=(
            "Publish current draft menu revision to make it the live outlet menu. "
            "Requires confirmation."
        ),
        input_model=OwnerPublishMenuInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.CONSEQUENTIAL_MUTATION,
        requires_confirmation=True,
        handler=owner_publish_menu,
    ),
]
