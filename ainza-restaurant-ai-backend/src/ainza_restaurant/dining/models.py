from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from ainza_restaurant.db.base import Base
from ainza_restaurant.domain.enums import DiningSessionStartedVia, DiningSessionStatus


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class RestaurantTable(Base):
    __tablename__ = "restaurant_tables"
    __table_args__ = (
        CheckConstraint("length(trim(label)) > 0", name="ck_restaurant_tables_label"),
        CheckConstraint("capacity IS NULL OR capacity > 0", name="ck_restaurant_tables_capacity"),
        CheckConstraint("display_order >= 0", name="ck_restaurant_tables_display_order"),
        Index(
            "uq_restaurant_tables_outlet_active_label",
            "outlet_id",
            "normalized_label",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active"),
        ),
        Index("uq_restaurant_tables_public_qr_code", "public_qr_code", unique=True),
        Index("ix_restaurant_tables_outlet_order", "outlet_id", "display_order", "label"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    outlet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_label: Mapped[str] = mapped_column(String(120), nullable=False)
    area_name: Mapped[str | None] = mapped_column(String(120))
    capacity: Mapped[int | None] = mapped_column(SmallInteger)
    display_order: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    public_qr_code: Mapped[str] = mapped_column(String(96), nullable=False)
    qr_code_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    dining_sessions: Mapped[list[DiningSession]] = relationship(
        back_populates="table", cascade="all, delete-orphan"
    )


class DiningSession(Base):
    __tablename__ = "dining_sessions"
    __table_args__ = (
        CheckConstraint(
            "party_size IS NULL OR party_size > 0", name="ck_dining_sessions_party_size"
        ),
        CheckConstraint(
            "(status = 'open' AND closed_at IS NULL) OR "
            "(status = 'closed' AND closed_at IS NOT NULL)",
            name="ck_dining_sessions_status_closed_at",
        ),
        Index("uq_dining_sessions_public_session_token", "public_session_token", unique=True),
        Index(
            "uq_dining_sessions_one_open_per_table",
            "table_id",
            unique=True,
            sqlite_where=text("status = 'open'"),
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_dining_sessions_table_status", "table_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    table_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_tables.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    public_session_token: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[DiningSessionStatus] = mapped_column(
        SAEnum(
            DiningSessionStatus,
            name="dining_session_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=DiningSessionStatus.OPEN,
        server_default=DiningSessionStatus.OPEN.value,
    )
    party_size: Mapped[int | None] = mapped_column(SmallInteger)
    started_via: Mapped[DiningSessionStartedVia] = mapped_column(
        SAEnum(
            DiningSessionStartedVia,
            name="dining_session_started_via",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    table: Mapped[RestaurantTable] = relationship(back_populates="dining_sessions")
