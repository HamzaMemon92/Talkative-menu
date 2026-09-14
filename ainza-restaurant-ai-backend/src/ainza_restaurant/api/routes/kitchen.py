# ruff: noqa: B008
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.db.session import get_db_session
from ainza_restaurant.domain.enums import KitchenTicketStatus
from ainza_restaurant.kitchen.schemas import KitchenTicketRead
from ainza_restaurant.kitchen.service import KitchenConflict, KitchenNotFound, KitchenService

router = APIRouter(tags=["kitchen"])


def service(session: AsyncSession = Depends(get_db_session)) -> KitchenService:
    return KitchenService(session)


def _not_found(exc: KitchenNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})


def _conflict(exc: KitchenConflict) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": exc.code, "message": str(exc), "details": exc.details},
    )


@router.get("/api/v1/outlets/{outlet_id}/kitchen/tickets", response_model=list[KitchenTicketRead])
async def list_kitchen_tickets(
    outlet_id: UUID,
    ticket_status: KitchenTicketStatus | None = Query(default=None, alias="status"),
    kitchen: KitchenService = Depends(service),
) -> list[KitchenTicketRead]:
    try:
        return await kitchen.list_tickets(outlet_id, status=ticket_status)
    except KitchenNotFound as exc:
        raise _not_found(exc) from exc
    except KitchenConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/kitchen/tickets/{ticket_id}", response_model=KitchenTicketRead)
async def get_kitchen_ticket(
    ticket_id: UUID,
    kitchen: KitchenService = Depends(service),
) -> KitchenTicketRead:
    try:
        return await kitchen.get_ticket(ticket_id)
    except KitchenNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/api/v1/kitchen/tickets/{ticket_id}/start", response_model=KitchenTicketRead)
async def start_kitchen_ticket(
    ticket_id: UUID,
    kitchen: KitchenService = Depends(service),
) -> KitchenTicketRead:
    try:
        return await kitchen.start_ticket(ticket_id)
    except KitchenNotFound as exc:
        raise _not_found(exc) from exc
    except KitchenConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/kitchen/tickets/{ticket_id}/ready", response_model=KitchenTicketRead)
async def ready_kitchen_ticket(
    ticket_id: UUID,
    kitchen: KitchenService = Depends(service),
) -> KitchenTicketRead:
    try:
        return await kitchen.ready_ticket(ticket_id)
    except KitchenNotFound as exc:
        raise _not_found(exc) from exc
    except KitchenConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/kitchen/tickets/{ticket_id}/serve", response_model=KitchenTicketRead)
async def serve_kitchen_ticket(
    ticket_id: UUID,
    kitchen: KitchenService = Depends(service),
) -> KitchenTicketRead:
    try:
        return await kitchen.serve_ticket(ticket_id)
    except KitchenNotFound as exc:
        raise _not_found(exc) from exc
    except KitchenConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/kitchen/items/{ticket_item_id}/start", response_model=KitchenTicketRead)
async def start_kitchen_item(
    ticket_item_id: UUID,
    kitchen: KitchenService = Depends(service),
) -> KitchenTicketRead:
    try:
        return await kitchen.start_item(ticket_item_id)
    except KitchenNotFound as exc:
        raise _not_found(exc) from exc
    except KitchenConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/kitchen/items/{ticket_item_id}/ready", response_model=KitchenTicketRead)
async def ready_kitchen_item(
    ticket_item_id: UUID,
    kitchen: KitchenService = Depends(service),
) -> KitchenTicketRead:
    try:
        return await kitchen.ready_item(ticket_item_id)
    except KitchenNotFound as exc:
        raise _not_found(exc) from exc
    except KitchenConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/kitchen/items/{ticket_item_id}/serve", response_model=KitchenTicketRead)
async def serve_kitchen_item(
    ticket_item_id: UUID,
    kitchen: KitchenService = Depends(service),
) -> KitchenTicketRead:
    try:
        return await kitchen.serve_item(ticket_item_id)
    except KitchenNotFound as exc:
        raise _not_found(exc) from exc
    except KitchenConflict as exc:
        raise _conflict(exc) from exc
