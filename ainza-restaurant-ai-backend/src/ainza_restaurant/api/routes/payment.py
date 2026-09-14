# ruff: noqa: B008
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.ai.context import AIActorType
from ainza_restaurant.core.config import get_settings
from ainza_restaurant.db.session import get_db_session
from ainza_restaurant.dining.models import DiningSession
from ainza_restaurant.payment.schemas import (
    ManualPaymentConfirmRequest,
    PaymentIntentCreate,
    PaymentIntentRead,
    PaymentWebhookResponse,
)
from ainza_restaurant.payment.service import PaymentConflict, PaymentNotFound, PaymentService

router = APIRouter(tags=["payment"])


def service(session: AsyncSession = Depends(get_db_session)) -> PaymentService:
    return PaymentService(session)


def _not_found(exc: PaymentNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})


def _conflict(exc: PaymentConflict) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": exc.code, "message": str(exc), "details": exc.details},
    )


@router.post(
    "/api/v1/dining-sessions/{session_token}/payment-intents",
    response_model=PaymentIntentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment_intent(
    session_token: str,
    payload: PaymentIntentCreate,
    session: AsyncSession = Depends(get_db_session),
    payment: PaymentService = Depends(service),
) -> PaymentIntentRead:
    dining_session = await session.scalar(
        select(DiningSession).where(DiningSession.public_session_token == session_token)
    )

    if dining_session is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "dining_session_not_found", "message": "Dining session not found"},
        )

    idempotency_key = (
        payload.idempotency_key or f"pay_{dining_session.id}_{payload.payment_mode.value}"
    )
    try:
        intent = await payment.create_payment_intent(
            dining_session_id=dining_session.id,
            payment_mode=payload.payment_mode,
            idempotency_key=idempotency_key,
        )
        return PaymentIntentRead.model_validate(intent)
    except PaymentNotFound as exc:
        raise _not_found(exc) from exc
    except PaymentConflict as exc:
        raise _conflict(exc) from exc


@router.get(
    "/api/v1/payment-intents/{intent_id}",
    response_model=PaymentIntentRead,
)
async def get_payment_intent(
    intent_id: UUID,
    payment: PaymentService = Depends(service),
) -> PaymentIntentRead:
    try:
        intent = await payment.get_payment_intent(intent_id)
        return PaymentIntentRead.model_validate(intent)
    except PaymentNotFound as exc:
        raise _not_found(exc) from exc


@router.post(
    "/api/v1/payment-intents/{intent_id}/confirm-manual",
    response_model=PaymentIntentRead,
)
async def confirm_manual_payment(
    intent_id: UUID,
    payload: ManualPaymentConfirmRequest,
    x_actor_type: str = Header(default="staff"),
    payment: PaymentService = Depends(service),
) -> PaymentIntentRead:
    actor = (
        AIActorType.STAFF
        if x_actor_type.lower() == "staff"
        else (AIActorType.OWNER if x_actor_type.lower() == "owner" else AIActorType.CUSTOMER)
    )
    try:
        intent = await payment.confirm_manual_payment(
            intent_id,
            actor_type=actor,
            staff_actor_id=payload.staff_actor_id,
            notes=payload.notes,
        )
        return PaymentIntentRead.model_validate(intent)
    except PaymentNotFound as exc:
        raise _not_found(exc) from exc
    except PaymentConflict as exc:
        raise _conflict(exc) from exc


@router.post(
    "/api/v1/payment-webhooks/{provider}",
    response_model=PaymentWebhookResponse,
)
async def handle_payment_webhook(
    provider: str,
    request: Request,
    payment: PaymentService = Depends(service),
) -> PaymentWebhookResponse:
    body = await request.body()
    headers = dict(request.headers)
    secret = get_settings().fake_payment_webhook_secret.get_secret_value()
    try:
        intent, is_duplicate = await payment.handle_provider_webhook(
            provider,
            raw_body=body,
            headers=headers,
            secret=secret,
        )
        return PaymentWebhookResponse(
            ok=True,
            status=intent.status.value,
            payment_intent_id=str(intent.id),
            duplicate=is_duplicate,
        )
    except PaymentNotFound as exc:
        raise _not_found(exc) from exc
    except PaymentConflict as exc:
        raise _conflict(exc) from exc
