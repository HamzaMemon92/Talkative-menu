# ruff: noqa: B008
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.availability.schemas import (
    AvailabilityCancelRequest,
    AvailabilityConfirmRequest,
    AvailabilityProposalCreate,
    AvailabilityProposalRead,
    DishAvailabilityRead,
    IngredientAvailabilityRead,
    OutletAvailabilityRead,
)
from ainza_restaurant.availability.service import (
    AvailabilityConflict,
    AvailabilityNotFound,
    AvailabilityService,
)
from ainza_restaurant.db.session import get_db_session

router = APIRouter(tags=["availability"])


def service(session: AsyncSession = Depends(get_db_session)) -> AvailabilityService:
    return AvailabilityService(session)


def _not_found(exc: AvailabilityNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})


def _conflict(exc: AvailabilityConflict) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": exc.code, "message": str(exc), "details": exc.details},
    )


@router.post(
    "/api/v1/outlets/{outlet_id}/availability/proposals",
    response_model=AvailabilityProposalRead,
    status_code=201,
)
async def create_availability_proposal(
    outlet_id: UUID,
    payload: AvailabilityProposalCreate,
    availability: AvailabilityService = Depends(service),
) -> AvailabilityProposalRead:
    try:
        return await availability.create_proposal(outlet_id, payload)
    except AvailabilityNotFound as exc:
        raise _not_found(exc) from exc
    except AvailabilityConflict as exc:
        raise _conflict(exc) from exc


@router.get(
    "/api/v1/availability-proposals/{proposal_id}",
    response_model=AvailabilityProposalRead,
)
async def get_availability_proposal(
    proposal_id: UUID, availability: AvailabilityService = Depends(service)
) -> AvailabilityProposalRead:
    try:
        return await availability.get_proposal(proposal_id)
    except AvailabilityNotFound as exc:
        raise _not_found(exc) from exc
    except AvailabilityConflict as exc:
        raise _conflict(exc) from exc


@router.post(
    "/api/v1/availability-proposals/{proposal_id}/confirm",
    response_model=AvailabilityProposalRead,
)
async def confirm_availability_proposal(
    proposal_id: UUID,
    payload: AvailabilityConfirmRequest,
    availability: AvailabilityService = Depends(service),
) -> AvailabilityProposalRead:
    try:
        return await availability.confirm_proposal(proposal_id, confirm=payload.confirm)
    except AvailabilityNotFound as exc:
        raise _not_found(exc) from exc
    except AvailabilityConflict as exc:
        raise _conflict(exc) from exc


@router.post(
    "/api/v1/availability-proposals/{proposal_id}/cancel",
    response_model=AvailabilityProposalRead,
)
async def cancel_availability_proposal(
    proposal_id: UUID,
    payload: AvailabilityCancelRequest | None = None,
    availability: AvailabilityService = Depends(service),
) -> AvailabilityProposalRead:
    try:
        if payload is not None and not payload.confirm:
            raise AvailabilityConflict(
                "availability cancellation requires confirm=true",
                code="availability_confirmation_required",
            )
        return await availability.cancel_proposal(proposal_id)
    except AvailabilityNotFound as exc:
        raise _not_found(exc) from exc
    except AvailabilityConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/dishes/{dish_id}/availability", response_model=DishAvailabilityRead)
async def get_dish_availability(
    dish_id: UUID, availability: AvailabilityService = Depends(service)
) -> DishAvailabilityRead:
    try:
        return await availability.dish_availability(dish_id)
    except AvailabilityNotFound as exc:
        raise _not_found(exc) from exc


@router.get(
    "/api/v1/ingredients/{ingredient_id}/availability",
    response_model=IngredientAvailabilityRead,
)
async def get_ingredient_availability(
    ingredient_id: UUID, availability: AvailabilityService = Depends(service)
) -> IngredientAvailabilityRead:
    try:
        return await availability.ingredient_availability(ingredient_id)
    except AvailabilityNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/outlets/{outlet_id}/availability", response_model=OutletAvailabilityRead)
async def get_outlet_availability(
    outlet_id: UUID,
    available: bool | None = None,
    category_id: UUID | None = None,
    availability: AvailabilityService = Depends(service),
) -> OutletAvailabilityRead:
    try:
        return await availability.outlet_availability(
            outlet_id, available=available, category_id=category_id
        )
    except AvailabilityNotFound as exc:
        raise _not_found(exc) from exc
