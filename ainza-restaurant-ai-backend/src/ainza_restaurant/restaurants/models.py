from __future__ import annotations

import uuid
from datetime import datetime, time
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
    Time,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from ainza_restaurant.db.base import Base
from ainza_restaurant.domain.enums import (
    AlcoholPolicy,
    HalalCertificationStatus,
    HalalPolicy,
    HalalStatus,
    OnboardingStatus,
    PorkPolicy,
    RestaurantStatus,
    RestaurantType,
)


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class Restaurant(Base):
    __tablename__ = "restaurants"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_restaurants_name"),
        CheckConstraint("length(trim(slug)) > 0", name="ck_restaurants_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), nullable=False, unique=True, index=True)
    legal_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[RestaurantStatus] = mapped_column(
        SAEnum(
            RestaurantStatus,
            name="restaurant_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=RestaurantStatus.ACTIVE,
        server_default=RestaurantStatus.ACTIVE.value,
    )
    onboarding_status: Mapped[OnboardingStatus] = mapped_column(
        SAEnum(
            OnboardingStatus,
            name="onboarding_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=OnboardingStatus.DRAFT,
        server_default=OnboardingStatus.DRAFT.value,
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    outlets: Mapped[list[RestaurantOutlet]] = relationship(
        back_populates="restaurant", cascade="all, delete-orphan"
    )


class RestaurantOutlet(Base):
    __tablename__ = "restaurant_outlets"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_restaurant_outlets_name"),
        CheckConstraint(
            "length(country) = 2 AND country = upper(country)", name="ck_outlets_country"
        ),
        CheckConstraint(
            "length(currency_code) = 3 AND currency_code = upper(currency_code)",
            name="ck_outlets_currency_code",
        ),
        Index(
            "uq_restaurant_outlets_primary",
            "restaurant_id",
            unique=True,
            sqlite_where=text("is_primary = 1"),
            postgresql_where=text("is_primary"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address_line1: Mapped[str] = mapped_column(String(250), nullable=False)
    address_line2: Mapped[str | None] = mapped_column(String(250), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    country: Mapped[str] = mapped_column(
        String(2), nullable=False, default="IN", server_default="IN"
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Asia/Kolkata", server_default="Asia/Kolkata"
    )
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False, default="INR", server_default="INR"
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    restaurant: Mapped[Restaurant] = relationship(back_populates="outlets")
    operating_intervals: Mapped[list[WeeklyOperatingInterval]] = relationship(
        back_populates="outlet", cascade="all, delete-orphan"
    )
    tax_profile: Mapped[OutletTaxProfile | None] = relationship(
        back_populates="outlet", cascade="all, delete-orphan", uselist=False
    )
    food_policy: Mapped[OutletFoodPolicy | None] = relationship(
        back_populates="outlet", cascade="all, delete-orphan", uselist=False
    )


class WeeklyOperatingInterval(Base):
    __tablename__ = "weekly_operating_intervals"
    __table_args__ = (
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_operating_intervals_weekday"),
        CheckConstraint(
            "(is_full_day IS TRUE AND opens_at IS NULL AND closes_at IS NULL) "
            "OR (is_full_day IS FALSE AND opens_at IS NOT NULL AND closes_at IS NOT NULL "
            "AND opens_at <> closes_at)",
            name="ck_operating_intervals_shape",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    outlet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    opens_at: Mapped[time | None] = mapped_column(Time, nullable=True)
    closes_at: Mapped[time | None] = mapped_column(Time, nullable=True)
    is_full_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    outlet: Mapped[RestaurantOutlet] = relationship(back_populates="operating_intervals")


class OutletTaxProfile(Base):
    __tablename__ = "outlet_tax_profiles"
    __table_args__ = (
        CheckConstraint(
            "configured_tax_rate_percent IS NULL OR "
            "(configured_tax_rate_percent >= 0 AND configured_tax_rate_percent <= 100)",
            name="ck_tax_profiles_rate_range",
        ),
        CheckConstraint(
            "gst_state_code IS NULL OR length(gst_state_code) = 2",
            name="ck_tax_profiles_state_code",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    outlet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    legal_business_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    restaurant_type: Mapped[RestaurantType | None] = mapped_column(
        SAEnum(
            RestaurantType,
            name="restaurant_type",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=True,
    )
    gst_registered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    gst_state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    gstin_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    configured_tax_rate_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    prices_include_tax: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tax_configuration_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Retained for compatibility with the first Task 002 API. They are not tax rates.
    no_auto_tax_rates_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    tax_rates_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    outlet: Mapped[RestaurantOutlet] = relationship(back_populates="tax_profile")


class OutletFoodPolicy(Base):
    __tablename__ = "outlet_food_policies"
    __table_args__ = (
        CheckConstraint("confirmation IN (0, 1)", name="ck_outlet_food_policies_confirmation"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    outlet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    halal_status: Mapped[HalalStatus] = mapped_column(
        SAEnum(
            HalalStatus,
            name="halal_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=HalalStatus.UNKNOWN,
        server_default=HalalStatus.UNKNOWN.value,
    )
    halal_policy: Mapped[HalalPolicy] = mapped_column(
        SAEnum(
            HalalPolicy,
            name="halal_policy",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=HalalPolicy.UNKNOWN,
        server_default=HalalPolicy.UNKNOWN.value,
    )
    halal_certification_status: Mapped[HalalCertificationStatus] = mapped_column(
        SAEnum(
            HalalCertificationStatus,
            name="halal_certification_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=HalalCertificationStatus.UNKNOWN,
        server_default=HalalCertificationStatus.UNKNOWN.value,
    )
    halal_certificate_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pork_policy: Mapped[PorkPolicy] = mapped_column(
        SAEnum(
            PorkPolicy,
            name="pork_policy",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=PorkPolicy.UNKNOWN,
        server_default=PorkPolicy.UNKNOWN.value,
    )
    alcohol_policy: Mapped[AlcoholPolicy] = mapped_column(
        SAEnum(
            AlcoholPolicy,
            name="alcohol_policy",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=AlcoholPolicy.UNKNOWN,
        server_default=AlcoholPolicy.UNKNOWN.value,
    )
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    information_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    confirmation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    outlet: Mapped[RestaurantOutlet] = relationship(back_populates="food_policy")
