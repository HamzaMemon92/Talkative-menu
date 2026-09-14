# ruff: noqa: B008
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.customer_menu.schemas import (
    CustomerDishRead,
    CustomerMenuFilters,
    CustomerMenuRead,
)
from ainza_restaurant.customer_menu.service import (
    CustomerMenuConflict,
    CustomerMenuNotFound,
    CustomerMenuService,
)
from ainza_restaurant.db.session import get_db_session
from ainza_restaurant.domain.enums import (
    AvailabilityStatus,
    DietaryClassification,
    HalalOverride,
    ItemType,
    SpiceLevel,
)

router = APIRouter(tags=["customer menu"])


def service(session: AsyncSession = Depends(get_db_session)) -> CustomerMenuService:
    return CustomerMenuService(session)


def _not_found(exc: CustomerMenuNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})


def _conflict(exc: CustomerMenuConflict) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": exc.code, "message": str(exc), "details": exc.details},
    )


def _filters(
    category_id: UUID | None = None,
    cuisine_id: UUID | None = None,
    item_type: ItemType | None = None,
    dietary_classification: DietaryClassification | None = None,
    vegan_status: AvailabilityStatus | None = None,
    jain_status: AvailabilityStatus | None = None,
    halal_status: HalalOverride | None = None,
    spice_level: SpiceLevel | None = None,
    available: bool | None = None,
    is_featured: bool | None = None,
    is_todays_special: bool | None = None,
) -> CustomerMenuFilters:
    return CustomerMenuFilters(
        category_id=category_id,
        cuisine_id=cuisine_id,
        item_type=item_type,
        dietary_classification=dietary_classification,
        vegan_status=vegan_status,
        jain_status=jain_status,
        halal_status=halal_status,
        spice_level=spice_level,
        available=available,
        is_featured=is_featured,
        is_todays_special=is_todays_special,
    )


@router.get("/api/v1/outlets/{outlet_id}/customer-menu", response_model=CustomerMenuRead)
async def get_customer_menu(
    outlet_id: UUID,
    filters: CustomerMenuFilters = Depends(_filters),
    customer_menu: CustomerMenuService = Depends(service),
) -> CustomerMenuRead:
    try:
        return await customer_menu.get_menu(outlet_id, filters=filters)
    except CustomerMenuNotFound as exc:
        raise _not_found(exc) from exc
    except CustomerMenuConflict as exc:
        raise _conflict(exc) from exc


@router.get(
    "/api/v1/outlets/{outlet_id}/customer-menu/search",
    response_model=list[CustomerDishRead],
)
async def search_customer_menu(
    outlet_id: UUID,
    q: str = Query(min_length=1),
    filters: CustomerMenuFilters = Depends(_filters),
    customer_menu: CustomerMenuService = Depends(service),
) -> list[CustomerDishRead]:
    try:
        return await customer_menu.search(outlet_id, q=q, filters=filters)
    except CustomerMenuNotFound as exc:
        raise _not_found(exc) from exc
    except CustomerMenuConflict as exc:
        raise _conflict(exc) from exc


@router.get(
    "/api/v1/outlets/{outlet_id}/customer-menu/dishes/{dish_id}",
    response_model=CustomerDishRead,
)
async def get_customer_menu_dish(
    outlet_id: UUID,
    dish_id: UUID,
    customer_menu: CustomerMenuService = Depends(service),
) -> CustomerDishRead:
    try:
        return await customer_menu.get_dish(outlet_id, dish_id)
    except CustomerMenuNotFound as exc:
        raise _not_found(exc) from exc
    except CustomerMenuConflict as exc:
        raise _conflict(exc) from exc
