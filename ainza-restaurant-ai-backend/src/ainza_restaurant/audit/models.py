from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from ainza_restaurant.ai.context import AIActorType
from ainza_restaurant.db.base import Base
from ainza_restaurant.domain.enums import AuditActionType


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_outlet_created", "outlet_id", "created_at"),
        Index("ix_audit_logs_target", "target_type", "target_id"),
        Index("ix_audit_logs_action", "action_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    outlet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_outlets.id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    actor_type: Mapped[AIActorType] = mapped_column(
        SAEnum(
            AIActorType,
            name="audit_actor_type",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=AIActorType.OWNER,
    )
    action_type: Mapped[AuditActionType] = mapped_column(
        SAEnum(
            AuditActionType,
            name="audit_action_type",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(60), nullable=False)
    target_id: Mapped[str] = mapped_column(String(120), nullable=False)
    previous_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(60), nullable=False, default="api")
    confirmation_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
