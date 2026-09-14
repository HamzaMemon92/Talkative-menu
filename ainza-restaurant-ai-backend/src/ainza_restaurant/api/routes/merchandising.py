# ruff: noqa: B008
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.db.session import get_db_session
from ainza_restaurant.merchandising.schemas import (
    ComboItemsReplace,
    ConfirmRequest,
    FeaturedCreate,
    FeaturedPatch,
    FeaturedRead,
    OfferCreate,
    OfferPatch,
    OfferPreviewRead,
    OfferPreviewRequest,
    OfferRead,
    ScopeCategoryReplace,
    ScopeDishReplace,
    SpecialCreate,
    SpecialPatch,
    SpecialRead,
)
from ainza_restaurant.merchandising.service import (
    MerchandisingConflict,
    MerchandisingNotFound,
    MerchandisingService,
)

router = APIRouter(tags=["merchandising"])


def service(session: AsyncSession = Depends(get_db_session)) -> MerchandisingService:
    return MerchandisingService(session)


def _not_found(exc: MerchandisingNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})


def _conflict(exc: MerchandisingConflict) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": exc.code, "message": str(exc), "details": exc.details},
    )


@router.post("/api/v1/outlets/{outlet_id}/specials", response_model=SpecialRead, status_code=201)
async def create_special(
    outlet_id: UUID, payload: SpecialCreate, promo: MerchandisingService = Depends(service)
) -> SpecialRead:
    try:
        return await promo.create_special(outlet_id, payload)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/outlets/{outlet_id}/specials", response_model=list[SpecialRead])
async def list_specials(
    outlet_id: UUID, promo: MerchandisingService = Depends(service)
) -> list[SpecialRead]:
    try:
        return await promo.list_specials(outlet_id)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/outlets/{outlet_id}/specials/effective", response_model=list[SpecialRead])
async def list_effective_specials(
    outlet_id: UUID, promo: MerchandisingService = Depends(service)
) -> list[SpecialRead]:
    try:
        return await promo.list_specials(outlet_id, effective=True)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/specials/{special_id}", response_model=SpecialRead)
async def get_special(
    special_id: UUID, promo: MerchandisingService = Depends(service)
) -> SpecialRead:
    try:
        return await promo.get_special(special_id)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc


@router.patch("/api/v1/specials/{special_id}", response_model=SpecialRead)
async def patch_special(
    special_id: UUID, payload: SpecialPatch, promo: MerchandisingService = Depends(service)
) -> SpecialRead:
    try:
        return await promo.patch_special(special_id, payload)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/specials/{special_id}/activate", response_model=SpecialRead)
async def activate_special(
    special_id: UUID, payload: ConfirmRequest, promo: MerchandisingService = Depends(service)
) -> SpecialRead:
    try:
        return await promo.activate_special(special_id, confirm=payload.confirm)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/specials/{special_id}/deactivate", response_model=SpecialRead)
async def deactivate_special(
    special_id: UUID, payload: ConfirmRequest, promo: MerchandisingService = Depends(service)
) -> SpecialRead:
    try:
        return await promo.deactivate_special(special_id, confirm=payload.confirm)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc


@router.post(
    "/api/v1/outlets/{outlet_id}/featured-dishes",
    response_model=FeaturedRead,
    status_code=201,
)
async def create_featured(
    outlet_id: UUID, payload: FeaturedCreate, promo: MerchandisingService = Depends(service)
) -> FeaturedRead:
    try:
        return await promo.create_featured(outlet_id, payload)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/outlets/{outlet_id}/featured-dishes", response_model=list[FeaturedRead])
async def list_featured(
    outlet_id: UUID, promo: MerchandisingService = Depends(service)
) -> list[FeaturedRead]:
    try:
        return await promo.list_featured(outlet_id)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc


@router.get(
    "/api/v1/outlets/{outlet_id}/featured-dishes/effective",
    response_model=list[FeaturedRead],
)
async def list_effective_featured(
    outlet_id: UUID, promo: MerchandisingService = Depends(service)
) -> list[FeaturedRead]:
    try:
        return await promo.list_featured(outlet_id, effective=True)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/featured-dishes/{featured_id}", response_model=FeaturedRead)
async def get_featured(
    featured_id: UUID, promo: MerchandisingService = Depends(service)
) -> FeaturedRead:
    try:
        return await promo.get_featured(featured_id)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc


