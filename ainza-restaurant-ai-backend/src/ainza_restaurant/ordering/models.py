from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
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
from ainza_restaurant.domain.enums import DiningOrderStatus, OfferType


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class DiningCart(Base):
    __tablename__ = "dining_carts"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_dining_carts_version"),
        Index("ix_dining_carts_session", "dining_session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dining_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dining_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    selected_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("offers.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list[CartItem]] = relationship(
        back_populates="cart", cascade="all, delete-orphan"
    )


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (
        CheckConstraint("quantity > 0 AND quantity <= 99", name="ck_cart_items_quantity"),
        Index("ix_cart_items_cart", "cart_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cart_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dining_carts.id", ondelete="CASCADE"), nullable=False
    )
    dish_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dishes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("dish_variants.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    customer_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    cart: Mapped[DiningCart] = relationship(back_populates="items")
    modifiers: Mapped[list[CartItemModifier]] = relationship(
        back_populates="cart_item", cascade="all, delete-orphan"
    )


class CartItemModifier(Base):
    __tablename__ = "cart_item_modifiers"
    __table_args__ = (
        UniqueConstraint("cart_item_id", "modifier_option_id", name="uq_cart_item_modifier_option"),
    )

    cart_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cart_items.id", ondelete="CASCADE"), primary_key=True
    )
    modifier_option_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("modifier_options.id", ondelete="RESTRICT"), primary_key=True
    )

    cart_item: Mapped[CartItem] = relationship(back_populates="modifiers")


class DiningOrder(Base):
    __tablename__ = "dining_orders"
    __table_args__ = (
        UniqueConstraint("dining_session_id", "round_number", name="uq_dining_orders_round"),
        UniqueConstraint(
            "dining_session_id", "idempotency_key", name="uq_dining_orders_idempotency"
        ),
        CheckConstraint("round_number >= 1", name="ck_dining_orders_round_number"),
        CheckConstraint(
            "subtotal_before_discount >= 0 AND discount_amount >= 0 "
            "AND subtotal_after_discount >= 0",
            name="ck_dining_orders_money",
        ),
        Index("ix_dining_orders_session", "dining_session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dining_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dining_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DiningOrderStatus] = mapped_column(
        SAEnum(
            DiningOrderStatus,
            name="dining_order_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=DiningOrderStatus.SUBMITTED,
        server_default=DiningOrderStatus.SUBMITTED.value,
    )
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal_before_discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    subtotal_after_discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    selected_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("offers.id", ondelete="SET NULL")
    )
    offer_name_snapshot: Mapped[str | None] = mapped_column(String(200))
    offer_type_snapshot: Mapped[OfferType | None] = mapped_column(
        SAEnum(OfferType, name="order_offer_type", native_enum=False, values_callable=_enum_values)
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    items: Mapped[list[DiningOrderItem]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class DiningOrderItem(Base):
    __tablename__ = "dining_order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_dining_order_items_quantity"),
        CheckConstraint(
            "catalog_unit_price_snapshot >= 0 AND modifier_unit_total_snapshot >= 0 "
            "AND configured_unit_price_snapshot >= 0 AND line_subtotal_snapshot >= 0",
            name="ck_dining_order_items_money",
        ),
        Index("ix_dining_order_items_order", "order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dining_orders.id", ondelete="CASCADE"), nullable=False
    )
    dish_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("dishes.id", ondelete="RESTRICT"))
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("dish_variants.id", ondelete="RESTRICT")
    )
    dish_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    variant_name_snapshot: Mapped[str | None] = mapped_column(String(150))
    quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    customer_note_snapshot: Mapped[str | None] = mapped_column(Text)
    catalog_unit_price_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    special_unit_price_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    effective_base_unit_price_snapshot: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    modifier_unit_total_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    configured_unit_price_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    line_subtotal_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_category_code_snapshot: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    order: Mapped[DiningOrder] = relationship(back_populates="items")
    modifiers: Mapped[list[DiningOrderItemModifier]] = relationship(
        back_populates="order_item", cascade="all, delete-orphan"
    )


class DiningOrderItemModifier(Base):
    __tablename__ = "dining_order_item_modifiers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dining_order_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    modifier_option_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("modifier_options.id", ondelete="SET NULL")
    )
    modifier_group_name_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    modifier_option_name_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    price_delta_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    order_item: Mapped[DiningOrderItem] = relationship(back_populates="modifiers")
