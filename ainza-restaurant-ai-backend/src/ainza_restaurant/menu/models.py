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
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from ainza_restaurant.db.base import Base
from ainza_restaurant.domain.enums import (
    AllergenStatus,
    AvailabilityStatus,
    BadgeCode,
    DietaryClassification,
    DietaryStatus,
    HalalOverride,
    ImageApprovalStatus,
    ItemType,
    MenuStatus,
    ProvenanceSource,
    ReviewStatus,
    SpiceLevel,
)


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class Menu(Base):
    __tablename__ = "menus"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="ck_menus_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    outlet_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("restaurant_outlets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[MenuStatus] = mapped_column(
        SAEnum(MenuStatus, name="menu_status", native_enum=False, values_callable=_enum_values),
        default=MenuStatus.DRAFT,
        server_default=MenuStatus.DRAFT.value,
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    categories: Mapped[list[Category]] = relationship(
        back_populates="menu", cascade="all, delete-orphan"
    )
    dishes: Mapped[list[Dish]] = relationship(back_populates="menu", cascade="all, delete-orphan")
    cuisines: Mapped[list[MenuCuisine]] = relationship(
        back_populates="menu", cascade="all, delete-orphan"
    )


class Category(Base):
    __tablename__ = "menu_categories"
    __table_args__ = (
        UniqueConstraint("menu_id", "slug", name="uq_menu_categories_menu_slug"),
        CheckConstraint("length(trim(name)) > 0", name="ck_menu_categories_name"),
        CheckConstraint("display_order >= 0", name="ck_menu_categories_display_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    menu_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("menus.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    # Kept as a compatibility column for the original Task 003 API.
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    menu: Mapped[Menu] = relationship(back_populates="categories")
    dishes: Mapped[list[Dish]] = relationship(back_populates="category")


class Cuisine(Base):
    __tablename__ = "cuisines"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "slug", name="uq_cuisines_restaurant_slug"),
        UniqueConstraint("outlet_id", "slug", name="uq_cuisines_outlet_slug"),
        CheckConstraint("length(trim(name)) > 0", name="ck_cuisines_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    outlet_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_slug: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )


class MenuCuisine(Base):
    __tablename__ = "menu_cuisines"
    menu_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("menus.id", ondelete="CASCADE"), primary_key=True
    )
    cuisine_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cuisines.id", ondelete="CASCADE"), primary_key=True
    )
    menu: Mapped[Menu] = relationship(back_populates="cuisines")
    cuisine: Mapped[Cuisine] = relationship()


class DishCuisine(Base):
    __tablename__ = "dish_cuisines"
    dish_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dishes.id", ondelete="CASCADE"), primary_key=True
    )
    cuisine_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cuisines.id", ondelete="CASCADE"), primary_key=True
    )
    dish: Mapped[Dish] = relationship(back_populates="cuisines")
    cuisine: Mapped[Cuisine] = relationship()


