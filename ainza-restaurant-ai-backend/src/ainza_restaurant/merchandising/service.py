from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ainza_restaurant.availability.service import AvailabilityService
from ainza_restaurant.domain.enums import (
    MerchandisingStatus,
    OfferScopeType,
    OfferType,
    ReviewStatus,
    SpecialDurationMode,
)
from ainza_restaurant.menu.models import Category, Dish, Menu
from ainza_restaurant.merchandising.models import (
    FeaturedDish,
    Offer,
    OfferCategoryScope,
    OfferComboItem,
    OfferDishScope,
    TodaysSpecial,
)
from ainza_restaurant.merchandising.schemas import (
    ComboItemInput,
    ComboItemsReplace,
    FeaturedCreate,
    FeaturedPatch,
    FeaturedRead,
    OfferCreate,
    OfferPatch,
    OfferPreviewRead,
    OfferPreviewRequest,
    OfferRead,
    PreviewItem,
    PreviewLineRead,
    ScopeCategoryReplace,
    ScopeDishReplace,
    SpecialCreate,
    SpecialPatch,
    SpecialRead,
)
from ainza_restaurant.restaurants.models import RestaurantOutlet, WeeklyOperatingInterval


class MerchandisingNotFound(LookupError):
    code = "promotion_not_found"


