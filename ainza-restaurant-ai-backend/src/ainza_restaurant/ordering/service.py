from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ainza_restaurant.availability.service import AvailabilityService
from ainza_restaurant.billing.models import DiningInvoice
from ainza_restaurant.dining.models import DiningSession, RestaurantTable
from ainza_restaurant.domain.enums import (
    DiningOrderStatus,
    DiningSessionStatus,
    MenuStatus,
    MerchandisingStatus,
    OfferScopeType,
    OfferType,
    ReviewStatus,
)
from ainza_restaurant.kitchen.service import KitchenService
from ainza_restaurant.menu.models import Dish, DishVariant, ModifierGroup, ModifierOption
from ainza_restaurant.merchandising.models import (
    Offer,
    OfferCategoryScope,
    OfferComboItem,
    OfferDishScope,
    TodaysSpecial,
)
from ainza_restaurant.ordering.models import (
    CartItem,
    CartItemModifier,
    DiningCart,
    DiningOrder,
    DiningOrderItem,
    DiningOrderItemModifier,
)
from ainza_restaurant.ordering.schemas import (
    CartBatchAddItem,
    CartBatchAddItemResult,
    CartBatchAddRead,
    CartItemCreate,
    CartItemPatch,
    CartItemPricingRead,
    CartItemRead,
    CartModifierRead,
    CartOfferSelect,
    CartRead,
    CartSubmitRequest,
    OrderItemModifierRead,
    OrderItemRead,
    OrderRead,
    SelectedOfferRead,
)
from ainza_restaurant.restaurants.models import Restaurant, RestaurantOutlet


