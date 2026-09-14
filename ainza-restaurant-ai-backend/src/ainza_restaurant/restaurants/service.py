from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ainza_restaurant.domain.enums import (
    HalalPolicy,
    HalalStatus,
    OnboardingStatus,
    RestaurantType,
)
from ainza_restaurant.restaurants.domain import (
    IntervalForValidation,
    OperatingHoursError,
    validate_gstin,
    validate_weekly_intervals,
)
from ainza_restaurant.restaurants.models import (
    OutletFoodPolicy,
    OutletTaxProfile,
    Restaurant,
    RestaurantOutlet,
    WeeklyOperatingInterval,
)
from ainza_restaurant.restaurants.schemas import (
    FinalizeRequest,
    FoodPolicyUpsert,
    MissingRequirement,
    OnboardingReadiness,
    OperatingHoursReplace,
    OutletCreate,
    OutletPatch,
    ReadinessCheck,
    RestaurantCreate,
    RestaurantPatch,
    TaxProfileUpsert,
)


class OnboardingNotFound(LookupError):
    code = "not_found"


class OnboardingConflict(ValueError):
    def __init__(
        self, message: str, *, code: str = "conflict", details: dict[str, object] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class RestaurantOnboardingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_restaurant(self, data: RestaurantCreate) -> Restaurant:
        try:
            slug = data.slug or self._slug_from_name(data.name)
        except ValueError as exc:
            raise OnboardingConflict(
                "restaurant name cannot be normalized to a slug", code="invalid_slug"
            ) from exc
        restaurant = Restaurant(
            name=data.name,
            slug=slug,
            legal_name=data.legal_name,
            status=data.status,
        )
        self.session.add(restaurant)
        try:
            await self.session.commit()
            await self.session.refresh(restaurant)
        except IntegrityError as exc:
            await self.session.rollback()
            raise OnboardingConflict(
                "restaurant slug is already in use",
                code="restaurant_slug_conflict",
                details={"slug": slug},
            ) from exc
        return restaurant

    async def get_restaurant(self, restaurant_id: UUID) -> Restaurant:
        result = await self.session.execute(
            select(Restaurant)
            .options(
                selectinload(Restaurant.outlets).selectinload(RestaurantOutlet.operating_intervals),
                selectinload(Restaurant.outlets).selectinload(RestaurantOutlet.tax_profile),
                selectinload(Restaurant.outlets).selectinload(RestaurantOutlet.food_policy),
            )
            .where(Restaurant.id == restaurant_id)
        )
        restaurant = result.scalar_one_or_none()
        if restaurant is None:
            raise OnboardingNotFound("restaurant not found")
        return restaurant

    async def list_restaurants(self) -> list[Restaurant]:
        result = await self.session.execute(
            select(Restaurant).order_by(Restaurant.name, Restaurant.id)
        )
        return list(result.scalars().all())

    async def update_restaurant(self, restaurant_id: UUID, data: RestaurantPatch) -> Restaurant:
        restaurant = await self.get_restaurant(restaurant_id)
        self._ensure_editable(restaurant)
        values = data.model_dump(exclude_unset=True)
        if values.get("slug", restaurant.slug) is None:
            raise OnboardingConflict("slug cannot be null", code="invalid_slug")
        if "slug" not in values and "name" in values:
            try:
                values["slug"] = self._slug_from_name(values["name"])
            except ValueError as exc:
                raise OnboardingConflict(
                    "restaurant name cannot be normalized to a slug", code="invalid_slug"
                ) from exc
        for key, value in values.items():
            setattr(restaurant, key, value)
        try:
            await self.session.commit()
            await self.session.refresh(restaurant)
        except IntegrityError as exc:
            await self.session.rollback()
            raise OnboardingConflict(
                "restaurant slug is already in use",
                code="restaurant_slug_conflict",
                details={"slug": values.get("slug", restaurant.slug)},
            ) from exc
        return restaurant

    async def create_outlet(self, restaurant_id: UUID, data: OutletCreate) -> RestaurantOutlet:
        restaurant = await self.get_restaurant(restaurant_id)
        self._ensure_editable(restaurant)
        existing = len(restaurant.outlets)
        requested_primary = data.is_primary
        make_primary = requested_primary if requested_primary is not None else existing == 0
        if (
            existing
            and requested_primary is False
            and not any(outlet.is_primary for outlet in restaurant.outlets)
        ):
            make_primary = True
        if make_primary:
            await self._clear_primary(restaurant_id)
        values = data.model_dump(exclude={"is_primary"})
        outlet = RestaurantOutlet(restaurant_id=restaurant.id, is_primary=make_primary, **values)
        self.session.add(outlet)
        try:
            await self.session.commit()
            await self.session.refresh(outlet)
        except IntegrityError as exc:
            await self.session.rollback()
            raise OnboardingConflict(
                "restaurant must have at most one primary outlet",
                code="primary_outlet_conflict",
            ) from exc
        return outlet

    async def get_outlet(self, restaurant_id: UUID, outlet_id: UUID) -> RestaurantOutlet:
        result = await self.session.execute(
            select(RestaurantOutlet)
            .options(
                selectinload(RestaurantOutlet.restaurant),
                selectinload(RestaurantOutlet.operating_intervals),
                selectinload(RestaurantOutlet.tax_profile),
                selectinload(RestaurantOutlet.food_policy),
            )
            .where(
                RestaurantOutlet.id == outlet_id,
                RestaurantOutlet.restaurant_id == restaurant_id,
            )
        )
        outlet = result.scalar_one_or_none()
        if outlet is None:
            raise OnboardingNotFound("outlet not found")
        return outlet

    async def get_outlet_by_id(self, outlet_id: UUID) -> RestaurantOutlet:
        result = await self.session.execute(
            select(RestaurantOutlet)
            .options(
                selectinload(RestaurantOutlet.restaurant),
                selectinload(RestaurantOutlet.food_policy),
            )
            .where(RestaurantOutlet.id == outlet_id)
        )
        outlet = result.scalar_one_or_none()
        if outlet is None:
            raise OnboardingNotFound("outlet not found")
        return outlet

    async def list_outlets(self, restaurant_id: UUID) -> list[RestaurantOutlet]:
        await self.get_restaurant(restaurant_id)
        result = await self.session.execute(
            select(RestaurantOutlet)
            .where(RestaurantOutlet.restaurant_id == restaurant_id)
            .order_by(
                RestaurantOutlet.is_primary.desc(), RestaurantOutlet.name, RestaurantOutlet.id
            )
        )
        return list(result.scalars().all())

    async def update_outlet(
        self, restaurant_id: UUID, outlet_id: UUID, data: OutletPatch
    ) -> RestaurantOutlet:
        outlet = await self.get_outlet(restaurant_id, outlet_id)
        self._ensure_editable(outlet.restaurant)
        values = data.model_dump(exclude_unset=True)
        requested_primary = values.pop("is_primary", None)
        if requested_primary is True:
            await self._clear_primary(restaurant_id)
            outlet.is_primary = True
        elif requested_primary is False and outlet.is_primary:
            raise OnboardingConflict(
                "the primary outlet cannot be unset without selecting another primary outlet",
                code="primary_outlet_required",
            )
        for key, value in values.items():
            setattr(outlet, key, value)
        try:
            await self.session.commit()
            await self.session.refresh(outlet)
        except IntegrityError as exc:
            await self.session.rollback()
            raise OnboardingConflict(
                "restaurant must have at most one primary outlet",
                code="primary_outlet_conflict",
            ) from exc
        return outlet

    async def replace_hours(
        self, restaurant_id: UUID, outlet_id: UUID, data: OperatingHoursReplace
    ) -> list[WeeklyOperatingInterval]:
        outlet = await self.get_outlet(restaurant_id, outlet_id)
        self._ensure_editable(outlet.restaurant)
        values = [
            IntervalForValidation(
                weekday=item.weekday,
                opens_at=item.opens_at,
                closes_at=item.closes_at,
                is_full_day=item.is_full_day,
            )
            for item in data.intervals
        ]
        try:
            validate_weekly_intervals(values)
        except OperatingHoursError as exc:
            raise OnboardingConflict(str(exc), code="operating_hours_overlap") from exc

        # Full-day is explicit in the API. Matching times are accepted for
        # compatibility but stored canonically as NULL times.
        intervals = [
            WeeklyOperatingInterval(
                outlet_id=outlet_id,
                weekday=item.weekday,
                opens_at=None if item.is_full_day else item.opens_at,
                closes_at=None if item.is_full_day else item.closes_at,
                is_full_day=item.is_full_day,
            )
            for item in data.intervals
        ]
        try:
            await self.session.execute(
                delete(WeeklyOperatingInterval).where(
                    WeeklyOperatingInterval.outlet_id == outlet_id
                )
            )
            self.session.add_all(intervals)
            await self.session.flush()
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise OnboardingConflict(
                "operating hours are invalid", code="invalid_schedule"
            ) from exc
        return intervals

    async def get_hours(
        self, restaurant_id: UUID, outlet_id: UUID
    ) -> list[WeeklyOperatingInterval]:
        outlet = await self.get_outlet(restaurant_id, outlet_id)
        return sorted(outlet.operating_intervals, key=lambda item: (item.weekday, str(item.id)))

    async def upsert_tax_profile(
        self,
        restaurant_id: UUID,
        outlet_id: UUID,
        data: TaxProfileUpsert,
        *,
        legacy_compat: bool = False,
    ) -> OutletTaxProfile:
        outlet = await self.get_outlet(restaurant_id, outlet_id)
        self._ensure_editable(outlet.restaurant)
        legacy = legacy_compat or (
            data.legal_business_name is None
            and data.restaurant_type is None
            and data.configured_tax_rate_percent is None
            and data.prices_include_tax is None
            and not data.tax_configuration_confirmed
        )
        gstin = validate_gstin(data.gstin)
        if legacy:
            gst_registered = gstin is not None
            legal_business_name: str | None = outlet.restaurant.legal_name or outlet.restaurant.name
            restaurant_type: RestaurantType | None = RestaurantType.OTHER
            gst_state_code: str | None = gstin[:2] if gstin else None
            prices_include_tax: bool | None = False
            tax_confirmed: bool = data.no_auto_tax_rates_confirmed
        else:
            gst_registered = bool(data.gst_registered)
            legal_business_name = data.legal_business_name
            restaurant_type = data.restaurant_type
            gst_state_code = data.gst_state_code
            prices_include_tax = data.prices_include_tax
            tax_confirmed = data.tax_configuration_confirmed

        profile = outlet.tax_profile
        if profile is None:
            profile = OutletTaxProfile(outlet_id=outlet.id)
            self.session.add(profile)
        profile.legal_business_name = legal_business_name
        profile.restaurant_type = restaurant_type
        profile.gst_registered = gst_registered
        profile.gst_state_code = gst_state_code
        profile.gstin = gstin
        profile.gstin_confirmed = data.gstin_confirmed or legacy and gstin is None
        profile.configured_tax_rate_percent = data.configured_tax_rate_percent
        profile.prices_include_tax = prices_include_tax
        profile.tax_configuration_confirmed = tax_confirmed
        profile.no_auto_tax_rates_confirmed = (
            data.no_auto_tax_rates_confirmed or data.confirm_no_auto_tax_rates is True
        )
        profile.tax_rates_confirmed = data.tax_rates_confirmed
        await self.session.commit()
        await self.session.refresh(profile)
        return profile

    async def get_tax_profile(
        self, restaurant_id: UUID, outlet_id: UUID
    ) -> OutletTaxProfile | None:
        outlet = await self.get_outlet(restaurant_id, outlet_id)
        return outlet.tax_profile

    async def upsert_food_policy(
        self,
        restaurant_id: UUID,
        outlet_id: UUID,
        data: FoodPolicyUpsert,
    ) -> OutletFoodPolicy:
        outlet = await self.get_outlet(restaurant_id, outlet_id)
        self._ensure_editable(outlet.restaurant)
        policy = outlet.food_policy
        if policy is None:
            policy = OutletFoodPolicy(outlet_id=outlet.id)
            self.session.add(policy)
        policy.halal_policy = data.halal_policy
        policy.halal_status = data.halal_status or (
            HalalStatus.HALAL
            if data.halal_policy == HalalPolicy.ALL_NONVEG_MEAT_RESTAURANT_DECLARED_HALAL
            else (
                HalalStatus.NOT_HALAL
                if data.halal_policy == HalalPolicy.RESTAURANT_DECLARED_NOT_HALAL
                else (
                    HalalStatus.PARTIAL
                    if data.halal_policy == HalalPolicy.SELECTED_ITEMS_ONLY
                    else HalalStatus.UNKNOWN
                )
            )
        )
        policy.halal_certification_status = data.halal_certification_status
        policy.halal_certificate_reference = data.halal_certificate_reference
        policy.pork_policy = data.pork_served_status
        policy.alcohol_policy = data.alcohol_served_status
        policy.notes = data.notes
        policy.information_confirmed = data.information_confirmed
        policy.confirmation = data.information_confirmed
        policy.confirmed_at = datetime.now(UTC) if data.information_confirmed else None
        await self.session.commit()
        await self.session.refresh(policy)
        return policy

    async def get_food_policy(
        self, restaurant_id: UUID, outlet_id: UUID
    ) -> OutletFoodPolicy | None:
        outlet = await self.get_outlet(restaurant_id, outlet_id)
        return outlet.food_policy

    async def readiness(self, restaurant_id: UUID) -> OnboardingReadiness:
        restaurant = await self.get_restaurant(restaurant_id)
        checks: list[ReadinessCheck] = []
        missing: list[MissingRequirement] = []

        self._add_check(
            checks,
            missing,
            code="restaurant_name",
            passed=bool(restaurant.name.strip()),
            message="restaurant name is required",
        )
        self._add_check(
            checks,
            missing,
            code="restaurant_slug",
            passed=bool(restaurant.slug.strip()),
            message="restaurant slug is required",
        )
        self._add_check(
            checks,
            missing,
            code="at_least_one_outlet",
            passed=bool(restaurant.outlets),
            message="at least one outlet is required",
        )
        primary_count = sum(outlet.is_primary for outlet in restaurant.outlets)
        self._add_check(
            checks,
            missing,
            code="exactly_one_primary_outlet",
            passed=primary_count == 1,
            message="exactly one primary outlet is required",
            details={"primary_count": primary_count},
        )

        for outlet in sorted(restaurant.outlets, key=lambda item: str(item.id)):
            self._add_check(
                checks,
                missing,
                code="operating_hours",
                passed=bool(outlet.operating_intervals),
                message=f"outlet {outlet.name} needs operating hours",
                outlet_id=outlet.id,
            )
            self._check_tax_profile(checks, missing, outlet)

        ready = not missing
        status = restaurant.onboarding_status
        reasons = [item.message for item in missing]
        return OnboardingReadiness(
            restaurant_id=restaurant.id,
            status=status,
            ready=ready,
            is_ready=ready,
            finalized=restaurant.onboarding_status == OnboardingStatus.READY_FOR_MENU,
            checks=checks,
            missing_requirements=missing,
            blocking_reasons=reasons,
            reasons=reasons,
        )

    async def finalize(self, restaurant_id: UUID, data: FinalizeRequest) -> Restaurant:
        restaurant = await self.get_restaurant(restaurant_id)
        if not data.confirm:
            raise OnboardingConflict(
                "finalization requires confirm=true", code="confirmation_required"
            )
        if restaurant.onboarding_status == OnboardingStatus.READY_FOR_MENU:
            return restaurant
        readiness = await self.readiness(restaurant_id)
        if not readiness.ready:
            raise OnboardingConflict(
                "onboarding is not ready",
                code="onboarding_not_ready",
                details={
                    "missing_requirements": [
                        item.model_dump(mode="json") for item in readiness.missing_requirements
                    ]
                },
            )
        restaurant.onboarding_status = OnboardingStatus.READY_FOR_MENU
        restaurant.finalized_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(restaurant)
        return restaurant

    @staticmethod
    def _slug_from_name(name: str) -> str:
        from ainza_restaurant.restaurants.domain import normalize_slug

        return normalize_slug(name)

    def _ensure_editable(self, restaurant: Restaurant) -> None:
        if restaurant.onboarding_status == OnboardingStatus.READY_FOR_MENU:
            raise OnboardingConflict(
                "finalized onboarding cannot be changed", code="onboarding_finalized"
            )

    async def _clear_primary(self, restaurant_id: UUID) -> None:
        await self.session.execute(
            update(RestaurantOutlet)
            .where(RestaurantOutlet.restaurant_id == restaurant_id)
            .values(is_primary=False)
        )

    @staticmethod
    def _add_check(
        checks: list[ReadinessCheck],
        missing: list[MissingRequirement],
        *,
        code: str,
        passed: bool,
        message: str,
        outlet_id: UUID | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        detail_values = details or {}
        checks.append(
            ReadinessCheck(
                code=code,
                passed=passed,
                message=message if not passed else f"{code} is configured",
                outlet_id=outlet_id,
                details=detail_values,
            )
        )
        if not passed:
            missing.append(
                MissingRequirement(
                    code=code,
                    message=message,
                    outlet_id=outlet_id,
                    details=detail_values,
                )
            )

    def _check_tax_profile(
        self,
        checks: list[ReadinessCheck],
        missing: list[MissingRequirement],
        outlet: RestaurantOutlet,
    ) -> None:
        profile = outlet.tax_profile
        if profile is None:
            self._add_check(
                checks,
                missing,
                code="tax_profile",
                passed=False,
                message=f"outlet {outlet.name} needs a tax profile",
                outlet_id=outlet.id,
                details={"missing_fields": ["tax_profile"]},
            )
            return

        missing_fields: list[str] = []
        for field in ("legal_business_name", "restaurant_type", "configured_tax_rate_percent"):
            if field == "configured_tax_rate_percent" and profile.no_auto_tax_rates_confirmed:
                continue
            if getattr(profile, field) is None or (
                isinstance(getattr(profile, field), str) and not getattr(profile, field).strip()
            ):
                missing_fields.append(field)
        if profile.prices_include_tax is None:
            missing_fields.append("prices_include_tax")
        if not profile.tax_configuration_confirmed and not profile.no_auto_tax_rates_confirmed:
            missing_fields.append("tax_configuration_confirmed")
        if profile.gst_registered:
            if not profile.gstin:
                missing_fields.append("gstin")
            if not profile.gstin_confirmed:
                missing_fields.append("gstin_confirmed")
            if not profile.gst_state_code:
                missing_fields.append("gst_state_code")
        elif profile.gstin:
            missing_fields.append("gstin_must_be_empty")
        self._add_check(
            checks,
            missing,
            code="tax_profile",
            passed=not missing_fields,
            message=f"outlet {outlet.name} needs a complete, explicitly confirmed tax profile",
            outlet_id=outlet.id,
            details={"missing_fields": missing_fields},
        )