class MerchandisingConflict(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "promotion_conflict",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class _LocalInterval:
    starts_at: datetime
    closes_at: datetime


@dataclass(frozen=True)
class _PricedItem:
    dish: Dish
    variant_id: UUID | None
    quantity: int
    unit_price: Decimal
    line_subtotal: Decimal
    available: bool


MONEY = Decimal("0.01")


class MerchandisingService:
    def __init__(self, session: AsyncSession, *, now: Callable[[], datetime] | None = None) -> None:
        self.session = session
        self._now = now or (lambda: datetime.now(UTC))

    def now(self) -> datetime:
        return _utc(self._now())

    async def create_special(self, outlet_id: UUID, data: SpecialCreate) -> SpecialRead:
        now = self.now()
        outlet = await self._outlet(outlet_id)
        dish = await self._promotion_dish(outlet_id, data.dish_id)
        await self._validate_variant(dish, data.variant_id)
        if data.special_price is not None and dish.variants and data.variant_id is None:
            raise MerchandisingConflict(
                "variant_id is required for variant dish special price",
                code="invalid_special_price",
            )
        starts_at, ends_at = await self._resolve_special_schedule(outlet, data, now)
        special = TodaysSpecial(
            outlet_id=outlet_id,
            dish_id=dish.id,
            variant_id=data.variant_id,
            special_price=data.special_price,
            starts_at=starts_at,
            ends_at=ends_at,
            display_note=data.display_note,
        )
        self.session.add(special)
        await self.session.commit()
        return await self.get_special(special.id)

    async def list_specials(self, outlet_id: UUID, *, effective: bool = False) -> list[SpecialRead]:
        await self._outlet(outlet_id)
        rows = (
            await self.session.execute(
                select(TodaysSpecial)
                .where(TodaysSpecial.outlet_id == outlet_id)
                .order_by(TodaysSpecial.starts_at, TodaysSpecial.created_at)
            )
        ).scalars()
        values = [await self._special_read(item) for item in rows]
        return [item for item in values if item.effective_active] if effective else values

    async def get_special(self, special_id: UUID) -> SpecialRead:
        return await self._special_read(await self._special(special_id))

    async def patch_special(self, special_id: UUID, data: SpecialPatch) -> SpecialRead:
        item = await self._special(special_id)
        self._ensure_mutable(item.status)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(item, key, _utc(value) if isinstance(value, datetime) else value)
        self._validate_schedule(item.starts_at, item.ends_at, "invalid_special_schedule")
        await self.session.commit()
        return await self.get_special(item.id)

    async def activate_special(self, special_id: UUID, *, confirm: bool) -> SpecialRead:
        if not confirm:
            raise MerchandisingConflict(
                "confirmation required", code="promotion_confirmation_required"
            )
        item = await self._special(special_id)
        await self._promotion_dish(item.outlet_id, item.dish_id)
        await self._validate_variant(await self._dish(item.dish_id), item.variant_id)
        await self._ensure_no_overlapping_special(item)
        item.status = MerchandisingStatus.ACTIVE
        item.activation_confirmed = True
        item.activated_at = self.now()
        await self.session.commit()
        await self.session.refresh(item)
        return await self.get_special(item.id)

    async def deactivate_special(self, special_id: UUID, *, confirm: bool) -> SpecialRead:
        if not confirm:
            raise MerchandisingConflict(
                "confirmation required", code="promotion_confirmation_required"
            )
        item = await self._special(special_id)
        item.status = MerchandisingStatus.DEACTIVATED
        item.deactivated_at = self.now()
        await self.session.commit()
        await self.session.refresh(item)
        return await self.get_special(item.id)

    async def create_featured(self, outlet_id: UUID, data: FeaturedCreate) -> FeaturedRead:
        await self._outlet(outlet_id)
        dish = await self._promotion_dish(outlet_id, data.dish_id)
        starts_at = _utc(data.starts_at) if data.starts_at else self.now()
        ends_at = _utc(data.ends_at) if data.ends_at else None
        if ends_at is not None and ends_at <= starts_at:
            raise MerchandisingConflict("invalid feature schedule", code="offer_schedule_invalid")
        item = FeaturedDish(
            outlet_id=outlet_id,
            dish_id=dish.id,
            starts_at=starts_at,
            ends_at=ends_at,
            display_order=data.display_order,
        )
        self.session.add(item)
        await self.session.commit()
        return await self.get_featured(item.id)

    async def list_featured(
        self, outlet_id: UUID, *, effective: bool = False
    ) -> list[FeaturedRead]:
        await self._outlet(outlet_id)
        rows = (
            await self.session.execute(
                select(FeaturedDish)
                .where(FeaturedDish.outlet_id == outlet_id)
                .order_by(FeaturedDish.display_order, FeaturedDish.created_at)
            )
        ).scalars()
        values = [await self._featured_read(item) for item in rows]
        return [item for item in values if item.effective_active] if effective else values

    async def get_featured(self, featured_id: UUID) -> FeaturedRead:
        return await self._featured_read(await self._featured(featured_id))

    async def patch_featured(self, featured_id: UUID, data: FeaturedPatch) -> FeaturedRead:
        item = await self._featured(featured_id)
        self._ensure_mutable(item.status)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(item, key, _utc(value) if isinstance(value, datetime) else value)
        if item.ends_at is not None and item.ends_at <= item.starts_at:
            raise MerchandisingConflict("invalid feature schedule", code="offer_schedule_invalid")
        await self.session.commit()
        return await self.get_featured(item.id)

    async def activate_featured(self, featured_id: UUID, *, confirm: bool) -> FeaturedRead:
        if not confirm:
            raise MerchandisingConflict(
                "confirmation required", code="promotion_confirmation_required"
            )
        item = await self._featured(featured_id)
        await self._promotion_dish(item.outlet_id, item.dish_id)
        item.status = MerchandisingStatus.ACTIVE
        item.activation_confirmed = True
        item.activated_at = self.now()
        await self.session.commit()
        await self.session.refresh(item)
        return await self.get_featured(item.id)

    async def deactivate_featured(self, featured_id: UUID, *, confirm: bool) -> FeaturedRead:
        if not confirm:
            raise MerchandisingConflict(
                "confirmation required", code="promotion_confirmation_required"
            )
        item = await self._featured(featured_id)
        item.status = MerchandisingStatus.DEACTIVATED
        item.deactivated_at = self.now()
        await self.session.commit()
        await self.session.refresh(item)
        return await self.get_featured(item.id)

    async def create_offer(self, outlet_id: UUID, data: OfferCreate) -> OfferRead:
        await self._outlet(outlet_id)
        offer = Offer(outlet_id=outlet_id, **data.model_dump())
        offer.starts_at = _utc(offer.starts_at)
        offer.ends_at = _utc(offer.ends_at)
        self.session.add(offer)
        await self.session.commit()
        return await self.get_offer(offer.id)

    async def list_offers(self, outlet_id: UUID, *, effective: bool = False) -> list[OfferRead]:
        await self._outlet(outlet_id)
        rows = (
            await self.session.execute(
                select(Offer).where(Offer.outlet_id == outlet_id).order_by(Offer.created_at)
            )
        ).scalars()
        values = [await self._offer_read(item) for item in rows]
        return [item for item in values if item.effective_active] if effective else values

    async def get_offer(self, offer_id: UUID) -> OfferRead:
        return await self._offer_read(await self._offer(offer_id))

    async def patch_offer(self, offer_id: UUID, data: OfferPatch) -> OfferRead:
        offer = await self._offer(offer_id)
        self._ensure_mutable(offer.status)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(offer, key, _utc(value) if isinstance(value, datetime) else value)
        self._validate_schedule(offer.starts_at, offer.ends_at, "offer_schedule_invalid")
        await self.session.commit()
        return await self.get_offer(offer.id)

    async def replace_offer_dish_scope(self, offer_id: UUID, data: ScopeDishReplace) -> OfferRead:
        offer = await self._offer(offer_id)
        self._ensure_mutable(offer.status)
        dishes = [await self._promotion_dish(offer.outlet_id, item) for item in data.dish_ids]
        await self.session.execute(
            delete(OfferDishScope).where(OfferDishScope.offer_id == offer_id)
        )
        self.session.add_all(
            [OfferDishScope(offer_id=offer_id, dish_id=dish.id) for dish in dishes]
        )
        offer.scope_type = OfferScopeType.SELECTED_DISHES
        await self.session.commit()
        await self.session.refresh(offer)
        return await self.get_offer(offer_id)

    async def replace_offer_category_scope(
        self, offer_id: UUID, data: ScopeCategoryReplace
    ) -> OfferRead:
        offer = await self._offer(offer_id)
        self._ensure_mutable(offer.status)
        categories = [
            await self._category_for_outlet(offer.outlet_id, item) for item in data.category_ids
        ]
        await self.session.execute(
            delete(OfferCategoryScope).where(OfferCategoryScope.offer_id == offer_id)
        )
        self.session.add_all(
            [
                OfferCategoryScope(offer_id=offer_id, category_id=category.id)
                for category in categories
            ]
        )
        offer.scope_type = OfferScopeType.SELECTED_CATEGORIES
        await self.session.commit()
        await self.session.refresh(offer)
        return await self.get_offer(offer_id)

    async def replace_combo_items(self, offer_id: UUID, data: ComboItemsReplace) -> OfferRead:
        offer = await self._offer(offer_id)
        self._ensure_mutable(offer.status)
        if len(data.items) < 2:
            raise MerchandisingConflict(
                "combo requires at least two items", code="offer_combo_invalid"
            )
        rows: list[OfferComboItem] = []
        for item in data.items:
            dish = await self._promotion_dish(offer.outlet_id, item.dish_id)
            await self._validate_variant(dish, item.variant_id)
            rows.append(
                OfferComboItem(
                    offer_id=offer_id,
                    dish_id=item.dish_id,
                    variant_id=item.variant_id,
                    required_quantity=item.required_quantity,
                )
            )
        await self.session.execute(
            delete(OfferComboItem).where(OfferComboItem.offer_id == offer_id)
        )
        self.session.add_all(rows)
        await self.session.commit()
        await self.session.refresh(offer)
        return await self.get_offer(offer_id)

    async def activate_offer(self, offer_id: UUID, *, confirm: bool) -> OfferRead:
        if not confirm:
            raise MerchandisingConflict(
                "confirmation required", code="promotion_confirmation_required"
            )
        offer = await self._offer(offer_id)
        await self._validate_offer_activation(offer)
        offer.status = MerchandisingStatus.ACTIVE
        offer.activation_confirmed = True
        offer.activated_at = self.now()
        await self.session.commit()
        await self.session.refresh(offer)
        return await self.get_offer(offer.id)

    async def pause_offer(self, offer_id: UUID, *, confirm: bool) -> OfferRead:
        if not confirm:
            raise MerchandisingConflict(
                "confirmation required", code="promotion_confirmation_required"
            )
        offer = await self._offer(offer_id)
        offer.status = MerchandisingStatus.PAUSED
        offer.paused_at = self.now()
        await self.session.commit()
        await self.session.refresh(offer)
        return await self.get_offer(offer.id)

    async def deactivate_offer(self, offer_id: UUID, *, confirm: bool) -> OfferRead:
        if not confirm:
            raise MerchandisingConflict(
                "confirmation required", code="promotion_confirmation_required"
            )
        offer = await self._offer(offer_id)
        offer.status = MerchandisingStatus.DEACTIVATED
        offer.deactivated_at = self.now()
        await self.session.commit()
        await self.session.refresh(offer)
        return await self.get_offer(offer.id)

    async def preview_offer(self, offer_id: UUID, data: OfferPreviewRequest) -> OfferPreviewRead:
        offer = await self._offer(offer_id)
        priced = [await self._price_preview_item(offer.outlet_id, item) for item in data.items]
        regular_subtotal = money(sum((item.line_subtotal for item in priced), Decimal("0")))
        scope_dish_ids = set(await self._offer_dish_scope_ids(offer.id))
        scope_category_ids = set(await self._offer_category_scope_ids(offer.id))
        lines: list[PreviewLineRead] = []
        eligible_subtotal = Decimal("0")
        for item in priced:
            eligible = self._line_eligible(offer, item.dish, scope_dish_ids, scope_category_ids)
            if eligible:
                eligible_subtotal += item.line_subtotal
            lines.append(
                PreviewLineRead(
                    dish_id=item.dish.id,
                    variant_id=item.variant_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    line_subtotal=item.line_subtotal,
                    eligible=eligible,
                    available=item.available,
                )
            )
        eligible_subtotal = money(eligible_subtotal)
        combo_count = 0
        discount = Decimal("0")
        if offer.offer_type == OfferType.COMBO_FIXED_PRICE:
            combo_count, discount = await self._combo_discount(offer, priced)
            eligible = combo_count > 0
            threshold = None
            amount_to_threshold = Decimal("0")
        else:
            threshold = offer.minimum_subtotal or Decimal("0")
            eligible = eligible_subtotal >= threshold
            amount_to_threshold = money(max(threshold - eligible_subtotal, Decimal("0")))
            if eligible:
                if offer.offer_type == OfferType.PERCENTAGE:
                    discount = money(
                        eligible_subtotal * (offer.discount_value or Decimal("0")) / Decimal("100")
                    )
                    if offer.maximum_discount is not None:
                        discount = min(discount, money(offer.maximum_discount))
                else:
                    discount = min(money(offer.discount_value or Decimal("0")), eligible_subtotal)
        discount = money(discount)
        return OfferPreviewRead(
            offer_id=offer.id,
            eligible=eligible,
            can_fulfill=all(item.available for item in priced),
            regular_subtotal=regular_subtotal,
            eligible_subtotal=eligible_subtotal,
            minimum_subtotal=offer.minimum_subtotal,
            amount_to_threshold=amount_to_threshold,
            discount_amount=discount,
            post_discount_subtotal=money(max(regular_subtotal - discount, Decimal("0"))),
            complete_combo_count=combo_count,
            line_items=lines,
        )

    async def _resolve_special_schedule(
        self, outlet: RestaurantOutlet, data: SpecialCreate, now: datetime
    ) -> tuple[datetime, datetime]:
        if data.duration_mode == SpecialDurationMode.UNTIL_TIMESTAMP:
            starts_at = _utc(data.starts_at) if data.starts_at else now
            ends_at = _utc(data.ends_at) if data.ends_at else now
            self._validate_schedule(starts_at, ends_at, "invalid_special_schedule")
            return starts_at, ends_at
        interval = self._service_interval(outlet, now)
        return interval.starts_at.astimezone(UTC), interval.closes_at.astimezone(UTC)

    def _service_interval(self, outlet: RestaurantOutlet, now: datetime) -> _LocalInterval:
        zone = ZoneInfo(outlet.timezone)
        local_now = now.astimezone(zone)
        intervals = sorted(
            outlet.operating_intervals,
            key=lambda item: (item.weekday, item.opens_at or time.min),
        )
        if _is_continuous_24_7(intervals):
            raise MerchandisingConflict(
                "continuous 24-hour schedule has no service end boundary",
                code="no_service_end_boundary",
            )
        candidates = _expand_intervals(intervals, local_now.date(), zone)
        current = next(
            (item for item in candidates if item.starts_at <= local_now < item.closes_at),
            None,
        )
        if current is not None:
            return _LocalInterval(starts_at=local_now, closes_at=current.closes_at)
        future = next((item for item in candidates if item.starts_at > local_now), None)
        if future is None:
            raise MerchandisingConflict("no service end boundary", code="no_service_end_boundary")
        return future

    async def _promotion_dish(self, outlet_id: UUID, dish_id: UUID) -> Dish:
        dish = await self._dish(dish_id)
        if dish.menu.outlet_id != outlet_id:
            raise MerchandisingConflict(
                "dish belongs to another outlet", code="promotion_wrong_outlet"
            )
        if dish.review_status not in (ReviewStatus.CONFIRMED, ReviewStatus.APPROVED):
            raise MerchandisingConflict(
                "dish is not confirmed", code="promotion_dish_not_confirmed"
            )
        if not dish.is_active:
            raise MerchandisingConflict("dish is inactive", code="promotion_dish_not_confirmed")
        if dish.menu.status.value != "published":
            raise MerchandisingConflict(
                "dish is not in a published menu", code="promotion_dish_not_published"
            )
        return dish

    async def _price_preview_item(self, outlet_id: UUID, item: PreviewItem) -> _PricedItem:
        dish = await self._promotion_dish(outlet_id, item.dish_id)
        await self._validate_variant(dish, item.variant_id)
        if dish.variants and item.variant_id is None:
            raise MerchandisingConflict("variant is required", code="offer_combo_invalid")
        price = await self._effective_unit_price(dish, item.variant_id)
        available = (
            await AvailabilityService(self.session, now=self._now).dish_availability(dish.id)
        ).available
        return _PricedItem(
            dish=dish,
            variant_id=item.variant_id,
            quantity=item.quantity,
            unit_price=price,
            line_subtotal=money(price * item.quantity),
            available=available,
        )

    async def _effective_unit_price(self, dish: Dish, variant_id: UUID | None) -> Decimal:
        now = self.now()
        query = select(TodaysSpecial).where(
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
        special = (
            await self.session.execute(query.order_by(TodaysSpecial.created_at.desc()))
        ).scalar_one_or_none()
        if special is not None and special.special_price is not None:
            return money(special.special_price)
        if variant_id is not None:
            variant = next(item for item in dish.variants if item.id == variant_id)
            return money(variant.price)
        if dish.base_price is None:
            raise MerchandisingConflict("dish has no base price", code="offer_combo_invalid")
        return money(dish.base_price)

    async def _combo_discount(self, offer: Offer, priced: list[_PricedItem]) -> tuple[int, Decimal]:
        rows = await self._combo_items(offer.id)
        if not rows:
            return 0, Decimal("0")
        counts: dict[tuple[UUID, UUID | None], int] = {}
        values: dict[tuple[UUID, UUID | None], Decimal] = {}
        for item in priced:
            key = (item.dish.id, item.variant_id)
            counts[key] = counts.get(key, 0) + item.quantity
            values[key] = item.unit_price
        complete: int | None = None
        regular_bundle = Decimal("0")
        for row in rows:
            key = (row.dish_id, row.variant_id)
            available = counts.get(key, 0) // row.required_quantity
            complete = available if complete is None else min(complete, available)
            if key not in values:
                dish = await self._dish(row.dish_id)
                values[key] = await self._effective_unit_price(dish, row.variant_id)
            regular_bundle += values[key] * row.required_quantity
        count = complete or 0
        combo_price = money(offer.combo_price or Decimal("0"))
        if regular_bundle < combo_price:
            raise MerchandisingConflict(
                "combo price exceeds bundle value", code="offer_combo_invalid"
            )
        return count, money((regular_bundle - combo_price) * count)

    async def _validate_offer_activation(self, offer: Offer) -> None:
        self._validate_schedule(offer.starts_at, offer.ends_at, "offer_schedule_invalid")
        if offer.offer_type == OfferType.PERCENTAGE:
            if offer.discount_value is None or not (
                Decimal("0") < offer.discount_value <= Decimal("100")
            ):
                raise MerchandisingConflict("invalid percentage", code="offer_invalid_percentage")
        if offer.offer_type == OfferType.FLAT:
            if offer.discount_value is None or offer.discount_value <= 0:
                raise MerchandisingConflict(
                    "invalid flat discount", code="offer_invalid_flat_discount"
                )
        if (
            offer.scope_type == OfferScopeType.SELECTED_DISHES
            and not await self._offer_dish_scope_ids(offer.id)
        ):
            raise MerchandisingConflict("offer scope is empty", code="offer_invalid_scope")
        if (
            offer.scope_type == OfferScopeType.SELECTED_CATEGORIES
            and not await self._offer_category_scope_ids(offer.id)
        ):
            raise MerchandisingConflict("offer scope is empty", code="offer_invalid_scope")
        if offer.offer_type == OfferType.COMBO_FIXED_PRICE:
            rows = await self._combo_items(offer.id)
            if len(rows) < 2:
                raise MerchandisingConflict("combo requires items", code="offer_combo_invalid")
            for row in rows:
                await self._promotion_dish(offer.outlet_id, row.dish_id)
            if offer.combo_price is None:
                raise MerchandisingConflict("combo price required", code="offer_combo_invalid")

    def _line_eligible(
        self,
        offer: Offer,
        dish: Dish,
        scope_dish_ids: set[UUID],
        scope_category_ids: set[UUID],
    ) -> bool:
        if offer.scope_type == OfferScopeType.ALL_ITEMS:
            return True
        if offer.scope_type == OfferScopeType.SELECTED_DISHES:
            return dish.id in scope_dish_ids
        return dish.category_id in scope_category_ids

    async def _special_read(self, item: TodaysSpecial) -> SpecialRead:
        now = self.now()
        available = (
            await AvailabilityService(self.session, now=self._now).dish_availability(item.dish_id)
        ).available
        return SpecialRead(
            id=item.id,
            outlet_id=item.outlet_id,
            dish_id=item.dish_id,
            variant_id=item.variant_id,
            special_price=money(item.special_price) if item.special_price is not None else None,
            starts_at=_utc(item.starts_at),
            ends_at=_utc(item.ends_at),
            status=item.status,
            activation_confirmed=item.activation_confirmed,
            display_note=item.display_note,
            effective_active=self._effective(item.status, item.starts_at, item.ends_at, now),
            dish_available=available,
            created_at=_utc(item.created_at),
            updated_at=_utc(item.updated_at),
            activated_at=_utc(item.activated_at) if item.activated_at else None,
            deactivated_at=_utc(item.deactivated_at) if item.deactivated_at else None,
        )

    async def _featured_read(self, item: FeaturedDish) -> FeaturedRead:
        now = self.now()
        available = (
            await AvailabilityService(self.session, now=self._now).dish_availability(item.dish_id)
        ).available
        return FeaturedRead(
            id=item.id,
            outlet_id=item.outlet_id,
            dish_id=item.dish_id,
            starts_at=_utc(item.starts_at),
            ends_at=_utc(item.ends_at) if item.ends_at else None,
            status=item.status,
            display_order=item.display_order,
            activation_confirmed=item.activation_confirmed,
            effective_active=self._effective(item.status, item.starts_at, item.ends_at, now),
            dish_available=available,
            created_at=_utc(item.created_at),
            updated_at=_utc(item.updated_at),
            activated_at=_utc(item.activated_at) if item.activated_at else None,
            deactivated_at=_utc(item.deactivated_at) if item.deactivated_at else None,
        )

    async def _offer_read(self, offer: Offer) -> OfferRead:
        now = self.now()
        return OfferRead(
            id=offer.id,
            outlet_id=offer.outlet_id,
            name=offer.name,
            description=offer.description,
            offer_type=offer.offer_type,
            scope_type=offer.scope_type,
            status=offer.status,
            starts_at=_utc(offer.starts_at),
            ends_at=_utc(offer.ends_at),
            minimum_subtotal=money(offer.minimum_subtotal)
            if offer.minimum_subtotal is not None
            else None,
            discount_value=money(offer.discount_value)
            if offer.discount_value is not None
            else None,
            maximum_discount=money(offer.maximum_discount)
            if offer.maximum_discount is not None
            else None,
            combo_price=money(offer.combo_price) if offer.combo_price is not None else None,
            activation_confirmed=offer.activation_confirmed,
            effective_active=self._effective(offer.status, offer.starts_at, offer.ends_at, now),
            dish_scope_ids=await self._offer_dish_scope_ids(offer.id),
            category_scope_ids=await self._offer_category_scope_ids(offer.id),
            combo_items=[
                ComboItemInput(
                    dish_id=item.dish_id,
                    variant_id=item.variant_id,
                    required_quantity=item.required_quantity,
                )
                for item in await self._combo_items(offer.id)
            ],
            created_at=_utc(offer.created_at),
            updated_at=_utc(offer.updated_at),
            activated_at=_utc(offer.activated_at) if offer.activated_at else None,
            paused_at=_utc(offer.paused_at) if offer.paused_at else None,
            deactivated_at=_utc(offer.deactivated_at) if offer.deactivated_at else None,
        )

    async def _outlet(self, outlet_id: UUID) -> RestaurantOutlet:
        result = await self.session.execute(
            select(RestaurantOutlet)
            .options(selectinload(RestaurantOutlet.operating_intervals))
            .where(RestaurantOutlet.id == outlet_id)
        )
        outlet = result.scalar_one_or_none()
        if outlet is None:
            raise MerchandisingNotFound("outlet not found")
        if not outlet.is_active:
            raise MerchandisingConflict("outlet is inactive", code="promotion_wrong_outlet")
        return outlet

    async def _dish(self, dish_id: UUID) -> Dish:
        result = await self.session.execute(
            select(Dish)
            .options(selectinload(Dish.menu), selectinload(Dish.variants))
            .where(Dish.id == dish_id)
        )
        dish = result.scalar_one_or_none()
        if dish is None:
            raise MerchandisingNotFound("dish not found")
        return dish

    async def _special(self, special_id: UUID) -> TodaysSpecial:
        item = await self.session.get(TodaysSpecial, special_id)
        if item is None:
            raise MerchandisingNotFound("special not found")
        return item

    async def _featured(self, featured_id: UUID) -> FeaturedDish:
        item = await self.session.get(FeaturedDish, featured_id)
        if item is None:
            raise MerchandisingNotFound("featured dish not found")
        return item

    async def _offer(self, offer_id: UUID) -> Offer:
        item = await self.session.get(Offer, offer_id)
        if item is None:
            raise MerchandisingNotFound("offer not found")
        return item

    async def _category_for_outlet(self, outlet_id: UUID, category_id: UUID) -> Category:
        result = await self.session.execute(
            select(Category)
            .join(Menu)
            .where(Category.id == category_id, Menu.outlet_id == outlet_id)
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise MerchandisingConflict(
                "category scope wrong outlet", code="offer_scope_wrong_outlet"
            )
        return item

    async def _validate_variant(self, dish: Dish, variant_id: UUID | None) -> None:
        if variant_id is None:
            return
        if not any(item.id == variant_id for item in dish.variants):
            raise MerchandisingConflict(
                "variant does not belong to dish", code="special_variant_wrong_dish"
            )

    async def _ensure_no_overlapping_special(self, item: TodaysSpecial) -> None:
        result = await self.session.execute(
            select(TodaysSpecial).where(
                TodaysSpecial.id != item.id,
                TodaysSpecial.outlet_id == item.outlet_id,
                TodaysSpecial.dish_id == item.dish_id,
                TodaysSpecial.variant_id.is_(None)
                if item.variant_id is None
                else TodaysSpecial.variant_id == item.variant_id,
                TodaysSpecial.status == MerchandisingStatus.ACTIVE,
                TodaysSpecial.starts_at < item.ends_at,
                TodaysSpecial.ends_at > item.starts_at,
            )
        )
        if result.scalar_one_or_none() is not None:
            raise MerchandisingConflict("overlapping special exists", code="overlapping_special")

    async def _offer_dish_scope_ids(self, offer_id: UUID) -> list[UUID]:
        result = await self.session.execute(
            select(OfferDishScope.dish_id).where(OfferDishScope.offer_id == offer_id)
        )
        return list(result.scalars())

    async def _offer_category_scope_ids(self, offer_id: UUID) -> list[UUID]:
        result = await self.session.execute(
            select(OfferCategoryScope.category_id).where(OfferCategoryScope.offer_id == offer_id)
        )
        return list(result.scalars())

    async def _combo_items(self, offer_id: UUID) -> list[OfferComboItem]:
        return list(
            (
                await self.session.execute(
                    select(OfferComboItem).where(OfferComboItem.offer_id == offer_id)
                )
            ).scalars()
        )

    def _effective(
        self,
        status: MerchandisingStatus,
        starts_at: datetime,
        ends_at: datetime | None,
        now: datetime,
    ) -> bool:
        return (
            status == MerchandisingStatus.ACTIVE
            and _utc(starts_at) <= now
            and (ends_at is None or _utc(ends_at) > now)
        )

    def _ensure_mutable(self, status: MerchandisingStatus) -> None:
        if status == MerchandisingStatus.ACTIVE:
            raise MerchandisingConflict(
                "active promotion cannot be edited", code="offer_active_immutable"
            )

    def _validate_schedule(self, starts_at: datetime, ends_at: datetime, code: str) -> None:
        if _utc(ends_at) <= _utc(starts_at):
            raise MerchandisingConflict("schedule end must be after start", code=code)


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_continuous_24_7(intervals: list[WeeklyOperatingInterval]) -> bool:
    return len({item.weekday for item in intervals if item.is_full_day}) == 7


def _expand_intervals(
    intervals: list[WeeklyOperatingInterval], local_date: date, zone: ZoneInfo
) -> list[_LocalInterval]:
    start_date = local_date - timedelta(days=1)
    expanded: list[_LocalInterval] = []
    for offset in range(10):
        day = start_date + timedelta(days=offset)
        for interval in intervals:
            if interval.weekday != day.weekday():
                continue
            if interval.is_full_day:
                starts_at = datetime.combine(day, time.min, tzinfo=zone)
                closes_at = starts_at + timedelta(days=1)
            else:
                assert interval.opens_at is not None
                assert interval.closes_at is not None
                starts_at = datetime.combine(day, interval.opens_at, tzinfo=zone)
                closes_at = datetime.combine(day, interval.closes_at, tzinfo=zone)
                if closes_at <= starts_at:
                    closes_at += timedelta(days=1)
            expanded.append(_LocalInterval(starts_at, closes_at))
    return sorted(expanded, key=lambda item: item.starts_at)