class Ingredient(Base):
    __tablename__ = "ingredients"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "normalized_name", name="uq_ingredients_restaurant_name"),
        UniqueConstraint("outlet_id", "normalized_name", name="uq_ingredients_outlet_name"),
        CheckConstraint("length(trim(name)) > 0", name="ck_ingredients_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    outlet_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )


class Dish(Base):
    __tablename__ = "dishes"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_dishes_name"),
        CheckConstraint("base_price IS NULL OR base_price >= 0", name="ck_dishes_base_price"),
        CheckConstraint("serves_min IS NULL OR serves_min > 0", name="ck_dishes_serves_min"),
        CheckConstraint("serves_max IS NULL OR serves_max > 0", name="ck_dishes_serves_max"),
        CheckConstraint(
            "serves_min IS NULL OR serves_max IS NULL OR serves_max >= serves_min",
            name="ck_dishes_serves_order",
        ),
        CheckConstraint(
            "preparation_time_minutes IS NULL OR preparation_time_minutes > 0",
            name="ck_dishes_prep_time",
        ),
        CheckConstraint("display_order >= 0", name="ck_dishes_display_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    menu_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("menus.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("menu_categories.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    ingredient_description: Mapped[str | None] = mapped_column(Text)
    item_type: Mapped[ItemType] = mapped_column(
        SAEnum(ItemType, name="item_type", native_enum=False, values_callable=_enum_values),
        default=ItemType.FOOD,
        server_default=ItemType.FOOD.value,
        nullable=False,
    )
    dietary_classification: Mapped[DietaryClassification] = mapped_column(
        SAEnum(
            DietaryClassification,
            name="dietary_classification",
            native_enum=False,
            values_callable=_enum_values,
        ),
        default=DietaryClassification.UNKNOWN,
        server_default=DietaryClassification.UNKNOWN.value,
        nullable=False,
    )
    jain_status: Mapped[AvailabilityStatus] = mapped_column(
        SAEnum(
            AvailabilityStatus, name="jain_status", native_enum=False, values_callable=_enum_values
        ),
        default=AvailabilityStatus.UNKNOWN,
        server_default=AvailabilityStatus.UNKNOWN.value,
        nullable=False,
    )
    vegan_status: Mapped[AvailabilityStatus] = mapped_column(
        SAEnum(
            AvailabilityStatus, name="vegan_status", native_enum=False, values_callable=_enum_values
        ),
        default=AvailabilityStatus.UNKNOWN,
        server_default=AvailabilityStatus.UNKNOWN.value,
        nullable=False,
    )
    halal_status: Mapped[HalalOverride] = mapped_column(
        SAEnum(
            HalalOverride, name="dish_halal_status", native_enum=False, values_callable=_enum_values
        ),
        default=HalalOverride.UNKNOWN,
        server_default=HalalOverride.UNKNOWN.value,
        nullable=False,
    )
    spice_level: Mapped[SpiceLevel] = mapped_column(
        SAEnum(SpiceLevel, name="spice_level", native_enum=False, values_callable=_enum_values),
        default=SpiceLevel.UNKNOWN,
        server_default=SpiceLevel.UNKNOWN.value,
        nullable=False,
    )
    serves_min: Mapped[int | None] = mapped_column(SmallInteger)
    serves_max: Mapped[int | None] = mapped_column(SmallInteger)
    preparation_time_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    base_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(
        String(3), default="INR", server_default="INR", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    display_order: Mapped[int] = mapped_column(
        SmallInteger, default=0, server_default="0", nullable=False
    )
    allergen_information_status: Mapped[AllergenStatus] = mapped_column(
        SAEnum(
            AllergenStatus,
            name="allergen_information_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        default=AllergenStatus.UNKNOWN,
        server_default=AllergenStatus.UNKNOWN.value,
        nullable=False,
    )
    allergen_notes: Mapped[str | None] = mapped_column(Text)
    tax_category_code: Mapped[str | None] = mapped_column(String(50))
    catalog_source: Mapped[ProvenanceSource] = mapped_column(
        SAEnum(
            ProvenanceSource, name="catalog_source", native_enum=False, values_callable=_enum_values
        ),
        default=ProvenanceSource.MANUAL,
        server_default=ProvenanceSource.MANUAL.value,
        nullable=False,
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        SAEnum(
            ReviewStatus,
            name="catalog_review_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        default=ReviewStatus.PENDING_REVIEW,
        server_default=ReviewStatus.PENDING_REVIEW.value,
        nullable=False,
    )
    # Legacy columns retained so old clients can be migrated without data loss.
    allergen_status: Mapped[AllergenStatus] = mapped_column(
        SAEnum(
            AllergenStatus, name="allergen_status", native_enum=False, values_callable=_enum_values
        ),
        default=AllergenStatus.UNKNOWN,
        server_default=AllergenStatus.UNKNOWN.value,
        nullable=False,
    )
    halal_override: Mapped[HalalOverride] = mapped_column(
        SAEnum(
            HalalOverride, name="halal_override", native_enum=False, values_callable=_enum_values
        ),
        default=HalalOverride.UNKNOWN,
        server_default=HalalOverride.UNKNOWN.value,
        nullable=False,
    )
    provenance_source: Mapped[ProvenanceSource] = mapped_column(
        SAEnum(
            ProvenanceSource,
            name="provenance_source",
            native_enum=False,
            values_callable=_enum_values,
        ),
        default=ProvenanceSource.MANUAL,
        server_default=ProvenanceSource.MANUAL.value,
        nullable=False,
    )
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    menu: Mapped[Menu] = relationship(back_populates="dishes")
    category: Mapped[Category | None] = relationship(back_populates="dishes")
    variants: Mapped[list[DishVariant]] = relationship(
        back_populates="dish", cascade="all, delete-orphan"
    )
    ingredients: Mapped[list[DishIngredient]] = relationship(
        back_populates="dish", cascade="all, delete-orphan"
    )
    dietary_statuses: Mapped[list[DishDietaryStatus]] = relationship(
        back_populates="dish", cascade="all, delete-orphan"
    )
    badges: Mapped[list[DishBadge]] = relationship(
        back_populates="dish", cascade="all, delete-orphan"
    )
    images: Mapped[list[DishImage]] = relationship(
        back_populates="dish", cascade="all, delete-orphan"
    )
    modifier_groups: Mapped[list[ModifierGroup]] = relationship(
        back_populates="dish", cascade="all, delete-orphan"
    )
    cuisines: Mapped[list[DishCuisine]] = relationship(
        back_populates="dish", cascade="all, delete-orphan"
    )


class DishVariant(Base):
    __tablename__ = "dish_variants"
    __table_args__ = (
        UniqueConstraint("dish_id", "normalized_name", name="uq_dish_variants_dish_name"),
        CheckConstraint("price >= 0", name="ck_dish_variants_price"),
        CheckConstraint("display_order >= 0", name="ck_dish_variants_display_order"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dish_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(150), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    display_order: Mapped[int] = mapped_column(
        SmallInteger, default=0, server_default="0", nullable=False
    )
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, default=0, server_default="0", nullable=False
    )
    dish: Mapped[Dish] = relationship(back_populates="variants")


class DishIngredient(Base):
    __tablename__ = "dish_ingredients"
    dish_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dishes.id", ondelete="CASCADE"), primary_key=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True
    )
    is_required_for_availability: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(String(300))
    dish: Mapped[Dish] = relationship(back_populates="ingredients")
    ingredient: Mapped[Ingredient] = relationship()


class DishDietaryStatus(Base):
    __tablename__ = "dish_dietary_statuses"
    dish_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dishes.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[DietaryStatus] = mapped_column(
        SAEnum(
            DietaryStatus, name="dietary_status", native_enum=False, values_callable=_enum_values
        ),
        primary_key=True,
    )
    dish: Mapped[Dish] = relationship(back_populates="dietary_statuses")


class DishBadge(Base):
    __tablename__ = "dish_badges"
    dish_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dishes.id", ondelete="CASCADE"), primary_key=True
    )
    badge: Mapped[BadgeCode] = mapped_column(
        SAEnum(BadgeCode, name="badge_code", native_enum=False, values_callable=_enum_values),
        primary_key=True,
    )
    dish: Mapped[Dish] = relationship(back_populates="badges")


class DishImage(Base):
    __tablename__ = "dish_images"
    __table_args__ = (
        CheckConstraint(
            "storage_key IS NOT NULL OR source_url IS NOT NULL",
            name="ck_dish_images_location",
        ),
        Index(
            "uq_dish_images_primary_variant",
            "dish_id",
            "variant_id",
            unique=True,
            sqlite_where=text("is_primary = 1"),
            postgresql_where=text("is_primary"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dish_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("dish_variants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    storage_key: Mapped[str | None] = mapped_column(String(1000))
    source_url: Mapped[str | None] = mapped_column(String(2000))
    # Legacy URI accepted as a location until clients migrate.
    uri: Mapped[str | None] = mapped_column(String(1000))
    alt_text: Mapped[str | None] = mapped_column(String(300))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    width: Mapped[int | None] = mapped_column(SmallInteger)
    height: Mapped[int | None] = mapped_column(SmallInteger)
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, default=0, server_default="0", nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    approval_status: Mapped[ImageApprovalStatus] = mapped_column(
        SAEnum(
            ImageApprovalStatus,
            name="image_approval_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        default=ImageApprovalStatus.PENDING,
        server_default=ImageApprovalStatus.PENDING.value,
        nullable=False,
    )
    catalog_source: Mapped[ProvenanceSource] = mapped_column(
        SAEnum(
            ProvenanceSource,
            name="image_catalog_source",
            native_enum=False,
            values_callable=_enum_values,
        ),
        default=ProvenanceSource.MANUAL,
        server_default=ProvenanceSource.MANUAL.value,
        nullable=False,
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        SAEnum(
            ReviewStatus,
            name="image_review_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        default=ReviewStatus.CONFIRMED,
        server_default=ReviewStatus.CONFIRMED.value,
        nullable=False,
    )
    dish: Mapped[Dish] = relationship(back_populates="images")


class ModifierGroup(Base):
    __tablename__ = "modifier_groups"
    __table_args__ = (
        CheckConstraint("min_selections >= 0", name="ck_modifier_groups_min"),
        CheckConstraint("max_selections >= 1", name="ck_modifier_groups_max_positive"),
        CheckConstraint("max_selections >= min_selections", name="ck_modifier_groups_max"),
        CheckConstraint("display_order >= 0", name="ck_modifier_groups_display_order"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dish_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    is_required: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    min_selections: Mapped[int] = mapped_column(
        SmallInteger, default=0, server_default="0", nullable=False
    )
    max_selections: Mapped[int] = mapped_column(
        SmallInteger, default=1, server_default="1", nullable=False
    )
    display_order: Mapped[int] = mapped_column(
        SmallInteger, default=0, server_default="0", nullable=False
    )
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, default=0, server_default="0", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    dish: Mapped[Dish] = relationship(back_populates="modifier_groups")
    options: Mapped[list[ModifierOption]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class ModifierOption(Base):
    __tablename__ = "modifier_options"
    __table_args__ = (
        CheckConstraint("display_order >= 0", name="ck_modifier_options_display_order"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("modifier_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    price_delta: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    display_order: Mapped[int] = mapped_column(
        SmallInteger, default=0, server_default="0", nullable=False
    )
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, default=0, server_default="0", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    group: Mapped[ModifierGroup] = relationship(back_populates="options")
