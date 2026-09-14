# ruff: noqa: B008
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.db.session import get_db_session
from ainza_restaurant.dining.schemas import (
    ActiveSessionRead,
    ConfirmRequest,
    DiningSessionRead,
    ManualSessionStartRequest,
    QRResolutionRead,
    SessionStartRead,
    SessionStartRequest,
    TableCreate,
    TablePatch,
    TableRead,
)
from ainza_restaurant.dining.service import DiningConflict, DiningNotFound, DiningService

router = APIRouter(tags=["tables and dining sessions"])


def service(session: AsyncSession = Depends(get_db_session)) -> DiningService:
    return DiningService(session)


def _not_found(exc: DiningNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})


def _conflict(exc: DiningConflict) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": exc.code, "message": str(exc), "details": exc.details},
    )


@router.post("/api/v1/outlets/{outlet_id}/tables", response_model=TableRead, status_code=201)
async def create_table(
    outlet_id: UUID, payload: TableCreate, dining: DiningService = Depends(service)
) -> TableRead:
    try:
        return await dining.create_table(outlet_id, payload)
    except DiningNotFound as exc:
        raise _not_found(exc) from exc
    except DiningConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/outlets/{outlet_id}/tables", response_model=list[TableRead])
async def list_tables(outlet_id: UUID, dining: DiningService = Depends(service)) -> list[TableRead]:
    try:
        return await dining.list_tables(outlet_id)
    except DiningNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/tables/{table_id}", response_model=TableRead)
async def get_table(table_id: UUID, dining: DiningService = Depends(service)) -> TableRead:
    try:
        return await dining.get_table(table_id)
    except DiningNotFound as exc:
        raise _not_found(exc) from exc


@router.patch("/api/v1/tables/{table_id}", response_model=TableRead)
async def patch_table(
    table_id: UUID, payload: TablePatch, dining: DiningService = Depends(service)
) -> TableRead:
    try:
        return await dining.patch_table(table_id, payload)
    except DiningNotFound as exc:
        raise _not_found(exc) from exc
    except DiningConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/tables/{table_id}/rotate-qr", response_model=TableRead)
async def rotate_qr(
    table_id: UUID, payload: ConfirmRequest, dining: DiningService = Depends(service)
) -> TableRead:
    try:
        return await dining.rotate_qr(table_id, confirm=payload.confirm)
    except DiningNotFound as exc:
        raise _not_found(exc) from exc
    except DiningConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/qr/{public_qr_code}", response_model=QRResolutionRead)
async def resolve_qr(
    public_qr_code: str, dining: DiningService = Depends(service)
) -> QRResolutionRead:
    try:
        return await dining.resolve_qr(public_qr_code)
    except DiningNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/api/v1/qr/{public_qr_code}/sessions", response_model=SessionStartRead)
async def start_session_from_qr(
    public_qr_code: str,
    payload: SessionStartRequest,
    dining: DiningService = Depends(service),
) -> SessionStartRead:
    try:
        return await dining.start_session_from_qr(public_qr_code, payload)
    except DiningNotFound as exc:
        raise _not_found(exc) from exc
    except DiningConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/tables/{table_id}/sessions", response_model=SessionStartRead)
async def start_manual_session(
    table_id: UUID,
    payload: ManualSessionStartRequest,
    dining: DiningService = Depends(service),
) -> SessionStartRead:
    try:
        return await dining.start_manual_session(table_id, payload)
    except DiningNotFound as exc:
        raise _not_found(exc) from exc
    except DiningConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/dining-sessions/{public_session_token}", response_model=DiningSessionRead)
async def get_dining_session(
    public_session_token: str, dining: DiningService = Depends(service)
) -> DiningSessionRead:
    try:
        return await dining.get_session(public_session_token)
    except DiningNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/tables/{table_id}/active-session", response_model=ActiveSessionRead)
async def active_session_for_table(
    table_id: UUID, dining: DiningService = Depends(service)
) -> ActiveSessionRead:
    try:
        return await dining.active_session_for_table(table_id)
    except DiningNotFound as exc:
        raise _not_found(exc) from exc


@router.post(
    "/api/v1/dining-sessions/{public_session_token}/close",
    response_model=DiningSessionRead,
)
async def close_dining_session(
    public_session_token: str,
    payload: ConfirmRequest,
    dining: DiningService = Depends(service),
) -> DiningSessionRead:
    try:
        return await dining.close_session(public_session_token, confirm=payload.confirm)
    except DiningNotFound as exc:
        raise _not_found(exc) from exc
    except DiningConflict as exc:
        raise _conflict(exc) from exc
