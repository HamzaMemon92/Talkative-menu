from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ainza_restaurant.availability.models import (
    AvailabilityProposal,
    AvailabilityProposalAffectedDish,
    DishAvailabilityOverride,
    IngredientAvailabilityOverride,
)
from ainza_restaurant.availability.schemas import (
    AvailabilityAffectedDishRead,
    AvailabilityCauseRead,
    AvailabilityProposalCreate,
    AvailabilityProposalRead,
    AvailabilityTargetRead,
    DishAvailabilityRead,
    IngredientAvailabilityRead,
    OutletAvailabilityRead,
)
from ainza_restaurant.core.config import get_settings
from ainza_restaurant.domain.enums import (
    AvailabilityAction,
    AvailabilityDurationMode,
    AvailabilityProposalStatus,
    AvailabilityReasonCode,
    AvailabilityTargetType,
    ReviewStatus,
)
from ainza_restaurant.menu.models import Dish, DishIngredient, Ingredient, Menu
from ainza_restaurant.restaurants.models import RestaurantOutlet, WeeklyOperatingInterval


class AvailabilityNotFound(LookupError):
    code = "availability_proposal_not_found"


class AvailabilityConflict(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "availability_conflict",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class _Target:
    id: UUID
    name: str
    outlet_id: UUID | None
    target_type: AvailabilityTargetType


@dataclass(frozen=True)
class _LocalInterval:
    starts_at: datetime
    closes_at: datetime


class AvailabilityService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        now: Callable[[], datetime] | None = None,
        proposal_ttl_minutes: int | None = None,
    ) -> None:
        self.session = session
        self._now = now or (lambda: datetime.now(UTC))
        self.proposal_ttl_minutes = (
            proposal_ttl_minutes or get_settings().availability_proposal_ttl_minutes
        )

    def now(self) -> datetime:
        return _utc(self._now())

    async def create_proposal(
        self, outlet_id: UUID, data: AvailabilityProposalCreate
    ) -> AvailabilityProposalRead:
        now = self.now()
        outlet = await self._outlet(outlet_id)
        await self._target_for_outlet(outlet_id, data.target_type, data.target_id)
        computed_expires_at = await self._computed_expiry(outlet, data, now)
        affected = await self._affected_dishes(data.target_type, data.target_id, outlet_id)
        proposal = AvailabilityProposal(
            outlet_id=outlet_id,
            target_type=data.target_type,
            target_id=data.target_id,
            action=data.action,
            duration_mode=data.duration_mode,
            requested_until=_utc(data.requested_until) if data.requested_until else None,
            computed_expires_at=computed_expires_at,
            reason_code=data.reason_code,
            reason_note=data.reason_note,
            proposal_expires_at=now + timedelta(minutes=self.proposal_ttl_minutes),
        )
        proposal.affected_dishes = [
            AvailabilityProposalAffectedDish(dish_id=dish.dish_id) for dish in affected
        ]
        self.session.add(proposal)
        await self.session.commit()
        return await self.get_proposal(
            proposal.id,
            current_outlet_time=now.astimezone(ZoneInfo(outlet.timezone)),
        )

    async def get_proposal(
        self, proposal_id: UUID, *, current_outlet_time: datetime | None = None
    ) -> AvailabilityProposalRead:
        proposal = await self._proposal(proposal_id)
        outlet = await self._outlet(proposal.outlet_id)
        target = await self._target_for_outlet(
            proposal.outlet_id, proposal.target_type, proposal.target_id
        )
        dishes = await self._snapshot_dishes(proposal)
        return self._proposal_read(
            proposal,
            target,
            dishes,
            current_outlet_time=current_outlet_time
            or self.now().astimezone(ZoneInfo(outlet.timezone)),
        )

    async def confirm_proposal(
        self, proposal_id: UUID, *, confirm: bool
    ) -> AvailabilityProposalRead:
        if not confirm:
            raise AvailabilityConflict(
                "availability confirmation requires confirm=true",
                code="availability_confirmation_required",
            )
        now = self.now()
        proposal = await self._proposal(proposal_id)
        if proposal.status == AvailabilityProposalStatus.CONFIRMED:
            return await self.get_proposal(proposal.id)
        self._ensure_confirmable(proposal, now)
        outlet = await self._outlet(proposal.outlet_id)
        await self._target_for_outlet(proposal.outlet_id, proposal.target_type, proposal.target_id)
        await self._ensure_not_stale(proposal, outlet, now)
        reason = proposal.reason_code or AvailabilityReasonCode.OTHER
        if proposal.action == AvailabilityAction.MARK_UNAVAILABLE:
            if proposal.target_type == AvailabilityTargetType.DISH:
                self.session.add(
                    DishAvailabilityOverride(
                        dish_id=proposal.target_id,
                        starts_at=now,
                        expires_at=proposal.computed_expires_at,
                        reason_code=reason,
                        reason_note=proposal.reason_note,
                        source_proposal_id=proposal.id,
                    )
                )
            else:
                self.session.add(
                    IngredientAvailabilityOverride(
                        ingredient_id=proposal.target_id,
                        starts_at=now,
                        expires_at=proposal.computed_expires_at,
                        reason_code=reason,
                        reason_note=proposal.reason_note,
                        source_proposal_id=proposal.id,
                    )
                )
        else:
            if proposal.target_type == AvailabilityTargetType.DISH:
                await self.session.execute(
                    update(DishAvailabilityOverride)
                    .where(
                        DishAvailabilityOverride.dish_id == proposal.target_id,
                        DishAvailabilityOverride.revoked_at.is_(None),
                        (DishAvailabilityOverride.expires_at.is_(None))
                        | (DishAvailabilityOverride.expires_at > now),
                    )
                    .values(revoked_at=now)
                )
            else:
                await self.session.execute(
                    update(IngredientAvailabilityOverride)
                    .where(
                        IngredientAvailabilityOverride.ingredient_id == proposal.target_id,
                        IngredientAvailabilityOverride.revoked_at.is_(None),
                        (IngredientAvailabilityOverride.expires_at.is_(None))
                        | (IngredientAvailabilityOverride.expires_at > now),
                    )
                    .values(revoked_at=now)
                )
        proposal.status = AvailabilityProposalStatus.CONFIRMED
        proposal.confirmed_at = now
        await self.session.commit()
        return await self.get_proposal(proposal.id)

    async def cancel_proposal(self, proposal_id: UUID) -> AvailabilityProposalRead:
        now = self.now()
        proposal = await self._proposal(proposal_id)
        if proposal.status == AvailabilityProposalStatus.CONFIRMED:
            raise AvailabilityConflict(
                "confirmed proposal cannot be cancelled",
                code="availability_proposal_confirmed",
            )
        if proposal.status == AvailabilityProposalStatus.CANCELLED:
            return await self.get_proposal(proposal.id)
        proposal.status = AvailabilityProposalStatus.CANCELLED
        proposal.cancelled_at = now
        await self.session.commit()
        return await self.get_proposal(proposal.id)

    async def dish_availability(self, dish_id: UUID) -> DishAvailabilityRead:
        dish = await self._dish(dish_id)
        causes = await self._dish_blockers(dish, self.now())
        return DishAvailabilityRead(
            dish_id=dish.id,
            dish_name=dish.name,
            outlet_id=dish.menu.outlet_id,
            menu_id=dish.menu_id,
            category_id=dish.category_id,
            catalog_active=dish.is_active,
            available=not causes,
            blocking_causes=causes,
        )

    async def ingredient_availability(self, ingredient_id: UUID) -> IngredientAvailabilityRead:
        ingredient = await self._ingredient(ingredient_id)
        overrides = await self._active_ingredient_overrides(ingredient.id, self.now())
        return IngredientAvailabilityRead(
            ingredient_id=ingredient.id,
            ingredient_name=ingredient.name,
            outlet_id=ingredient.outlet_id,
            available=not overrides,
            active_overrides=[
                AvailabilityCauseRead(
                    type=AvailabilityTargetType.INGREDIENT,
                    override_id=item.id,
                    ingredient_id=ingredient.id,
                    ingredient_name=ingredient.name,
                    reason_code=item.reason_code,
                    reason_note=item.reason_note,
                    starts_at=_utc(item.starts_at),
                    expires_at=_utc(item.expires_at) if item.expires_at else None,
                    source_proposal_id=item.source_proposal_id,
                )
                for item in overrides
            ],
        )

    async def outlet_availability(
        self,
        outlet_id: UUID,
        *,
        available: bool | None = None,
        category_id: UUID | None = None,
    ) -> OutletAvailabilityRead:
        now = self.now()
        outlet = await self._outlet(outlet_id)
        query = (
            select(Dish)
            .join(Menu)
            .where(Menu.outlet_id == outlet_id)
            .options(selectinload(Dish.menu))
        )
        if category_id is not None:
            query = query.where(Dish.category_id == category_id)
        result = await self.session.execute(query.order_by(Dish.display_order, Dish.name))
        dish_reads = [await self.dish_availability(dish.id) for dish in result.scalars()]
        if available is not None:
            dish_reads = [item for item in dish_reads if item.available is available]
        return OutletAvailabilityRead(
            outlet_id=outlet_id,
            current_outlet_time=now.astimezone(ZoneInfo(outlet.timezone)),
            dishes=dish_reads,
        )

    async def _computed_expiry(
        self, outlet: RestaurantOutlet, data: AvailabilityProposalCreate, now: datetime
    ) -> datetime | None:
        if data.action == AvailabilityAction.RESTORE:
            return None
        if data.duration_mode == AvailabilityDurationMode.INDEFINITE:
            return None
        if data.duration_mode == AvailabilityDurationMode.UNTIL_TIMESTAMP:
            if data.requested_until is None:
                raise AvailabilityConflict(
                    "requested_until is required", code="invalid_availability_duration"
                )
            requested_until = _utc(data.requested_until)
            if requested_until <= now:
                raise AvailabilityConflict(
                    "requested_until must be in the future", code="invalid_expiry"
                )
            return requested_until
        if data.duration_mode == AvailabilityDurationMode.UNTIL_NEXT_OPENING:
            return await self._next_opening_utc(outlet, now)
        raise AvailabilityConflict("invalid duration mode", code="invalid_availability_duration")

    async def _next_opening_utc(self, outlet: RestaurantOutlet, now: datetime) -> datetime:
        zone = ZoneInfo(outlet.timezone)
        local_now = now.astimezone(zone)
        intervals = sorted(
            outlet.operating_intervals,
            key=lambda item: (item.weekday, item.opens_at or time.min),
        )
        if not intervals:
            raise AvailabilityConflict(
                "outlet has no operating hours", code="no_next_opening_boundary"
            )
        if _is_continuous_24_7(intervals):
            raise AvailabilityConflict(
                "continuous 24-hour schedule has no next opening boundary",
                code="no_next_opening_boundary",
            )
        candidates = _expand_intervals(intervals, local_now.date(), zone)
        current = next(
            (item for item in candidates if item.starts_at <= local_now < item.closes_at),
            None,
        )
        threshold = current.closes_at if current else local_now
        starts = [item.starts_at for item in candidates if item.starts_at > threshold]
        if not starts:
            raise AvailabilityConflict(
                "no next opening boundary found", code="no_next_opening_boundary"
            )
        return starts[0].astimezone(UTC)

    async def _outlet(self, outlet_id: UUID) -> RestaurantOutlet:
        result = await self.session.execute(
            select(RestaurantOutlet)
            .options(selectinload(RestaurantOutlet.operating_intervals))
            .where(RestaurantOutlet.id == outlet_id)
        )
        outlet = result.scalar_one_or_none()
        if outlet is None:
            raise AvailabilityNotFound("outlet not found")
        return outlet

    async def _dish(self, dish_id: UUID) -> Dish:
        result = await self.session.execute(
            select(Dish)
            .options(
                selectinload(Dish.menu),
                selectinload(Dish.ingredients).selectinload(DishIngredient.ingredient),
            )
            .where(Dish.id == dish_id)
        )
        dish = result.scalar_one_or_none()
        if dish is None:
            raise AvailabilityNotFound("dish not found")
        return dish

    async def _ingredient(self, ingredient_id: UUID) -> Ingredient:
        item = await self.session.get(Ingredient, ingredient_id)
        if item is None:
            raise AvailabilityNotFound("ingredient not found")
        return item

    async def _target_for_outlet(
        self, outlet_id: UUID, target_type: AvailabilityTargetType, target_id: UUID
    ) -> _Target:
        if target_type == AvailabilityTargetType.DISH:
            dish = await self._dish(target_id)
            if dish.menu.outlet_id != outlet_id:
                raise AvailabilityConflict(
                    "dish does not belong to proposal outlet",
                    code="availability_target_wrong_outlet",
                )
            return _Target(dish.id, dish.name, dish.menu.outlet_id, target_type)
        ingredient = await self._ingredient(target_id)
        if ingredient.outlet_id != outlet_id:
            raise AvailabilityConflict(
                "ingredient does not belong to proposal outlet",
                code="availability_target_wrong_outlet",
            )
        return _Target(ingredient.id, ingredient.name, ingredient.outlet_id, target_type)

    async def _proposal(self, proposal_id: UUID) -> AvailabilityProposal:
        result = await self.session.execute(
            select(AvailabilityProposal)
            .options(selectinload(AvailabilityProposal.affected_dishes))
            .where(AvailabilityProposal.id == proposal_id)
        )
        proposal = result.scalar_one_or_none()
        if proposal is None:
            raise AvailabilityNotFound("availability proposal not found")
        return proposal

    def _ensure_confirmable(self, proposal: AvailabilityProposal, now: datetime) -> None:
        if proposal.status == AvailabilityProposalStatus.CANCELLED:
            raise AvailabilityConflict(
                "proposal is cancelled", code="availability_proposal_cancelled"
            )
        if proposal.status == AvailabilityProposalStatus.EXPIRED:
            raise AvailabilityConflict("proposal is expired", code="availability_proposal_expired")
        if proposal.status != AvailabilityProposalStatus.PENDING:
            raise AvailabilityConflict("proposal cannot be confirmed", code="availability_conflict")
        if _utc(proposal.proposal_expires_at) <= now:
            proposal.status = AvailabilityProposalStatus.EXPIRED
            raise AvailabilityConflict("proposal is expired", code="availability_proposal_expired")

    async def _ensure_not_stale(
        self, proposal: AvailabilityProposal, outlet: RestaurantOutlet, now: datetime
    ) -> None:
        current = await self._affected_dishes(
            proposal.target_type, proposal.target_id, proposal.outlet_id
        )
        snapshot_ids = {item.dish_id for item in proposal.affected_dishes}
        current_ids = {item.dish_id for item in current}
        if snapshot_ids != current_ids:
            raise AvailabilityConflict(
                "proposal affected dishes changed",
                code="availability_proposal_stale",
                details={
                    "snapshot_dish_ids": sorted(str(item) for item in snapshot_ids),
                    "current_dish_ids": sorted(str(item) for item in current_ids),
                },
            )
        if proposal.duration_mode == AvailabilityDurationMode.UNTIL_NEXT_OPENING:
            current_expiry = await self._next_opening_utc(outlet, now)
            if proposal.computed_expires_at is None or current_expiry != _utc(
                proposal.computed_expires_at
            ):
                raise AvailabilityConflict(
                    "proposal expiry changed",
                    code="availability_proposal_stale",
                    details={
                        "snapshot_expires_at": proposal.computed_expires_at.isoformat()
                        if proposal.computed_expires_at
                        else None,
                        "current_expires_at": current_expiry.isoformat(),
                    },
                )

    async def _affected_dishes(
        self, target_type: AvailabilityTargetType, target_id: UUID, outlet_id: UUID
    ) -> list[AvailabilityAffectedDishRead]:
        if target_type == AvailabilityTargetType.DISH:
            dish = await self._dish(target_id)
            return [
                AvailabilityAffectedDishRead(
                    dish_id=dish.id,
                    name=dish.name,
                    category_id=dish.category_id,
                    catalog_active=dish.is_active,
                )
            ]
        result = await self.session.execute(
            select(Dish)
            .join(DishIngredient)
            .join(Menu)
            .where(
                DishIngredient.ingredient_id == target_id,
                DishIngredient.is_required_for_availability.is_(True),
                Menu.outlet_id == outlet_id,
                Dish.review_status.in_([ReviewStatus.CONFIRMED, ReviewStatus.APPROVED]),
            )
            .order_by(Dish.display_order, Dish.name)
        )
        return [
            AvailabilityAffectedDishRead(
                dish_id=dish.id,
                name=dish.name,
                category_id=dish.category_id,
                catalog_active=dish.is_active,
            )
            for dish in result.scalars()
        ]

    async def _snapshot_dishes(
        self, proposal: AvailabilityProposal
    ) -> list[AvailabilityAffectedDishRead]:
        ids = [item.dish_id for item in proposal.affected_dishes]
        if not ids:
            return []
        result = await self.session.execute(select(Dish).where(Dish.id.in_(ids)))
        dishes = {dish.id: dish for dish in result.scalars()}
        return [
            AvailabilityAffectedDishRead(
                dish_id=dish_id,
                name=dishes[dish_id].name,
                category_id=dishes[dish_id].category_id,
                catalog_active=dishes[dish_id].is_active,
            )
            for dish_id in ids
            if dish_id in dishes
        ]

    async def _dish_blockers(self, dish: Dish, now: datetime) -> list[AvailabilityCauseRead]:
        direct = await self._active_dish_overrides(dish.id, now)
        causes = [
            AvailabilityCauseRead(
                type=AvailabilityTargetType.DISH,
                override_id=item.id,
                dish_id=dish.id,
                dish_name=dish.name,
                reason_code=item.reason_code,
                reason_note=item.reason_note,
                starts_at=_utc(item.starts_at),
                expires_at=_utc(item.expires_at) if item.expires_at else None,
                source_proposal_id=item.source_proposal_id,
            )
            for item in direct
        ]
        if dish.review_status not in (ReviewStatus.CONFIRMED, ReviewStatus.APPROVED):
            return causes
        required_ingredient_ids = [
            link.ingredient_id for link in dish.ingredients if link.is_required_for_availability
        ]
        if not required_ingredient_ids:
            return causes
        result = await self.session.execute(
            select(IngredientAvailabilityOverride, Ingredient)
            .join(Ingredient, Ingredient.id == IngredientAvailabilityOverride.ingredient_id)
            .where(
                IngredientAvailabilityOverride.ingredient_id.in_(required_ingredient_ids),
                IngredientAvailabilityOverride.revoked_at.is_(None),
                (IngredientAvailabilityOverride.expires_at.is_(None))
                | (IngredientAvailabilityOverride.expires_at > now),
            )
            .order_by(Ingredient.name)
        )
        for override, ingredient in result.all():
            causes.append(
                AvailabilityCauseRead(
                    type=AvailabilityTargetType.INGREDIENT,
                    override_id=override.id,
                    ingredient_id=ingredient.id,
                    ingredient_name=ingredient.name,
                    reason_code=override.reason_code,
                    reason_note=override.reason_note,
                    starts_at=_utc(override.starts_at),
                    expires_at=_utc(override.expires_at) if override.expires_at else None,
                    source_proposal_id=override.source_proposal_id,
                )
            )
        return causes

    async def _active_dish_overrides(
        self, dish_id: UUID, now: datetime
    ) -> list[DishAvailabilityOverride]:
        result = await self.session.execute(
            select(DishAvailabilityOverride).where(
                DishAvailabilityOverride.dish_id == dish_id,
                DishAvailabilityOverride.revoked_at.is_(None),
                (DishAvailabilityOverride.expires_at.is_(None))
                | (DishAvailabilityOverride.expires_at > now),
            )
        )
        return list(result.scalars())

    async def _active_ingredient_overrides(
        self, ingredient_id: UUID, now: datetime
    ) -> list[IngredientAvailabilityOverride]:
        result = await self.session.execute(
            select(IngredientAvailabilityOverride).where(
                IngredientAvailabilityOverride.ingredient_id == ingredient_id,
                IngredientAvailabilityOverride.revoked_at.is_(None),
                (IngredientAvailabilityOverride.expires_at.is_(None))
                | (IngredientAvailabilityOverride.expires_at > now),
            )
        )
        return list(result.scalars())

    def _proposal_read(
        self,
        proposal: AvailabilityProposal,
        target: _Target,
        affected: list[AvailabilityAffectedDishRead],
        *,
        current_outlet_time: datetime | None,
    ) -> AvailabilityProposalRead:
        return AvailabilityProposalRead(
            id=proposal.id,
            outlet_id=proposal.outlet_id,
            target=AvailabilityTargetRead(type=target.target_type, id=target.id, name=target.name),
            action=proposal.action,
            duration_mode=proposal.duration_mode,
            requested_until=_utc(proposal.requested_until) if proposal.requested_until else None,
            computed_expires_at=(
                _utc(proposal.computed_expires_at) if proposal.computed_expires_at else None
            ),
            reason_code=proposal.reason_code,
            reason_note=proposal.reason_note,
            status=proposal.status,
            proposal_expires_at=_utc(proposal.proposal_expires_at),
            current_outlet_time=current_outlet_time,
            affected_dishes=affected,
            confirmed_at=_utc(proposal.confirmed_at) if proposal.confirmed_at else None,
            cancelled_at=_utc(proposal.cancelled_at) if proposal.cancelled_at else None,
            created_at=_utc(proposal.created_at),
            updated_at=_utc(proposal.updated_at),
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_continuous_24_7(intervals: list[WeeklyOperatingInterval]) -> bool:
    full_days = {item.weekday for item in intervals if item.is_full_day}
    return len(full_days) == 7


def _expand_intervals(
    intervals: list[WeeklyOperatingInterval], local_date: date, zone: ZoneInfo
) -> list[_LocalInterval]:
    start_date = local_date - timedelta(days=1)
    expanded: list[_LocalInterval] = []
    for offset in range(10):
        day = start_date + timedelta(days=offset)
        weekday = day.weekday()
        for interval in intervals:
            if interval.weekday != weekday:
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
            expanded.append(_LocalInterval(starts_at=starts_at, closes_at=closes_at))
    return sorted(expanded, key=lambda item: item.starts_at)
