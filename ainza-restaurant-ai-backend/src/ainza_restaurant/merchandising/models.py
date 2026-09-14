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
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from ainza_restaurant.db.base import Base
from ainza_restaurant.domain.enums import (
    MerchandisingStatus,
    OfferScopeType,
    OfferType,
)


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class TodaysSpecial(Base):
    __tablename__ = "todays_specials"
    __table_args__ = (
        CheckConstraint("special_price IS NULL OR special_price >= 0", name="ck_special_price"),
        CheckConstraint("ends_at > starts_at", name="ck_special_schedule"),
        Index("ix_todays_specials_outlet_status", "outlet_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    outlet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dish_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("dish_variants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    special_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[MerchandisingStatus] = mapped_column(
        SAEnum(
            MerchandisingStatus,
            name="merchandising_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=MerchandisingStatus.DRAFT,
        server_default=MerchandisingStatus.DRAFT.value,
    )
    activation_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    display_note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FeaturedDish(Base):
    __tablename__ = "featured_dishes"
    __table_args__ = (
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ck_featured_schedule"),
        CheckConstraint("display_order >= 0", name="ck_featured_display_order"),
        Index("ix_featured_dishes_outlet_status", "outlet_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    outlet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dish_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[MerchandisingStatus] = mapped_column(
        SAEnum(
            MerchandisingStatus,
            name="featured_dish_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=MerchandisingStatus.DRAFT,
        server_default=MerchandisingStatus.DRAFT.value,
    )
    display_order: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    activation_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_offers_name"),
        CheckConstraint("ends_at > starts_at", name="ck_offers_schedule"),
        CheckConstraint(
            "minimum_subtotal IS NULL OR minimum_subtotal >= 0",
            name="ck_offers_minimum_subtotal",
        ),
        CheckConstraint(
            "discount_value IS NULL OR discount_value >= 0", name="ck_offers_discount_value"
        ),
        CheckConstraint(
            "maximum_discount IS NULL OR maximum_discount >= 0",
            name="ck_offers_maximum_discount",
        ),
        CheckConstraint("combo_price IS NULL OR combo_price >= 0", name="ck_offers_combo_price"),
        Index("ix_offers_outlet_status", "outlet_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    outlet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    offer_type: Mapped[OfferType] = mapped_column(
        SAEnum(OfferType, name="offer_type", native_enum=False, values_callable=_enum_values),
        nullable=False,
    )
    scope_type: Mapped[OfferScopeType] = mapped_column(
        SAEnum(
            OfferScopeType,
            name="offer_scope_type",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=OfferScopeType.ALL_ITEMS,
        server_default=OfferScopeType.ALL_ITEMS.value,
    )
    status: Mapped[MerchandisingStatus] = mapped_column(
        SAEnum(
            MerchandisingStatus,
            name="offer_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=MerchandisingStatus.DRAFT,
        server_default=MerchandisingStatus.DRAFT.value,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    minimum_subtotal: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    discount_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    maximum_discount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    combo_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    activation_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OfferDishScope(Base):
    __tablename__ = "offer_dish_scopes"

    offer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("offers.id", ondelete="CASCADE"), primary_key=True
    )
    dish_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dishes.id", ondelete="CASCADE"), primary_key=True
    )


class OfferCategoryScope(Base):
    __tablename__ = "offer_category_scopes"

    offer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("offers.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("menu_categories.id", ondelete="CASCADE"), primary_key=True
    )


class OfferComboItem(Base):
    __tablename__ = "offer_combo_items"
    __table_args__ = (
        CheckConstraint("required_quantity >= 1", name="ck_combo_items_required_quantity"),
        UniqueConstraint("offer_id", "dish_id", "variant_id", name="uq_offer_combo_items_target"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    offer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("offers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dish_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("dish_variants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    required_quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