class CartNotFound(LookupError):
    code = "cart_not_available"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class CartConflict(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "cart_conflict",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class _Context:
    session: DiningSession
    table: RestaurantTable
    outlet: RestaurantOutlet
    restaurant: Restaurant


@dataclass(frozen=True)
class _DishTarget:
    dish: Dish
    variant: DishVariant | None
    modifiers: list[ModifierOption]


@dataclass(frozen=True)
class _CartEvaluation:
    read: CartRead
    raw_items: list[CartItem]
    offer: Offer | None


MONEY = Decimal("0.01")


class CartService:
    def __init__(self, session: AsyncSession, *, now: Callable[[], datetime] | None = None) -> None:
        self.session = session
        self._now = now or (lambda: datetime.now(UTC))

    def now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    async def get_cart(self, session_token: str) -> CartRead:
        context = await self._context(session_token)
        cart = await self._get_or_create_cart(context.session.id)
        return (await self._evaluate_cart(context, cart)).read

    async def add_item(self, session_token: str, data: CartItemCreate) -> CartRead:
        context = await self._open_context(session_token)
        await self._ensure_not_invoiced(context.session.id)
        cart = await self._get_or_create_cart(context.session.id)
        self._check_version(cart, data.expected_version)
        target = await self._validated_target(
            context, data.dish_id, data.variant_id, data.modifier_option_ids
        )
        available = await self._dish_available(target.dish)
        if not available:
            raise CartConflict("cart item is unavailable", code="cart_item_unavailable")
        item = CartItem(
            cart_id=cart.id,
            dish_id=target.dish.id,
            variant_id=target.variant.id if target.variant else None,
            quantity=data.quantity,
            customer_note=data.customer_note,
        )
        item.modifiers = [
            CartItemModifier(modifier_option_id=option.id) for option in target.modifiers
        ]
        cart.version += 1
        self.session.add(item)
        await self.session.commit()
        return await self.get_cart(session_token)

    async def add_items_batch(
        self,
        session_token: str,
        items: list[CartBatchAddItem],
        *,
        expected_version: int | None = None,
    ) -> CartBatchAddRead:
        """Validate the complete batch, then apply it in one cart transaction.

        Required entries make the whole operation fail; conditional entries are
        reported as skipped when they cannot be resolved or are unavailable.
        """
        if not items:
            raise CartConflict("cart batch must contain at least one item", code="cart_batch_empty")
        context = await self._open_context(session_token)
        await self._ensure_not_invoiced(context.session.id)
        cart = await self._get_or_create_cart(context.session.id)
        self._check_version(cart, expected_version)
        prepared: list[tuple[int, CartBatchAddItem, _DishTarget]] = []
        results: list[CartBatchAddItemResult] = []
        for index, data in enumerate(items):
            if data.dish_id is None:
                if data.required:
                    raise CartConflict(
                        "required cart item could not be resolved",
                        code="cart_batch_item_unresolved",
                        details={"index": index, "requested_reference": data.requested_reference},
                    )
                results.append(
                    CartBatchAddItemResult(
                        index=index,
                        requested_quantity=data.quantity,
                        status="skipped",
                        reason="item was not found on the current menu",
                        requested_reference=data.requested_reference,
                    )
                )
                continue
            try:
                target = await self._validated_target(
                    context, data.dish_id, data.variant_id, data.modifier_option_ids
                )
                if not await self._dish_available(target.dish):
                    raise CartConflict("cart item is unavailable", code="cart_item_unavailable")
            except (CartConflict, CartNotFound) as exc:
                if data.required:
                    raise
                results.append(
                    CartBatchAddItemResult(
                        index=index,
                        dish_id=data.dish_id,
                        requested_quantity=data.quantity,
                        status="skipped",
                        reason=str(exc),
                        requested_reference=data.requested_reference,
                    )
                )
                continue
            prepared.append((index, data, target))
        for index, data, target in prepared:
            item = CartItem(
                cart_id=cart.id,
                dish_id=target.dish.id,
                variant_id=target.variant.id if target.variant else None,
                quantity=data.quantity,
                customer_note=data.customer_note,
            )
            item.modifiers = [
                CartItemModifier(modifier_option_id=option.id) for option in target.modifiers
            ]
            self.session.add(item)
            results.append(
                CartBatchAddItemResult(
                    index=index,
                    dish_id=data.dish_id,
                    requested_quantity=data.quantity,
                    added_quantity=data.quantity,
                    status="added",
                    requested_reference=data.requested_reference,
                )
            )
        if prepared:
            cart.version += 1
            await self.session.commit()
        cart_read = await self.get_cart(session_token)
        return CartBatchAddRead(
            cart=cart_read,
            overall_status=(
                "SUCCESS_WITH_OPTIONAL_SKIPS"
                if any(result.status == "skipped" for result in results)
                else "SUCCESS"
            ),
            items=sorted(results, key=lambda result: result.index),
        )

    async def patch_item(self, session_token: str, item_id: UUID, data: CartItemPatch) -> CartRead:
        context = await self._open_context(session_token)
        await self._ensure_not_invoiced(context.session.id)
        cart = await self._cart_for_session(context.session.id)
        self._check_version(cart, data.expected_version)
        item = await self._cart_item(cart.id, item_id)
        modifier_ids = (
            data.modifier_option_ids
            if data.modifier_option_ids is not None
            else [modifier.modifier_option_id for modifier in item.modifiers]
        )
        await self._validated_target(context, item.dish_id, item.variant_id, modifier_ids)
        if data.quantity is not None:
            item.quantity = data.quantity
        if "customer_note" in data.model_fields_set:
            item.customer_note = data.customer_note
        if data.modifier_option_ids is not None:
            await self.session.execute(
                delete(CartItemModifier).where(CartItemModifier.cart_item_id == item.id)
            )
            item.modifiers = [
                CartItemModifier(cart_item_id=item.id, modifier_option_id=option_id)
                for option_id in data.modifier_option_ids
            ]
        cart.version += 1
        await self.session.commit()
        return await self.get_cart(session_token)

    async def remove_item(
        self, session_token: str, item_id: UUID, *, expected_version: int | None
    ) -> CartRead:
        context = await self._open_context(session_token)
        await self._ensure_not_invoiced(context.session.id)
        cart = await self._cart_for_session(context.session.id)
        self._check_version(cart, expected_version)
        item = await self._cart_item(cart.id, item_id)
        await self.session.delete(item)
        cart.version += 1
        await self.session.commit()
        return await self.get_cart(session_token)

    async def select_offer(self, session_token: str, data: CartOfferSelect) -> CartRead:
        context = await self._open_context(session_token)
        await self._ensure_not_invoiced(context.session.id)
        cart = await self._get_or_create_cart(context.session.id)
        self._check_version(cart, data.expected_version)
        if data.offer_id is not None:
            await self._effective_offer(context.outlet.id, data.offer_id)
        cart.selected_offer_id = data.offer_id
        cart.version += 1
        await self.session.commit()
        return await self.get_cart(session_token)

    async def submit_cart(self, session_token: str, data: CartSubmitRequest) -> OrderRead:
        if not data.confirm:
            raise CartConflict(
                "order submission requires confirm=true",
                code="order_submission_confirmation_required",
            )
        context = await self._open_context(session_token)
        await self._ensure_not_invoiced(context.session.id)
        existing = await self._order_by_idempotency(context.session.id, data.idempotency_key)
        if existing is not None:
            return await self._order_read(existing)
        cart = await self._cart_for_session(context.session.id)
        evaluation = await self._evaluate_cart(context, cart)
        if not evaluation.read.items:
            raise CartConflict("cart is empty", code="cart_empty")
        if evaluation.read.unavailable_item_ids:
            raise CartConflict(
                "cart contains unavailable items",
                code="cart_contains_unavailable_items",
                details={
                    "cart_item_ids": [str(item) for item in evaluation.read.unavailable_item_ids]
                },
            )
        if evaluation.read.quote_token != data.quote_token:
            raise CartConflict(
                "cart quote is stale",
                code="cart_quote_stale",
                details={"current_quote_token": evaluation.read.quote_token},
            )
        round_number = await self._next_round_number(context.session.id)
        now = self.now()
        order = DiningOrder(
            dining_session_id=context.session.id,
            round_number=round_number,
            status=DiningOrderStatus.SUBMITTED,
            currency_code=evaluation.read.currency_code,
            subtotal_before_discount=evaluation.read.subtotal_before_offer,
            discount_amount=evaluation.read.discount_amount,
            subtotal_after_discount=evaluation.read.subtotal_after_discount,
            selected_offer_id=evaluation.offer.id if evaluation.offer else None,
            offer_name_snapshot=evaluation.offer.name if evaluation.offer else None,
            offer_type_snapshot=evaluation.offer.offer_type if evaluation.offer else None,
            idempotency_key=data.idempotency_key,
            submitted_at=now,
        )
        self.session.add(order)
        await self.session.flush()
        try:
            item_by_id = {item.id: item for item in evaluation.raw_items}
            for line in evaluation.read.items:
                source = item_by_id[line.id]
                order_item = DiningOrderItem(
                    order_id=order.id,
                    dish_id=line.dish_id,
                    variant_id=line.variant_id,
                    dish_name_snapshot=line.dish_name,
                    variant_name_snapshot=line.variant_name,
                    quantity=line.quantity,
                    customer_note_snapshot=line.customer_note,
                    catalog_unit_price_snapshot=line.pricing.catalog_unit_price,
                    special_unit_price_snapshot=line.pricing.special_unit_price,
                    effective_base_unit_price_snapshot=line.pricing.effective_base_unit_price,
                    modifier_unit_total_snapshot=line.pricing.modifier_unit_total,
                    configured_unit_price_snapshot=line.pricing.configured_unit_price,
                    line_subtotal_snapshot=line.pricing.line_subtotal,
                    tax_category_code_snapshot=(await self._dish(source.dish_id)).tax_category_code,
                )
                order_item.modifiers = [
                    DiningOrderItemModifier(
                        modifier_option_id=modifier.modifier_option_id,
                        modifier_group_name_snapshot=modifier.modifier_group_name,
                        modifier_option_name_snapshot=modifier.modifier_option_name,
                        price_delta_snapshot=modifier.price_delta,
                    )
                    for modifier in line.modifiers
                ]
                self.session.add(order_item)
            await self.session.flush()
            await KitchenService(self.session, now=self._now).create_ticket_for_order(
                order.id,
                outlet_id=context.outlet.id,
                table_label_snapshot=context.table.label,
            )
            await self.session.execute(delete(CartItem).where(CartItem.cart_id == cart.id))
            cart.selected_offer_id = None
            cart.version += 1
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            existing_after_race = await self._order_by_idempotency(
                context.session.id, data.idempotency_key
            )
            if existing_after_race is not None:
                return await self._order_read(existing_after_race)
            raise CartConflict(
                "duplicate order submission", code="order_submission_duplicate"
            ) from exc
        except Exception:
            await self.session.rollback()
            raise
        return await self._order_read_by_id(order.id)

    async def list_orders(self, session_token: str) -> list[OrderRead]:
        context = await self._context(session_token)
        result = await self.session.execute(
            select(DiningOrder)
            .where(DiningOrder.dining_session_id == context.session.id)
            .order_by(DiningOrder.round_number)
        )
        return [await self._order_read(order) for order in result.scalars()]

    async def _context(self, session_token: str) -> _Context:
        result = await self.session.execute(
            select(DiningSession, RestaurantTable, RestaurantOutlet, Restaurant)
            .join(RestaurantTable, RestaurantTable.id == DiningSession.table_id)
            .join(RestaurantOutlet, RestaurantOutlet.id == RestaurantTable.outlet_id)
            .join(Restaurant, Restaurant.id == RestaurantOutlet.restaurant_id)
            .where(DiningSession.public_session_token == session_token)
        )
        row = result.one_or_none()
        if row is None:
            raise CartNotFound("dining session not found", code="dining_session_not_found")
        dining_session, table, outlet, restaurant = row
        return _Context(dining_session, table, outlet, restaurant)

    async def _open_context(self, session_token: str) -> _Context:
        context = await self._context(session_token)
        if context.session.status != DiningSessionStatus.OPEN:
            raise CartConflict("dining session is closed", code="cart_session_closed")
        return context

    async def _ensure_not_invoiced(self, dining_session_id: UUID) -> None:
        invoice_id = await self.session.scalar(
            select(DiningInvoice.id).where(DiningInvoice.dining_session_id == dining_session_id)
        )
        if invoice_id is not None:
            raise CartConflict(
                "ordering is closed for billing",
                code="ordering_closed_for_billing",
            )

    async def _get_or_create_cart(self, dining_session_id: UUID) -> DiningCart:
        cart = await self._cart_for_session_or_none(dining_session_id)
        if cart is not None:
            return cart
        cart = DiningCart(dining_session_id=dining_session_id)
        self.session.add(cart)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self._cart_for_session_or_none(dining_session_id)
            if existing is not None:
                return existing
            raise
        return await self._cart_for_session(dining_session_id)

    async def _cart_for_session(self, dining_session_id: UUID) -> DiningCart:
        cart = await self._cart_for_session_or_none(dining_session_id)
        if cart is None:
            raise CartNotFound("cart not found", code="cart_not_available")
        return cart

    async def _cart_for_session_or_none(self, dining_session_id: UUID) -> DiningCart | None:
        return (
            await self.session.execute(
                select(DiningCart)
                .options(
                    selectinload(DiningCart.items).selectinload(CartItem.modifiers),
                )
                .execution_options(populate_existing=True)
                .where(DiningCart.dining_session_id == dining_session_id)
            )
        ).scalar_one_or_none()

    async def _cart_item(self, cart_id: UUID, item_id: UUID) -> CartItem:
        item = (
            await self.session.execute(
                select(CartItem)
                .options(selectinload(CartItem.modifiers))
                .where(CartItem.id == item_id, CartItem.cart_id == cart_id)
            )
        ).scalar_one_or_none()
        if item is None:
            raise CartNotFound("cart item not found", code="cart_item_not_found")
        return item

    def _check_version(self, cart: DiningCart, expected_version: int | None) -> None:
        if expected_version is not None and expected_version != cart.version:
            raise CartConflict("cart version conflict", code="cart_version_conflict")

    async def _validated_target(
        self,
        context: _Context,
        dish_id: UUID,
        variant_id: UUID | None,
        modifier_option_ids: list[UUID],
    ) -> _DishTarget:
        dish = await self._customer_visible_dish(context, dish_id)
        active_variants = [variant for variant in dish.variants if variant.is_active]
        variant = None
        if active_variants and variant_id is None:
            raise CartConflict("variant is required", code="cart_variant_required")
        if not active_variants and variant_id is not None:
            raise CartConflict("variant is not valid for dish", code="cart_variant_wrong_dish")
        if not active_variants and dish.base_price is None:
            raise CartConflict("dish has no orderable price", code="cart_dish_not_customer_visible")
        if variant_id is not None:
            variant = next((item for item in active_variants if item.id == variant_id), None)
            if variant is None:
                raise CartConflict(
                    "variant does not belong to dish", code="cart_variant_wrong_dish"
                )
        modifiers = await self._validate_modifiers(dish, modifier_option_ids)
        return _DishTarget(dish=dish, variant=variant, modifiers=modifiers)

    async def _customer_visible_dish(self, context: _Context, dish_id: UUID) -> Dish:
        dish = await self._dish(dish_id)
        if dish.menu.outlet_id != context.outlet.id:
            raise CartConflict(
                "dish belongs to another outlet", code="cart_dish_not_customer_visible"
            )
        if dish.menu.status != MenuStatus.PUBLISHED or not dish.menu.outlet_id:
            raise CartConflict(
                "dish is not in a published menu", code="cart_dish_not_customer_visible"
            )
        if not dish.category or not dish.category.is_active:
            raise CartConflict("dish category is inactive", code="cart_dish_not_customer_visible")
        if not dish.is_active or dish.review_status not in (
            ReviewStatus.CONFIRMED,
            ReviewStatus.APPROVED,
        ):
            raise CartConflict(
                "dish is not customer visible", code="cart_dish_not_customer_visible"
            )
        restaurant_status = getattr(context.restaurant.status, "value", context.restaurant.status)
        if not context.outlet.is_active or restaurant_status != "active":
            raise CartConflict("cart is not available", code="cart_not_available")
        return dish

    async def _dish(self, dish_id: UUID) -> Dish:
        dish = (
            await self.session.execute(
                select(Dish)
                .options(
                    selectinload(Dish.menu),
                    selectinload(Dish.category),
                    selectinload(Dish.variants),
                    selectinload(Dish.modifier_groups).selectinload(ModifierGroup.options),
                )
                .where(Dish.id == dish_id)
            )
        ).scalar_one_or_none()
        if dish is None:
            raise CartNotFound("dish not found", code="cart_dish_not_customer_visible")
        return dish

    async def _validate_modifiers(
        self, dish: Dish, modifier_option_ids: list[UUID]
    ) -> list[ModifierOption]:
        if len(set(modifier_option_ids)) != len(modifier_option_ids):
            raise CartConflict("duplicate modifier option", code="cart_modifier_selection_invalid")
        groups = [group for group in dish.modifier_groups if group.is_active]
        options_by_id = {
            option.id: option for group in groups for option in group.options if option.is_active
        }
        selected: list[ModifierOption] = []
        for option_id in modifier_option_ids:
            option = options_by_id.get(option_id)
            if option is None:
                raise CartConflict("invalid modifier option", code="cart_modifier_invalid")
            selected.append(option)
        counts: dict[UUID, int] = {}
        for option in selected:
            counts[option.group_id] = counts.get(option.group_id, 0) + 1
        for group in groups:
            count = counts.get(group.id, 0)
            if count < group.min_selections or count > group.max_selections:
                raise CartConflict(
                    "modifier selection outside group bounds",
                    code="cart_modifier_selection_invalid",
                )
        return selected

    async def _dish_available(self, dish: Dish) -> bool:
        return (
            await AvailabilityService(self.session, now=self._now).dish_availability(dish.id)
        ).available

    async def _evaluate_cart(self, context: _Context, cart: DiningCart) -> _CartEvaluation:
        raw_items = sorted(cart.items, key=lambda item: (item.created_at, str(item.id)))
        lines: list[CartItemRead] = []
        subtotal = Decimal("0")
        unavailable: list[UUID] = []
        for item in raw_items:
            dish = await self._customer_visible_dish(context, item.dish_id)
            variant = await self._variant_for_item(dish, item.variant_id)
            modifier_ids = [modifier.modifier_option_id for modifier in item.modifiers]
            modifiers = await self._validate_modifiers(dish, modifier_ids)
            available = await self._dish_available(dish)
            if not available:
                unavailable.append(item.id)
            pricing = await self._pricing(dish, variant, modifiers, item.quantity)
            subtotal += pricing.line_subtotal
            lines.append(
                CartItemRead(
                    id=item.id,
                    dish_id=dish.id,
                    dish_name=dish.name,
                    variant_id=variant.id if variant else None,
                    variant_name=variant.name if variant else None,
                    quantity=item.quantity,
                    customer_note=item.customer_note,
                    available=available,
                    availability_status="available" if available else "sold_out",
                    pricing=pricing,
                    modifiers=[
                        CartModifierRead(
                            modifier_option_id=option.id,
                            modifier_group_id=option.group_id,
                            modifier_group_name=next(
                                group.name
                                for group in dish.modifier_groups
                                if group.id == option.group_id
                            ),
                            modifier_option_name=option.name,
                            price_delta=money(option.price_delta),
                        )
                        for option in sorted(
                            modifiers, key=lambda value: (value.group_id, value.name)
                        )
                    ],
                )
            )
        subtotal = money(subtotal)
        offer = await self._offer_for_cart(context.outlet.id, cart.selected_offer_id)
        selected_offer = await self._selected_offer_read(offer, lines)
        after_discount = money(max(subtotal - selected_offer.discount_amount, Decimal("0")))
        read_without_token = CartRead(
            dining_session_token=context.session.public_session_token,
            version=cart.version,
            currency_code=context.outlet.currency_code,
            item_count=len(lines),
            quantity_count=sum(line.quantity for line in lines),
            items=lines,
            subtotal_before_offer=subtotal,
            selected_offer=selected_offer,
            discount_amount=selected_offer.discount_amount,
            subtotal_after_discount=after_discount,
            can_submit=bool(lines) and not unavailable,
            unavailable_item_ids=unavailable,
            quote_token="",
        )
        return _CartEvaluation(
            read=read_without_token.model_copy(
                update={"quote_token": quote_token(read_without_token)}
            ),
            raw_items=raw_items,
            offer=offer if selected_offer.effective else None,
        )

    async def _variant_for_item(self, dish: Dish, variant_id: UUID | None) -> DishVariant | None:
        active = [variant for variant in dish.variants if variant.is_active]
        if active and variant_id is None:
            raise CartConflict("variant is required", code="cart_variant_required")
        if variant_id is None:
            return None
        variant = next((item for item in active if item.id == variant_id), None)
        if variant is None:
            raise CartConflict("variant does not belong to dish", code="cart_variant_wrong_dish")
        return variant

    async def _pricing(
        self,
        dish: Dish,
        variant: DishVariant | None,
        modifiers: list[ModifierOption],
        quantity: int,
    ) -> CartItemPricingRead:
        catalog = money(variant.price if variant is not None else dish.base_price or Decimal("0"))
        special = await self._special_price(dish, variant.id if variant else None)
        effective = special or catalog
        modifier_total = money(sum((option.price_delta for option in modifiers), Decimal("0")))
        configured = money(effective + modifier_total)
        return CartItemPricingRead(
            catalog_unit_price=catalog,
            special_unit_price=special,
            effective_base_unit_price=effective,
            modifier_unit_total=modifier_total,
            configured_unit_price=configured,
            quantity=quantity,
            line_subtotal=money(configured * quantity),
        )

    async def _special_price(self, dish: Dish, variant_id: UUID | None) -> Decimal | None:
        now = self.now()
        special = (
            await self.session.execute(
                select(TodaysSpecial)
                .where(
                    TodaysSpecial.outlet_id == dish.menu.outlet_id,
                    TodaysSpecial.dish_id == dish.id,
                    TodaysSpecial.variant_id.is_(None)
                    if variant_id is None
                    else TodaysSpecial.variant_id == variant_id,
                    TodaysSpecial.status == MerchandisingStatus.ACTIVE,
                    TodaysSpecial.starts_at <= now,
                    TodaysSpecial.ends_at > now,
                    TodaysSpecial.special_price.is_not(None),
                )
                .order_by(TodaysSpecial.created_at.desc())
            )
        ).scalar_one_or_none()
        if special and special.special_price is not None:
            return money(special.special_price)
        return None

    async def _offer_for_cart(self, outlet_id: UUID, offer_id: UUID | None) -> Offer | None:
        if offer_id is None:
            return None
        now = self.now()
        return (
            await self.session.execute(
                select(Offer).where(
                    Offer.id == offer_id,
                    Offer.outlet_id == outlet_id,
                    Offer.status == MerchandisingStatus.ACTIVE,
                    Offer.starts_at <= now,
                    Offer.ends_at > now,
                )
            )
        ).scalar_one_or_none()

    async def _effective_offer(self, outlet_id: UUID, offer_id: UUID) -> Offer:
        offer = await self._offer_for_cart(outlet_id, offer_id)
        if offer is None:
            raise CartConflict("offer is not effective", code="cart_offer_not_effective")
        return offer

    async def _selected_offer_read(
        self, offer: Offer | None, lines: list[CartItemRead]
    ) -> SelectedOfferRead:
        if offer is None:
            return SelectedOfferRead(
                offer_id=None,
                name=None,
                offer_type=None,
                effective=False,
                eligible=False,
                amount_to_threshold=None,
                discount_amount=Decimal("0.00"),
            )
        dish_scope = set(
            (
                await self.session.execute(
                    select(OfferDishScope.dish_id).where(OfferDishScope.offer_id == offer.id)
                )
            ).scalars()
        )
        category_scope = set(
            (
                await self.session.execute(
                    select(OfferCategoryScope.category_id).where(
                        OfferCategoryScope.offer_id == offer.id
                    )
                )
            ).scalars()
        )
        eligible_subtotal = Decimal("0")
        for line in lines:
            if await self._line_eligible(offer, line, dish_scope, category_scope):
                eligible_subtotal += line.pricing.line_subtotal
        eligible_subtotal = money(eligible_subtotal)
        if offer.offer_type == OfferType.COMBO_FIXED_PRICE:
            discount = await self._combo_discount(offer, lines)
            eligible = discount > 0
            amount = None
        else:
            threshold = offer.minimum_subtotal or Decimal("0")
            eligible = eligible_subtotal >= threshold
            amount = money(max(threshold - eligible_subtotal, Decimal("0")))
            discount = Decimal("0")
            if eligible:
                if offer.offer_type == OfferType.PERCENTAGE:
                    discount = money(
                        eligible_subtotal * (offer.discount_value or Decimal("0")) / Decimal("100")
                    )
                    if offer.maximum_discount is not None:
                        discount = min(discount, money(offer.maximum_discount))
                else:
                    discount = min(money(offer.discount_value or Decimal("0")), eligible_subtotal)
        return SelectedOfferRead(
            offer_id=offer.id,
            name=offer.name,
            offer_type=offer.offer_type,
            effective=True,
            eligible=eligible,
            amount_to_threshold=amount,
            discount_amount=money(discount),
        )

    async def _line_eligible(
        self,
        offer: Offer,
        line: CartItemRead,
        dish_scope: set[UUID],
        category_scope: set[UUID],
    ) -> bool:
        if offer.scope_type == OfferScopeType.ALL_ITEMS:
            return True
        if offer.scope_type == OfferScopeType.SELECTED_DISHES:
            return line.dish_id in dish_scope
        dish = await self._dish(line.dish_id)
        return dish.category_id in category_scope

    async def _combo_discount(self, offer: Offer, lines: list[CartItemRead]) -> Decimal:
        rows = list(
            (
                await self.session.execute(
                    select(OfferComboItem).where(OfferComboItem.offer_id == offer.id)
                )
            ).scalars()
        )
        if not rows:
            return Decimal("0")
        counts: dict[tuple[UUID, UUID | None], int] = {}
        prices: dict[tuple[UUID, UUID | None], Decimal] = {}
        for line in lines:
            key = (line.dish_id, line.variant_id)
            counts[key] = counts.get(key, 0) + line.quantity
            prices[key] = line.pricing.configured_unit_price
        complete: int | None = None
        regular_bundle = Decimal("0")
        for row in rows:
            key = (row.dish_id, row.variant_id)
            complete_for_item = counts.get(key, 0) // row.required_quantity
            complete = complete_for_item if complete is None else min(complete, complete_for_item)
            regular_bundle += prices.get(key, Decimal("0")) * row.required_quantity
        count = complete or 0
        combo_price = money(offer.combo_price or Decimal("0"))
        return money(max((regular_bundle - combo_price) * count, Decimal("0")))

    async def _next_round_number(self, dining_session_id: UUID) -> int:
        current = await self.session.scalar(
            select(func.max(DiningOrder.round_number)).where(
                DiningOrder.dining_session_id == dining_session_id
            )
        )
        return int(current or 0) + 1

    async def _order_by_idempotency(
        self, dining_session_id: UUID, idempotency_key: str
    ) -> DiningOrder | None:
        return (
            await self.session.execute(
                select(DiningOrder).where(
                    DiningOrder.dining_session_id == dining_session_id,
                    DiningOrder.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()

    async def _order_read(self, order: DiningOrder) -> OrderRead:
        return await self._order_read_by_id(order.id)

    async def _order_read_by_id(self, order_id: UUID) -> OrderRead:
        fresh = (
            await self.session.execute(
                select(DiningOrder)
                .options(
                    selectinload(DiningOrder.items).selectinload(DiningOrderItem.modifiers),
                )
                .where(DiningOrder.id == order_id)
            )
        ).scalar_one()
        return OrderRead(
            id=fresh.id,
            dining_session_id=fresh.dining_session_id,
            round_number=fresh.round_number,
            status=fresh.status,
            currency_code=fresh.currency_code,
            subtotal_before_discount=money(fresh.subtotal_before_discount),
            discount_amount=money(fresh.discount_amount),
            subtotal_after_discount=money(fresh.subtotal_after_discount),
            selected_offer_id=fresh.selected_offer_id,
            offer_name_snapshot=fresh.offer_name_snapshot,
            offer_type_snapshot=fresh.offer_type_snapshot,
            idempotency_key=fresh.idempotency_key,
            submitted_at=fresh.submitted_at,
            items=[
                OrderItemRead(
                    id=item.id,
                    dish_id=item.dish_id,
                    variant_id=item.variant_id,
                    dish_name_snapshot=item.dish_name_snapshot,
                    variant_name_snapshot=item.variant_name_snapshot,
                    quantity=item.quantity,
                    customer_note_snapshot=item.customer_note_snapshot,
                    catalog_unit_price_snapshot=money(item.catalog_unit_price_snapshot),
                    special_unit_price_snapshot=money(item.special_unit_price_snapshot)
                    if item.special_unit_price_snapshot is not None
                    else None,
                    effective_base_unit_price_snapshot=money(
                        item.effective_base_unit_price_snapshot
                    ),
                    modifier_unit_total_snapshot=money(item.modifier_unit_total_snapshot),
                    configured_unit_price_snapshot=money(item.configured_unit_price_snapshot),
                    line_subtotal_snapshot=money(item.line_subtotal_snapshot),
                    tax_category_code_snapshot=item.tax_category_code_snapshot,
                    modifiers=[
                        OrderItemModifierRead(
                            modifier_option_id=modifier.modifier_option_id,
                            modifier_group_name_snapshot=modifier.modifier_group_name_snapshot,
                            modifier_option_name_snapshot=modifier.modifier_option_name_snapshot,
                            price_delta_snapshot=money(modifier.price_delta_snapshot),
                        )
                        for modifier in item.modifiers
                    ],
                )
                for item in sorted(fresh.items, key=lambda value: (value.created_at, str(value.id)))
            ],
        )


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def quote_token(cart: CartRead) -> str:
    payload = cart.model_dump(mode="json")
    payload["quote_token"] = ""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
