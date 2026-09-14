from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ainza_restaurant.domain.enums import PaymentMode, PaymentStatus


class PaymentIntentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_mode: PaymentMode = PaymentMode.ONLINE
    idempotency_key: str | None = Field(default=None, max_length=120)


class PaymentIntentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    outlet_id: UUID
    dining_session_id: UUID
    invoice_id: UUID
    amount: Decimal
    currency_code: str
    status: PaymentStatus
    payment_mode: PaymentMode
    provider: str
    provider_intent_reference: str | None = None
    idempotency_key: str
    qr_payload: str | None = None
    checkout_url: str | None = None
    expires_at: datetime
    created_at: datetime


class ManualPaymentConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str | None = Field(default=None, max_length=500)
    staff_actor_id: str = Field(default="staff_terminal_1", min_length=1, max_length=120)


class PaymentWebhookResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    status: str
    payment_intent_id: str
    duplicate: bool = False
