from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from ainza_restaurant.db.base import Base


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class AIConversationStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class AIMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class AIMessageStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    PENDING_CONFIRMATION = "pending_confirmation"
    FAILED = "failed"


class AIPendingConfirmationStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class AIConversation(Base):
    __tablename__ = "ai_conversations"
    __table_args__ = (
        Index("uq_ai_conversations_public_token", "public_token", unique=True),
        Index("ix_ai_conversations_session", "dining_session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dining_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dining_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    outlet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_outlets.id", ondelete="RESTRICT"), nullable=False
    )
    public_token: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[AIConversationStatus] = mapped_column(
        SAEnum(
            AIConversationStatus,
            name="ai_conversation_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=AIConversationStatus.ACTIVE,
        server_default=AIConversationStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    pending_recommendation_interaction_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )

    messages: Mapped[list[AIConversationMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    confirmations: Mapped[list[AIPendingToolConfirmation]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class AIConversationMessage(Base):
    __tablename__ = "ai_conversation_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "client_message_id", name="uq_ai_message_client_id"),
        UniqueConstraint("conversation_id", "sequence_number", name="uq_ai_message_sequence"),
        CheckConstraint("sequence_number >= 1", name="ck_ai_message_sequence"),
        Index("ix_ai_messages_conversation_sequence", "conversation_id", "sequence_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False
    )
    client_message_id: Mapped[str | None] = mapped_column(String(120))
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[AIMessageRole] = mapped_column(
        SAEnum(
            AIMessageRole,
            name="ai_message_role",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    status: Mapped[AIMessageStatus] = mapped_column(
        SAEnum(
            AIMessageStatus,
            name="ai_message_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=AIMessageStatus.COMPLETED,
        server_default=AIMessageStatus.COMPLETED.value,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    conversation: Mapped[AIConversation] = relationship(back_populates="messages")


class AIPendingToolConfirmation(Base):
    __tablename__ = "ai_pending_tool_confirmations"
    __table_args__ = (
        Index("uq_ai_pending_confirmation_token", "public_confirmation_token", unique=True),
        Index("ix_ai_pending_confirmation_conversation", "conversation_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    public_confirmation_token: Mapped[str] = mapped_column(String(96), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_conversation_messages.id", ondelete="SET NULL")
    )
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    validated_arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    confirmation_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[AIPendingConfirmationStatus] = mapped_column(
        SAEnum(
            AIPendingConfirmationStatus,
            name="ai_pending_confirmation_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=AIPendingConfirmationStatus.PENDING,
        server_default=AIPendingConfirmationStatus.PENDING.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversation: Mapped[AIConversation] = relationship(back_populates="confirmations")
