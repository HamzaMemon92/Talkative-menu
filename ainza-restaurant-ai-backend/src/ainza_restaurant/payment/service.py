from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ainza_restaurant.ai.context import AIActorType
from ainza_restaurant.billing.models import DiningInvoice
from ainza_restaurant.core.config import get_settings
from ainza_restaurant.dining.models import DiningSession
from ainza_restaurant.domain.enums import (
    DiningInvoiceStatus,
    PaymentAttemptStatus,
    PaymentMode,
    PaymentStatus,
)
from ainza_restaurant.payment.adapters.base import PaymentProviderAdapter
from ainza_restaurant.payment.adapters.fake import FakeDeterministicPaymentAdapter
from ainza_restaurant.payment.models import PaymentAttempt, PaymentEvent, PaymentIntent


class PaymentConflict(Exception):
    def __init__(self, message: str, *, code: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class PaymentNotFound(Exception):
    def __init__(
        self, message: str = "payment not found", *, code: str = "payment_not_found"
    ) -> None:
        super().__init__(message)
        self.code = code


class PaymentService:
    """Authoritative service for payment intent creation, provider adapters, webhooks,
    and manual confirmations.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        adapter: PaymentProviderAdapter | None = None,
        now: datetime | None = None,
    ) -> None:
        self.session = session
        self.adapter = adapter or FakeDeterministicPaymentAdapter()
        self._now = now

    def now(self) -> datetime:
        return self._now or datetime.now(UTC)

    async def create_payment_intent(
        self,
        *,
        dining_session_id: UUID,
        payment_mode: PaymentMode,
        idempotency_key: str,
        ttl_minutes: int | None = None,
    ) -> PaymentIntent:
        # 1. Validate DiningSession
        session_stmt = select(DiningSession).where(DiningSession.id == dining_session_id)
        dining_session = await self.session.scalar(session_stmt)
        if dining_session is None:
            raise PaymentNotFound("dining session not found", code="dining_session_not_found")

        # 2. Validate finalized DiningInvoice
        invoice_stmt = select(DiningInvoice).where(
            DiningInvoice.dining_session_id == dining_session_id,
            DiningInvoice.status == DiningInvoiceStatus.FINALIZED,
        )
        invoice = await self.session.scalar(invoice_stmt)
        if invoice is None:
            raise PaymentConflict(
                "A finalized invoice is required before payment intent can be created",
                code="invoice_not_finalized",
            )

        # 3. Check idempotency: existing intent for this session + idempotency key
        existing_stmt = (
            select(PaymentIntent)
            .options(selectinload(PaymentIntent.attempts), selectinload(PaymentIntent.events))
            .where(
                PaymentIntent.dining_session_id == dining_session_id,
                PaymentIntent.idempotency_key == idempotency_key,
            )
        )
        existing = await self.session.scalar(existing_stmt)
        if existing is not None:
            return existing

        current_time = self.now()
        ttl = ttl_minutes or get_settings().payment_intent_ttl_minutes
        expires_at = current_time + timedelta(minutes=ttl)

        # 4. Construct intent with frozen amount & currency
        intent = PaymentIntent(
            id=uuid.uuid4(),
            outlet_id=invoice.outlet_id,
            dining_session_id=dining_session.id,
            invoice_id=invoice.id,
            amount=invoice.invoice_total,
            currency_code=invoice.currency_code,
            status=PaymentStatus.PENDING,
            payment_mode=payment_mode,
            provider="fake",
            idempotency_key=idempotency_key,
            expires_at=expires_at,
            created_at=current_time,
            updated_at=current_time,
        )

        # 5. Online provider initialization
        if payment_mode == PaymentMode.ONLINE:
            provider_data = await self.adapter.create_intent(intent)
            intent.provider_intent_reference = provider_data.get("provider_reference")
            intent.qr_payload = provider_data.get("qr_payload")
            intent.checkout_url = provider_data.get("checkout_url")
        else:
            # Pay at table / counter: QR carries the payment intent token
            intent.qr_payload = (
                f"ainza_pay_manual:{intent.id}:{intent.amount}:{intent.currency_code}"
            )

        self.session.add(intent)
        await self.session.flush()

        # Record initial attempt and creation event
        attempt = PaymentAttempt(
            payment_intent_id=intent.id,
            intent=intent,
            attempt_number=1,
            status=PaymentAttemptStatus.INITIATED,
            provider_reference=intent.provider_intent_reference,
            created_at=current_time,
        )
        event = PaymentEvent(
            payment_intent_id=intent.id,
            intent=intent,
            event_type="intent_created",
            data={
                "amount": str(intent.amount),
                "currency": intent.currency_code,
                "mode": intent.payment_mode.value,
            },
            created_at=current_time,
        )
        self.session.add(attempt)
        self.session.add(event)
        await self.session.commit()

        await self.session.refresh(intent, ["attempts", "events"])
        return intent

    async def get_payment_intent(self, intent_id: UUID) -> PaymentIntent:
        stmt = (
            select(PaymentIntent)
            .options(selectinload(PaymentIntent.attempts), selectinload(PaymentIntent.events))
            .where(PaymentIntent.id == intent_id)
        )
        intent = await self.session.scalar(stmt)
        if intent is None:
            raise PaymentNotFound("payment intent not found", code="payment_intent_not_found")
        return intent

    async def confirm_manual_payment(
        self,
        intent_id: UUID,
        *,
        actor_type: AIActorType,
        staff_actor_id: str,
        notes: str | None = None,
    ) -> PaymentIntent:
        """Staff/Owner action to confirm a PAY_AT_TABLE or PAY_AT_COUNTER payment."""
        if actor_type not in {AIActorType.STAFF, AIActorType.OWNER}:
            raise PaymentConflict(
                "Only authorized staff or owners can confirm table/counter payments",
                code="payment_confirmation_forbidden",
            )

        intent = await self.get_payment_intent(intent_id)

        if intent.status == PaymentStatus.SUCCESS:
            return intent  # Idempotent success

        if intent.status in {PaymentStatus.CANCELLED, PaymentStatus.EXPIRED}:
            raise PaymentConflict(
                f"Cannot confirm payment with status {intent.status.value}",
                code="payment_invalid_state",
            )

        if intent.payment_mode not in {PaymentMode.PAY_AT_TABLE, PaymentMode.PAY_AT_COUNTER}:
            raise PaymentConflict(
                "Manual confirmation is only valid for pay_at_table or pay_at_counter modes",
                code="manual_confirmation_invalid_mode",
            )

        current_time = self.now()
        intent.status = PaymentStatus.SUCCESS
        intent.updated_at = current_time

        attempt = PaymentAttempt(
            payment_intent_id=intent.id,
            intent=intent,
            attempt_number=len(intent.attempts) + 1 if intent.attempts else 1,
            status=PaymentAttemptStatus.SUCCESS,
            provider_reference=f"staff_{staff_actor_id}",
            raw_payload={"notes": notes, "staff_id": staff_actor_id},
            created_at=current_time,
        )
        event = PaymentEvent(
            payment_intent_id=intent.id,
            intent=intent,
            event_type="staff_confirmed",
            data={"staff_id": staff_actor_id, "notes": notes},
            created_at=current_time,
        )
        self.session.add(attempt)
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(intent, ["attempts", "events"])
        return intent

    async def handle_provider_webhook(
        self,
        provider_name: str,
        raw_body: bytes,
        headers: dict[str, str],
        secret: str,
    ) -> tuple[PaymentIntent, bool]:
        """Verify webhook signature, validate amount and transition intent to SUCCESS.

        Returns: (intent, is_duplicate)
        """
        try:
            payload = self.adapter.verify_webhook(raw_body, headers, secret)
        except ValueError as exc:
            raise PaymentConflict(
                f"Webhook verification failed: {exc}", code="bad_signature"
            ) from exc

        intent_id_str = payload.get("payment_intent_id")
        if not intent_id_str:
            raise PaymentConflict(
                "Missing payment_intent_id in webhook payload", code="invalid_payload"
            )

        intent = await self.get_payment_intent(UUID(intent_id_str))

        # Duplicate webhook safety: if already SUCCESS, acknowledge safely without reprocessing
        if intent.status == PaymentStatus.SUCCESS:
            return intent, True

        # Amount and currency verification
        webhook_amount = Decimal(str(payload.get("amount", 0)))
        webhook_currency = str(payload.get("currency", "")).upper()
        if webhook_amount != intent.amount or webhook_currency != intent.currency_code.upper():
            current_time = self.now()
            attempt = PaymentAttempt(
                payment_intent_id=intent.id,
                intent=intent,
                attempt_number=len(intent.attempts) + 1 if intent.attempts else 1,
                status=PaymentAttemptStatus.FAILED,
                failure_code="amount_mismatch",
                failure_message=(
                    f"Expected {intent.currency_code} {intent.amount}, "
                    f"got {webhook_currency} {webhook_amount}"
                ),
                raw_payload=payload,
                created_at=current_time,
            )
            self.session.add(attempt)
            await self.session.commit()
            raise PaymentConflict(
                "Webhook amount or currency does not match authoritative payment intent",
                code="payment_amount_mismatch",
            )

        current_time = self.now()
        webhook_status = str(payload.get("status", "")).lower()
        if webhook_status in {"success", "paid", "captured"}:
            intent.status = PaymentStatus.SUCCESS
            attempt_status = PaymentAttemptStatus.SUCCESS
        else:
            intent.status = PaymentStatus.FAILED
            attempt_status = PaymentAttemptStatus.FAILED

        intent.updated_at = current_time

        attempt = PaymentAttempt(
            payment_intent_id=intent.id,
            intent=intent,
            attempt_number=len(intent.attempts) + 1 if intent.attempts else 1,
            status=attempt_status,
            provider_reference=payload.get("provider_reference"),
            raw_payload=payload,
            created_at=current_time,
        )
        event = PaymentEvent(
            payment_intent_id=intent.id,
            intent=intent,
            event_type=f"webhook_{webhook_status}",
            data=payload,
            created_at=current_time,
        )
        self.session.add(attempt)
        self.session.add(event)
        await self.session.commit()

        await self.session.refresh(intent, ["attempts", "events"])
        return intent, False
