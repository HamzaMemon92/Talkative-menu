from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from ainza_restaurant.db.base import Base
from ainza_restaurant.domain.enums import PaymentAttemptStatus, PaymentMode, PaymentStatus


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class PaymentIntent(Base):
    __tablename__ = "payment_intents"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_payment_intents_amount"),
        UniqueConstraint(
            "dining_session_id", "idempotency_key", name="uq_payment_intents_session_idempotency"
        ),
        Index("ix_payment_intents_session", "dining_session_id"),
        Index("ix_payment_intents_invoice", "invoice_id"),
        Index("ix_payment_intents_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    outlet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_outlets.id", ondelete="RESTRICT"), nullable=False
    )
    dining_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dining_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dining_invoices.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(
            PaymentStatus,
            name="payment_intent_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=PaymentStatus.PENDING,
        server_default=PaymentStatus.PENDING.value,
    )
    payment_mode: Mapped[PaymentMode] = mapped_column(
        SAEnum(
            PaymentMode,
            name="payment_intent_mode",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="fake")
    provider_intent_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    qr_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    attempts: Mapped[list[PaymentAttempt]] = relationship(
        back_populates="intent",
        cascade="all, delete-orphan",
        order_by="PaymentAttempt.attempt_number",
        lazy="selectin",
    )
    events: Mapped[list[PaymentEvent]] = relationship(
        back_populates="intent",
        cascade="all, delete-orphan",
        order_by="PaymentEvent.created_at",
        lazy="selectin",
    )


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (Index("ix_payment_attempts_intent", "payment_intent_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    payment_intent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("payment_intents.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[PaymentAttemptStatus] = mapped_column(
        SAEnum(
            PaymentAttemptStatus,
            name="payment_attempt_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=PaymentAttemptStatus.INITIATED,
    )
    provider_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    intent: Mapped[PaymentIntent] = relationship(back_populates="attempts")


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    __table_args__ = (Index("ix_payment_events_intent", "payment_intent_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    payment_intent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("payment_intents.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    intent: Mapped[PaymentIntent] = relationship(back_populates="events")
