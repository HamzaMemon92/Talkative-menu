from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from ainza_restaurant.db.base import Base
from ainza_restaurant.domain.enums import DiningInvoiceStatus, RestaurantType


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class DiningInvoice(Base):
    __tablename__ = "dining_invoices"
    __table_args__ = (
        CheckConstraint(
            "subtotal_before_discount >= 0 AND discount_total >= 0 "
            "AND subtotal_after_discount >= 0 AND taxable_amount >= 0 "
            "AND tax_amount >= 0 AND invoice_total >= 0",
            name="ck_dining_invoices_money",
        ),
        CheckConstraint(
            "tax_rate_snapshot >= 0 AND tax_rate_snapshot <= 100",
            name="ck_dining_invoices_tax_rate",
        ),
        UniqueConstraint("dining_session_id", name="uq_dining_invoices_session"),
        UniqueConstraint(
            "dining_session_id", "idempotency_key", name="uq_dining_invoices_idempotency"
        ),
        Index("ix_dining_invoices_outlet_created", "outlet_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dining_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dining_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    outlet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_outlets.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_reference: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    status: Mapped[DiningInvoiceStatus] = mapped_column(
        SAEnum(
            DiningInvoiceStatus,
            name="dining_invoice_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=DiningInvoiceStatus.FINALIZED,
        server_default=DiningInvoiceStatus.FINALIZED.value,
    )
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal_before_discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    subtotal_after_discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_rate_snapshot: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    prices_include_tax_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    invoice_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    restaurant_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    outlet_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_business_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    restaurant_type_snapshot: Mapped[RestaurantType] = mapped_column(
        SAEnum(
            RestaurantType,
            name="invoice_restaurant_type",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    gst_registered_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False)
    gstin_snapshot: Mapped[str | None] = mapped_column(String(15))
    state_snapshot: Mapped[str | None] = mapped_column(String(100))
    country_code_snapshot: Mapped[str] = mapped_column(String(2), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    finalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    orders: Mapped[list[DiningInvoiceOrder]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    lines: Mapped[list[DiningInvoiceLine]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class DiningInvoiceOrder(Base):
    __tablename__ = "dining_invoice_orders"
    __table_args__ = (
        UniqueConstraint("invoice_id", "dining_order_id", name="uq_invoice_order_order"),
        Index("ix_dining_invoice_orders_invoice", "invoice_id"),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dining_invoices.id", ondelete="CASCADE"), primary_key=True
    )
    dining_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dining_orders.id", ondelete="RESTRICT"), primary_key=True
    )
    round_number_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)

    invoice: Mapped[DiningInvoice] = relationship(back_populates="orders")


class DiningInvoiceLine(Base):
    __tablename__ = "dining_invoice_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_dining_invoice_lines_quantity"),
        CheckConstraint(
            "configured_unit_price_snapshot >= 0 AND line_subtotal_snapshot >= 0",
            name="ck_dining_invoice_lines_money",
        ),
        Index("ix_dining_invoice_lines_invoice", "invoice_id", "display_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dining_invoices.id", ondelete="CASCADE"), nullable=False
    )
    dining_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dining_orders.id", ondelete="RESTRICT"), nullable=False
    )
    dining_order_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("dining_order_items.id", ondelete="SET NULL")
    )
    round_number_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    dish_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    variant_name_snapshot: Mapped[str | None] = mapped_column(String(150))
    quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    configured_unit_price_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    line_subtotal_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    customer_note_snapshot: Mapped[str | None] = mapped_column(Text)
    tax_category_code_snapshot: Mapped[str | None] = mapped_column(String(50))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    invoice: Mapped[DiningInvoice] = relationship(back_populates="lines")
    modifiers: Mapped[list[DiningInvoiceLineModifier]] = relationship(
        back_populates="invoice_line", cascade="all, delete-orphan"
    )


class DiningInvoiceLineModifier(Base):
    __tablename__ = "dining_invoice_line_modifiers"
    __table_args__ = (Index("ix_dining_invoice_line_modifiers_line", "invoice_line_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    invoice_line_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dining_invoice_lines.id", ondelete="CASCADE"), nullable=False
    )
    modifier_option_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    modifier_group_name_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    modifier_option_name_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    price_delta_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    invoice_line: Mapped[DiningInvoiceLine] = relationship(back_populates="modifiers")