@router.patch("/api/v1/featured-dishes/{featured_id}", response_model=FeaturedRead)
async def patch_featured(
    featured_id: UUID, payload: FeaturedPatch, promo: MerchandisingService = Depends(service)
) -> FeaturedRead:
    try:
        return await promo.patch_featured(featured_id, payload)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/featured-dishes/{featured_id}/activate", response_model=FeaturedRead)
async def activate_featured(
    featured_id: UUID, payload: ConfirmRequest, promo: MerchandisingService = Depends(service)
) -> FeaturedRead:
    try:
        return await promo.activate_featured(featured_id, confirm=payload.confirm)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/featured-dishes/{featured_id}/deactivate", response_model=FeaturedRead)
async def deactivate_featured(
    featured_id: UUID, payload: ConfirmRequest, promo: MerchandisingService = Depends(service)
) -> FeaturedRead:
    try:
        return await promo.deactivate_featured(featured_id, confirm=payload.confirm)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/outlets/{outlet_id}/offers", response_model=OfferRead, status_code=201)
async def create_offer(
    outlet_id: UUID, payload: OfferCreate, promo: MerchandisingService = Depends(service)
) -> OfferRead:
    try:
        return await promo.create_offer(outlet_id, payload)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/outlets/{outlet_id}/offers", response_model=list[OfferRead])
async def list_offers(
    outlet_id: UUID, promo: MerchandisingService = Depends(service)
) -> list[OfferRead]:
    try:
        return await promo.list_offers(outlet_id)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/outlets/{outlet_id}/offers/effective", response_model=list[OfferRead])
async def list_effective_offers(
    outlet_id: UUID, promo: MerchandisingService = Depends(service)
) -> list[OfferRead]:
    try:
        return await promo.list_offers(outlet_id, effective=True)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/offers/{offer_id}", response_model=OfferRead)
async def get_offer(offer_id: UUID, promo: MerchandisingService = Depends(service)) -> OfferRead:
    try:
        return await promo.get_offer(offer_id)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc


@router.patch("/api/v1/offers/{offer_id}", response_model=OfferRead)
async def patch_offer(
    offer_id: UUID, payload: OfferPatch, promo: MerchandisingService = Depends(service)
) -> OfferRead:
    try:
        return await promo.patch_offer(offer_id, payload)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc


@router.put("/api/v1/offers/{offer_id}/scope/dishes", response_model=OfferRead)
async def replace_offer_dish_scope(
    offer_id: UUID, payload: ScopeDishReplace, promo: MerchandisingService = Depends(service)
) -> OfferRead:
    try:
        return await promo.replace_offer_dish_scope(offer_id, payload)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc


@router.put("/api/v1/offers/{offer_id}/scope/categories", response_model=OfferRead)
async def replace_offer_category_scope(
    offer_id: UUID, payload: ScopeCategoryReplace, promo: MerchandisingService = Depends(service)
) -> OfferRead:
    try:
        return await promo.replace_offer_category_scope(offer_id, payload)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc


@router.put("/api/v1/offers/{offer_id}/combo-items", response_model=OfferRead)
async def replace_combo_items(
    offer_id: UUID, payload: ComboItemsReplace, promo: MerchandisingService = Depends(service)
) -> OfferRead:
    try:
        return await promo.replace_combo_items(offer_id, payload)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/offers/{offer_id}/activate", response_model=OfferRead)
async def activate_offer(
    offer_id: UUID, payload: ConfirmRequest, promo: MerchandisingService = Depends(service)
) -> OfferRead:
    try:
        return await promo.activate_offer(offer_id, confirm=payload.confirm)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/offers/{offer_id}/pause", response_model=OfferRead)
async def pause_offer(
    offer_id: UUID, payload: ConfirmRequest, promo: MerchandisingService = Depends(service)
) -> OfferRead:
    try:
        return await promo.pause_offer(offer_id, confirm=payload.confirm)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/offers/{offer_id}/deactivate", response_model=OfferRead)
async def deactivate_offer(
    offer_id: UUID, payload: ConfirmRequest, promo: MerchandisingService = Depends(service)
) -> OfferRead:
    try:
        return await promo.deactivate_offer(offer_id, confirm=payload.confirm)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/offers/{offer_id}/preview", response_model=OfferPreviewRead)
async def preview_offer(
    offer_id: UUID, payload: OfferPreviewRequest, promo: MerchandisingService = Depends(service)
) -> OfferPreviewRead:
    try:
        return await promo.preview_offer(offer_id, payload)
    except MerchandisingNotFound as exc:
        raise _not_found(exc) from exc
    except MerchandisingConflict as exc:
        raise _conflict(exc) from exc
