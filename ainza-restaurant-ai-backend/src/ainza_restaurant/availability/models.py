from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from ainza_restaurant.db.base import Base
from ainza_restaurant.domain.enums import (
    AvailabilityAction,
    AvailabilityDurationMode,
    AvailabilityProposalStatus,
    AvailabilityReasonCode,
    AvailabilityTargetType,
)


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class AvailabilityProposal(Base):
    __tablename__ = "availability_proposals"
    __table_args__ = (
        CheckConstraint("target_id IS NOT NULL", name="ck_availability_proposals_target_id"),
        CheckConstraint(
            "(action = 'restore' AND duration_mode IS NULL) "
            "OR (action = 'mark_unavailable' AND duration_mode IS NOT NULL)",
            name="ck_availability_proposals_action_duration",
        ),
        Index("ix_availability_proposals_outlet_status", "outlet_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    outlet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type: Mapped[AvailabilityTargetType] = mapped_column(
        SAEnum(
            AvailabilityTargetType,
            name="availability_target_type",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    action: Mapped[AvailabilityAction] = mapped_column(
        SAEnum(
            AvailabilityAction,
            name="availability_action",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    duration_mode: Mapped[AvailabilityDurationMode | None] = mapped_column(
        SAEnum(
            AvailabilityDurationMode,
            name="availability_duration_mode",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=True,
    )
    requested_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    computed_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason_code: Mapped[AvailabilityReasonCode | None] = mapped_column(
        SAEnum(
            AvailabilityReasonCode,
            name="availability_reason_code",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=True,
    )
    reason_note: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[AvailabilityProposalStatus] = mapped_column(
        SAEnum(
            AvailabilityProposalStatus,
            name="availability_proposal_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        default=AvailabilityProposalStatus.PENDING,
        server_default=AvailabilityProposalStatus.PENDING.value,
        nullable=False,
    )
    proposal_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    affected_dishes: Mapped[list[AvailabilityProposalAffectedDish]] = relationship(
        back_populates="proposal", cascade="all, delete-orphan"
    )


class AvailabilityProposalAffectedDish(Base):
    __tablename__ = "availability_proposal_affected_dishes"

    proposal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("availability_proposals.id", ondelete="CASCADE"),
        primary_key=True,
    )
    dish_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dishes.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    proposal: Mapped[AvailabilityProposal] = relationship(back_populates="affected_dishes")


class DishAvailabilityOverride(Base):
    __tablename__ = "dish_availability_overrides"
    __table_args__ = (
        Index("ix_dish_availability_overrides_dish_active", "dish_id", "revoked_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dish_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason_code: Mapped[AvailabilityReasonCode] = mapped_column(
        SAEnum(
            AvailabilityReasonCode,
            name="dish_availability_reason_code",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    reason_note: Mapped[str | None] = mapped_column(String(1000))
    source_proposal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("availability_proposals.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IngredientAvailabilityOverride(Base):
    __tablename__ = "ingredient_availability_overrides"
    __table_args__ = (
        Index(
            "ix_ingredient_availability_overrides_active",
            "ingredient_id",
            "revoked_at",
            "expires_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason_code: Mapped[AvailabilityReasonCode] = mapped_column(
        SAEnum(
            AvailabilityReasonCode,
            name="ingredient_availability_reason_code",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    reason_note: Mapped[str | None] = mapped_column(String(1000))
    source_proposal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("availability_proposals.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
