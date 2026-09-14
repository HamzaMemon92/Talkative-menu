from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from ainza_restaurant.db.base import Base
from ainza_restaurant.domain.enums import KitchenTicketItemStatus, KitchenTicketStatus
from ainza_restaurant.ordering.models import DiningOrder, DiningOrderItem


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class KitchenTicket(Base):
    __tablename__ = "kitchen_tickets"
    __table_args__ = (
        CheckConstraint("length(trim(table_label_snapshot)) > 0", name="ck_kitchen_table_label"),
        UniqueConstraint("dining_order_id", name="uq_kitchen_tickets_order"),
        Index("ix_kitchen_tickets_outlet_status_created", "outlet_id", "status", "created_at"),
        Index("ix_kitchen_tickets_order", "dining_order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    outlet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False
    )
    dining_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dining_orders.id", ondelete="CASCADE"), nullable=False
    )
    table_label_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[KitchenTicketStatus] = mapped_column(
        SAEnum(
            KitchenTicketStatus,
            name="kitchen_ticket_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=KitchenTicketStatus.QUEUED,
        server_default=KitchenTicketStatus.QUEUED.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    served_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    order: Mapped[DiningOrder] = relationship()
    items: Mapped[list[KitchenTicketItem]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )


class KitchenTicketItem(Base):
    __tablename__ = "kitchen_ticket_items"
    __table_args__ = (
        UniqueConstraint("dining_order_item_id", name="uq_kitchen_ticket_items_order_item"),
        Index("ix_kitchen_ticket_items_ticket", "kitchen_ticket_id"),
        Index("ix_kitchen_ticket_items_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kitchen_ticket_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_tickets.id", ondelete="CASCADE"), nullable=False
    )
    dining_order_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dining_order_items.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[KitchenTicketItemStatus] = mapped_column(
        SAEnum(
            KitchenTicketItemStatus,
            name="kitchen_ticket_item_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=KitchenTicketItemStatus.QUEUED,
        server_default=KitchenTicketItemStatus.QUEUED.value,
    )
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    served_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    ticket: Mapped[KitchenTicket] = relationship(back_populates="items")
    order_item: Mapped[DiningOrderItem] = relationship()
