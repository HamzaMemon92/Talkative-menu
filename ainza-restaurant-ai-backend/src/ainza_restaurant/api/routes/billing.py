# ruff: noqa: B008
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.billing.schemas import BillPreviewRead, InvoiceFinalizeRequest, InvoiceRead
from ainza_restaurant.billing.service import BillingConflict, BillingNotFound, BillingService
from ainza_restaurant.db.session import get_db_session

router = APIRouter(tags=["billing"])


def service(session: AsyncSession = Depends(get_db_session)) -> BillingService:
    return BillingService(session)


def _not_found(exc: BillingNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})


def _conflict(exc: BillingConflict) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": exc.code, "message": str(exc), "details": exc.details},
    )


@router.get("/api/v1/dining-sessions/{session_token}/bill-preview", response_model=BillPreviewRead)
async def get_bill_preview(
    session_token: str,
    billing: BillingService = Depends(service),
) -> BillPreviewRead:
    try:
        return await billing.get_preview(session_token)
    except BillingNotFound as exc:
        raise _not_found(exc) from exc
    except BillingConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/dining-sessions/{session_token}/invoice/finalize", response_model=InvoiceRead)
async def finalize_invoice(
    session_token: str,
    payload: InvoiceFinalizeRequest,
    billing: BillingService = Depends(service),
) -> InvoiceRead:
    try:
        return await billing.finalize_invoice(session_token, payload)
    except BillingNotFound as exc:
        raise _not_found(exc) from exc
    except BillingConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/dining-sessions/{session_token}/invoice", response_model=InvoiceRead)
async def get_session_invoice(
    session_token: str,
    billing: BillingService = Depends(service),
) -> InvoiceRead:
    try:
        return await billing.get_session_invoice(session_token)
    except BillingNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/api/v1/invoices/{invoice_id}", response_model=InvoiceRead)
async def get_invoice(
    invoice_id: UUID,
    billing: BillingService = Depends(service),
) -> InvoiceRead:
    try:
        return await billing.get_invoice(invoice_id)
    except BillingNotFound as exc:
        raise _not_found(exc) from exc
