# ruff: noqa: B008
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.db.session import get_db_session
from ainza_restaurant.restaurants.schemas import (
    FinalizationResponse,
    FinalizeRequest,
    FoodPolicyRead,
    FoodPolicyUpsert,
    LegacyTaxProfileUpsert,
    OnboardingReadiness,
    OperatingHoursReplace,
    OperatingIntervalRead,
    OutletCreate,
    OutletPatch,
    OutletRead,
    RestaurantCreate,
    RestaurantPatch,
    RestaurantRead,
    TaxProfileRead,
    TaxProfileUpsert,
)
from ainza_restaurant.restaurants.service import (
    OnboardingConflict,
    OnboardingNotFound,
    RestaurantOnboardingService,
)

router = APIRouter(tags=["restaurants"])


def service(session: AsyncSession = Depends(get_db_session)) -> RestaurantOnboardingService:
    return RestaurantOnboardingService(session)


def _not_found(exc: OnboardingNotFound) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "not_found", "message": str(exc)},
    )


def _conflict(exc: OnboardingConflict) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": exc.code, "message": str(exc), "details": exc.details},
    )


@router.post(
    "/api/v1/restaurants",
    response_model=RestaurantRead,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/restaurants",
    response_model=RestaurantRead,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def create_restaurant(
    payload: RestaurantCreate, onboarding: RestaurantOnboardingService = Depends(service)
) -> RestaurantRead:
    try:
        return RestaurantRead.model_validate(await onboarding.create_restaurant(payload))
    except OnboardingConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/restaurants", response_model=list[RestaurantRead])
@router.get("/restaurants", response_model=list[RestaurantRead], include_in_schema=False)
async def list_restaurants(
    onboarding: RestaurantOnboardingService = Depends(service),
) -> list[RestaurantRead]:
    return [
        RestaurantRead.model_validate(restaurant)
        for restaurant in await onboarding.list_restaurants()
    ]


@router.get("/api/v1/restaurants/{restaurant_id}", response_model=RestaurantRead)
@router.get("/restaurants/{restaurant_id}", response_model=RestaurantRead, include_in_schema=False)
async def get_restaurant(
    restaurant_id: UUID, onboarding: RestaurantOnboardingService = Depends(service)
) -> RestaurantRead:
    try:
        return RestaurantRead.model_validate(await onboarding.get_restaurant(restaurant_id))
    except OnboardingNotFound as exc:
        raise _not_found(exc) from exc


@router.patch("/api/v1/restaurants/{restaurant_id}", response_model=RestaurantRead)
@router.patch(
    "/restaurants/{restaurant_id}", response_model=RestaurantRead, include_in_schema=False
)
async def patch_restaurant(
    restaurant_id: UUID,
    payload: RestaurantPatch,
    onboarding: RestaurantOnboardingService = Depends(service),
) -> RestaurantRead:
    try:
        return RestaurantRead.model_validate(
            await onboarding.update_restaurant(restaurant_id, payload)
        )
    except OnboardingNotFound as exc:
        raise _not_found(exc) from exc
    except OnboardingConflict as exc:
        raise _conflict(exc) from exc


@router.post(
    "/api/v1/restaurants/{restaurant_id}/outlets",
    response_model=OutletRead,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/restaurants/{restaurant_id}/outlets",
    response_model=OutletRead,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def create_outlet(
    restaurant_id: UUID,
    payload: OutletCreate,
    onboarding: RestaurantOnboardingService = Depends(service),
) -> OutletRead:
    try:
        return OutletRead.model_validate(await onboarding.create_outlet(restaurant_id, payload))
    except OnboardingNotFound as exc:
        raise _not_found(exc) from exc
    except OnboardingConflict as exc:
        raise _conflict(exc) from exc


@router.get(
    "/api/v1/restaurants/{restaurant_id}/outlets",
    response_model=list[OutletRead],
)
@router.get(
    "/restaurants/{restaurant_id}/outlets",
    response_model=list[OutletRead],
    include_in_schema=False,
)
async def list_outlets(
    restaurant_id: UUID,
    onboarding: RestaurantOnboardingService = Depends(service),
) -> list[OutletRead]:
    try:
        return [
            OutletRead.model_validate(outlet)
            for outlet in await onboarding.list_outlets(restaurant_id)
        ]
    except OnboardingNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/restaurants/{restaurant_id}/outlets/{outlet_id}", response_model=OutletRead)
@router.get(
    "/restaurants/{restaurant_id}/outlets/{outlet_id}",
    response_model=OutletRead,
    include_in_schema=False,
)
async def get_outlet(
    restaurant_id: UUID,
    outlet_id: UUID,
    onboarding: RestaurantOnboardingService = Depends(service),
) -> OutletRead:
    try:
        return OutletRead.model_validate(await onboarding.get_outlet(restaurant_id, outlet_id))
    except OnboardingNotFound as exc:
        raise _not_found(exc) from exc


@router.patch("/api/v1/restaurants/{restaurant_id}/outlets/{outlet_id}", response_model=OutletRead)
@router.patch(
    "/restaurants/{restaurant_id}/outlets/{outlet_id}",
    response_model=OutletRead,
    include_in_schema=False,
)
async def patch_outlet(
    restaurant_id: UUID,
    outlet_id: UUID,
    payload: OutletPatch,
    onboarding: RestaurantOnboardingService = Depends(service),
) -> OutletRead:
    try:
        return OutletRead.model_validate(
            await onboarding.update_outlet(restaurant_id, outlet_id, payload)
        )
    except OnboardingNotFound as exc:
        raise _not_found(exc) from exc
    except OnboardingConflict as exc:
        raise _conflict(exc) from exc


@router.put(
    "/api/v1/restaurants/{restaurant_id}/outlets/{outlet_id}/operating-hours",
    response_model=list[OperatingIntervalRead],
)
@router.put(
    "/restaurants/{restaurant_id}/outlets/{outlet_id}/operating-hours",
    response_model=list[OperatingIntervalRead],
    include_in_schema=False,
)
@router.put(
    "/restaurants/{restaurant_id}/outlets/{outlet_id}/hours",
    response_model=list[OperatingIntervalRead],
    include_in_schema=False,
)
async def replace_operating_hours(
    restaurant_id: UUID,
    outlet_id: UUID,
    payload: OperatingHoursReplace,
    onboarding: RestaurantOnboardingService = Depends(service),
) -> list[OperatingIntervalRead]:
    try:
        intervals = await onboarding.replace_hours(restaurant_id, outlet_id, payload)
        return [OperatingIntervalRead.model_validate(interval) for interval in intervals]
    except OnboardingNotFound as exc:
        raise _not_found(exc) from exc
    except OnboardingConflict as exc:
        raise _conflict(exc) from exc


@router.get(
    "/api/v1/restaurants/{restaurant_id}/outlets/{outlet_id}/operating-hours",
    response_model=list[OperatingIntervalRead],
)
@router.get(
    "/restaurants/{restaurant_id}/outlets/{outlet_id}/operating-hours",
    response_model=list[OperatingIntervalRead],
    include_in_schema=False,
)
async def get_operating_hours(
    restaurant_id: UUID,
    outlet_id: UUID,
    onboarding: RestaurantOnboardingService = Depends(service),
) -> list[OperatingIntervalRead]:
    try:
        intervals = await onboarding.get_hours(restaurant_id, outlet_id)
        return [OperatingIntervalRead.model_validate(interval) for interval in intervals]
    except OnboardingNotFound as exc:
        raise _not_found(exc) from exc


@router.put(
    "/api/v1/restaurants/{restaurant_id}/outlets/{outlet_id}/tax-profile",
    response_model=TaxProfileRead,
)
async def upsert_tax_profile(
    restaurant_id: UUID,
    outlet_id: UUID,
    payload: TaxProfileUpsert,
    onboarding: RestaurantOnboardingService = Depends(service),
) -> TaxProfileRead:
    try:
        return TaxProfileRead.model_validate(
            await onboarding.upsert_tax_profile(restaurant_id, outlet_id, payload)
        )
    except OnboardingNotFound as exc:
        raise _not_found(exc) from exc
    except OnboardingConflict as exc:
        raise _conflict(exc) from exc


@router.put(
    "/restaurants/{restaurant_id}/outlets/{outlet_id}/tax-profile",
    response_model=TaxProfileRead,
    include_in_schema=False,
)
async def upsert_legacy_tax_profile(
    restaurant_id: UUID,
    outlet_id: UUID,
    payload: LegacyTaxProfileUpsert,
    onboarding: RestaurantOnboardingService = Depends(service),
) -> TaxProfileRead:
    gst_registered = payload.gstin is not None
    modern_payload = TaxProfileUpsert(
        gst_registered=gst_registered,
        gst_state_code=payload.gstin[:2] if payload.gstin else None,
        gstin=payload.gstin,
        gstin_confirmed=payload.gstin_confirmed,
        configured_tax_rate_percent=None,
        prices_include_tax=None,
        tax_configuration_confirmed=False,
        no_auto_tax_rates_confirmed=payload.no_auto_tax_rates_confirmed,
        tax_rates_confirmed=payload.tax_rates_confirmed,
        confirm_no_auto_tax_rates=payload.confirm_no_auto_tax_rates,
    )
    try:
        return TaxProfileRead.model_validate(
            await onboarding.upsert_tax_profile(
                restaurant_id, outlet_id, modern_payload, legacy_compat=True
            )
        )
    except OnboardingNotFound as exc:
        raise _not_found(exc) from exc
    except OnboardingConflict as exc:
        raise _conflict(exc) from exc


@router.get(
    "/api/v1/restaurants/{restaurant_id}/outlets/{outlet_id}/tax-profile",
    response_model=TaxProfileRead,
)
@router.get(
    "/restaurants/{restaurant_id}/outlets/{outlet_id}/tax-profile",
    response_model=TaxProfileRead,
    include_in_schema=False,
)
async def get_tax_profile(
    restaurant_id: UUID,
    outlet_id: UUID,
    onboarding: RestaurantOnboardingService = Depends(service),
) -> TaxProfileRead:
    try:
        profile = await onboarding.get_tax_profile(restaurant_id, outlet_id)
        if profile is None:
            raise OnboardingNotFound("tax profile not found")
        return TaxProfileRead.model_validate(profile)
    except OnboardingNotFound as exc:
        raise _not_found(exc) from exc


@router.put(
    "/api/v1/outlets/{outlet_id}/food-policy",
    response_model=FoodPolicyRead,
)
async def upsert_food_policy(
    outlet_id: UUID,
    payload: FoodPolicyUpsert,
    onboarding: RestaurantOnboardingService = Depends(service),
) -> FoodPolicyRead:
    """Upsert food policy while validating outlet ownership from the URL payload."""
    try:
        outlet = await onboarding.get_outlet_by_id(outlet_id)
        return FoodPolicyRead.model_validate(
            await onboarding.upsert_food_policy(outlet.restaurant_id, outlet_id, payload)
        )
    except OnboardingNotFound as exc:
        raise _not_found(exc) from exc
    except OnboardingConflict as exc:
        raise _conflict(exc) from exc


@router.get(
    "/api/v1/outlets/{outlet_id}/food-policy",
    response_model=FoodPolicyRead,
)
async def get_food_policy(
    outlet_id: UUID,
    onboarding: RestaurantOnboardingService = Depends(service),
) -> FoodPolicyRead:
    try:
        outlet = await onboarding.get_outlet_by_id(outlet_id)
        policy = await onboarding.get_food_policy(outlet.restaurant_id, outlet_id)
        if policy is None:
            raise OnboardingNotFound("food policy not found")
        return FoodPolicyRead.model_validate(policy)
    except OnboardingNotFound as exc:
        raise _not_found(exc) from exc


@router.get(
    "/api/v1/restaurants/{restaurant_id}/onboarding/status",
    response_model=OnboardingReadiness,
)
@router.get(
    "/restaurants/{restaurant_id}/onboarding/status",
    response_model=OnboardingReadiness,
    include_in_schema=False,
)
@router.get(
    "/restaurants/{restaurant_id}/onboarding/readiness",
    response_model=OnboardingReadiness,
    include_in_schema=False,
)
async def get_onboarding_status(
    restaurant_id: UUID, onboarding: RestaurantOnboardingService = Depends(service)
) -> OnboardingReadiness:
    try:
        return await onboarding.readiness(restaurant_id)
    except OnboardingNotFound as exc:
        raise _not_found(exc) from exc


@router.post(
    "/api/v1/restaurants/{restaurant_id}/onboarding/finalize",
    response_model=FinalizationResponse,
)
async def finalize_onboarding(
    restaurant_id: UUID,
    payload: FinalizeRequest,
    onboarding: RestaurantOnboardingService = Depends(service),
) -> FinalizationResponse:
    try:
        restaurant = await onboarding.finalize(restaurant_id, payload)
        return FinalizationResponse(
            restaurant=RestaurantRead.model_validate(restaurant),
            readiness=await onboarding.readiness(restaurant_id),
        )
    except OnboardingNotFound as exc:
        raise _not_found(exc) from exc
    except OnboardingConflict as exc:
        raise _conflict(exc) from exc


@router.post(
    "/restaurants/{restaurant_id}/onboarding/finalize",
    response_model=None,
    include_in_schema=False,
)
async def finalize_legacy_onboarding(
    restaurant_id: UUID,
    payload: FinalizeRequest | None = Body(default=None),
    onboarding: RestaurantOnboardingService = Depends(service),
) -> dict[str, Any]:
    try:
        restaurant = await onboarding.finalize(
            restaurant_id, payload or FinalizeRequest(confirm=True)
        )
        restaurant_data = RestaurantRead.model_validate(restaurant).model_dump(mode="json")
        restaurant_data["status"] = "finalized"
        return {
            "restaurant": restaurant_data,
            "readiness": (await onboarding.readiness(restaurant_id)).model_dump(mode="json"),
        }
    except OnboardingNotFound as exc:
        raise _not_found(exc) from exc
    except OnboardingConflict as exc:
        raise _conflict(exc) from exc
