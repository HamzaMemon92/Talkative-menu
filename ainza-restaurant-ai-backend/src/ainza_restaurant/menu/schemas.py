from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


def _text(value: str, field: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field} must not be blank")
    return value


class MenuCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    outlet_id: UUID | None = None

    @model_validator(mode="after")
    def normalize(self) -> MenuCreate:
        self.name = _text(self.name, "name")
        return self


class MenuPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None

    @model_validator(mode="after")
    def normalize(self) -> MenuPatch:
        if self.name is not None:
            self.name = _text(self.name, "name")
        return self


class MenuRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    restaurant_id: UUID
    outlet_id: UUID | None
    name: str
    description: str | None
    status: MenuStatus
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    slug: str | None = Field(default=None, max_length=180)
    description: str | None = None
    display_order: int = Field(default=0, ge=0)
    # Legacy spelling.
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool = True

    @model_validator(mode="after")
    def normalize(self) -> CategoryCreate:
        self.name = _text(self.name, "name")
        self.slug = self.slug.strip().lower() if self.slug else self.name
        self.display_order = self.sort_order if self.sort_order is not None else self.display_order
        return self


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    slug: str | None = Field(default=None, max_length=180)
    description: str | None = None
    display_order: int | None = Field(default=None, ge=0)
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @model_validator(mode="after")
    def normalize(self) -> CategoryPatch:
        if self.name is not None:
            self.name = _text(self.name, "name")
        if self.slug is not None:
            self.slug = self.slug.strip().lower()
        if self.display_order is None:
            self.display_order = self.sort_order
        return self


class CategoryRead(CategoryCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    menu_id: UUID
    slug: str
    display_order: int
    is_active: bool


class CuisineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str | None = Field(default=None, max_length=120)
    is_active: bool = True

    @model_validator(mode="after")
    def normalize(self) -> CuisineCreate:
        self.name = _text(self.name, "name")
        self.slug = (self.slug or self.name).strip().lower()
        return self


class CuisinePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    slug: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None


class CuisineRead(CuisineCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    restaurant_id: UUID
    outlet_id: UUID | None
    slug: str


class IngredientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def normalize(self) -> IngredientCreate:
        self.name = _text(self.name, "name")
        return self


class IngredientPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None
    is_active: bool | None = None


class IngredientRead(IngredientCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    restaurant_id: UUID
    outlet_id: UUID | None
    normalized_name: str


class VariantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    price: Decimal = Field(ge=0, decimal_places=2)
    is_active: bool = True
    display_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def normalize(self) -> VariantCreate:
        self.name = _text(self.name, "name")
        return self


class VariantPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    is_active: bool | None = None
    display_order: int | None = Field(default=None, ge=0)


class VariantRead(VariantCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    dish_id: UUID
    normalized_name: str


class DishIngredientInput(BaseModel):
    ingredient_id: UUID
    is_required_for_availability: bool = False
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=300)


class DishIngredientRead(DishIngredientInput):
    model_config = ConfigDict(from_attributes=True)
    dish_id: UUID
    ingredient: IngredientRead


class DishCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    ingredient_description: str | None = None
    category_id: UUID | None = None
    item_type: ItemType = ItemType.FOOD
    dietary_classification: DietaryClassification = DietaryClassification.UNKNOWN
    jain_status: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    vegan_status: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    halal_status: HalalOverride = HalalOverride.UNKNOWN
    spice_level: SpiceLevel = SpiceLevel.UNKNOWN
    serves_min: int | None = Field(default=None, gt=0)
    serves_max: int | None = Field(default=None, gt=0)
    preparation_time_minutes: int | None = Field(default=None, gt=0)
    base_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    is_active: bool = True
    display_order: int = Field(default=0, ge=0)
    allergen_information_status: AllergenStatus = AllergenStatus.UNKNOWN
    allergen_notes: str | None = None
    tax_category_code: str | None = Field(default=None, max_length=50)
    catalog_source: ProvenanceSource = ProvenanceSource.MANUAL
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW
    variants: list[VariantCreate] = Field(default_factory=list)
    ingredient_ids: list[UUID] = Field(default_factory=list)
    dietary_statuses: list[DietaryStatus] = Field(default_factory=list)
    badges: list[BadgeCode] = Field(default_factory=list)
    # Initial API compatibility.
    allergen_status: AllergenStatus | None = None
    halal_override: HalalOverride | None = None
    provenance_source: ProvenanceSource | None = None

    @model_validator(mode="after")
    def normalize(self) -> DishCreate:
        self.name = _text(self.name, "name")
        self.currency = self.currency.strip().upper()
        if self.allergen_status is not None:
            self.allergen_information_status = self.allergen_status
        if self.halal_override is not None:
            self.halal_status = self.halal_override
        if self.provenance_source is not None:
            self.catalog_source = self.provenance_source
        if (
            self.serves_min is not None
            and self.serves_max is not None
            and self.serves_max < self.serves_min
        ):
            raise ValueError("serves_max must be at least serves_min")
        if len(set(self.ingredient_ids)) != len(self.ingredient_ids):
            raise ValueError("ingredient_ids must not contain duplicates")
        if len(set(self.dietary_statuses)) != len(self.dietary_statuses):
            raise ValueError("dietary_statuses must not contain duplicates")
        if len(set(self.badges)) != len(self.badges):
            raise ValueError("badges must not contain duplicates")
        return self


class DishPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    ingredient_description: str | None = None
    category_id: UUID | None = None
    item_type: ItemType | None = None
    dietary_classification: DietaryClassification | None = None
    jain_status: AvailabilityStatus | None = None
    vegan_status: AvailabilityStatus | None = None
    halal_status: HalalOverride | None = None
    spice_level: SpiceLevel | None = None
    serves_min: int | None = Field(default=None, gt=0)
    serves_max: int | None = Field(default=None, gt=0)
    preparation_time_minutes: int | None = Field(default=None, gt=0)
    base_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    is_active: bool | None = None
    display_order: int | None = Field(default=None, ge=0)
    allergen_information_status: AllergenStatus | None = None
    allergen_notes: str | None = None
    tax_category_code: str | None = Field(default=None, max_length=50)
    catalog_source: ProvenanceSource | None = None
    review_status: ReviewStatus | None = None
    review_note: str | None = None
    # Legacy patch names.
    allergen_status: AllergenStatus | None = None
    halal_override: HalalOverride | None = None
    provenance_source: ProvenanceSource | None = None

    @model_validator(mode="after")
    def normalize(self) -> DishPatch:
        if self.name is not None:
            self.name = _text(self.name, "name")
        if self.currency is not None:
            self.currency = self.currency.strip().upper()
        if self.allergen_status is not None:
            self.allergen_information_status = self.allergen_status
        if self.halal_override is not None:
            self.halal_status = self.halal_override
        if self.provenance_source is not None:
            self.catalog_source = self.provenance_source
        if (
            self.serves_min is not None
            and self.serves_max is not None
            and self.serves_max < self.serves_min
        ):
            raise ValueError("serves_max must be at least serves_min")
        return self


class DishRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    menu_id: UUID
    category_id: UUID | None
    name: str
    description: str | None
    ingredient_description: str | None
    item_type: ItemType
    dietary_classification: DietaryClassification
    jain_status: AvailabilityStatus
    vegan_status: AvailabilityStatus
    halal_status: HalalOverride
    spice_level: SpiceLevel
    serves_min: int | None
    serves_max: int | None
    preparation_time_minutes: int | None
    base_price: Decimal | None
    currency: str
    is_active: bool
    display_order: int
    allergen_information_status: AllergenStatus
    allergen_notes: str | None
    tax_category_code: str | None
    catalog_source: ProvenanceSource
    review_status: ReviewStatus
    review_note: str | None
    variants: list[VariantRead] = Field(default_factory=list)
    ingredients: list[DishIngredientRead] = Field(default_factory=list)
    dietary_statuses: list[DietaryStatus] = Field(default_factory=list)
    badges: list[BadgeCode] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def flatten_controlled_associations(cls, value: object) -> object:
        if not hasattr(value, "dietary_statuses"):
            return value
        raw = vars(value).copy()
        source = cast(Any, value)
        raw["dietary_statuses"] = [
            item.status if hasattr(item, "status") else item for item in source.dietary_statuses
        ]
        raw["badges"] = [item.badge if hasattr(item, "badge") else item for item in source.badges]
        return raw


class CuisineReplace(BaseModel):
    cuisine_ids: list[UUID] = Field(default_factory=list)


class IngredientReplace(BaseModel):
    ingredients: list[DishIngredientInput] = Field(default_factory=list)
    ingredient_ids: list[UUID] | None = None

    @model_validator(mode="after")
    def normalize(self) -> IngredientReplace:
        if self.ingredient_ids is not None:
            self.ingredients = [DishIngredientInput(ingredient_id=i) for i in self.ingredient_ids]
        if len({item.ingredient_id for item in self.ingredients}) != len(self.ingredients):
            raise ValueError("ingredients must not contain duplicates")
        return self


class DietaryReplace(BaseModel):
    statuses: list[DietaryStatus] = Field(default_factory=list)


class BadgeReplace(BaseModel):
    badges: list[BadgeCode] = Field(default_factory=list)


class ImageCreate(BaseModel):
    variant_id: UUID | None = None
    storage_key: str | None = Field(default=None, max_length=1000)
    source_url: str | None = Field(default=None, max_length=2000)
    uri: str | None = Field(default=None, max_length=1000)
    alt_text: str | None = Field(default=None, max_length=300)
    mime_type: str | None = Field(default=None, max_length=100)
    sort_order: int = Field(default=0, ge=0)
    is_primary: bool = False
    approval_status: ImageApprovalStatus = ImageApprovalStatus.PENDING
    catalog_source: ProvenanceSource = ProvenanceSource.MANUAL
    review_status: ReviewStatus = ReviewStatus.CONFIRMED

    @model_validator(mode="after")
    def validate_location(self) -> ImageCreate:
        self.storage_key = self.storage_key.strip() if self.storage_key else None
        self.source_url = self.source_url.strip() if self.source_url else None
        self.uri = self.uri.strip() if self.uri else None
        if not self.storage_key and not self.source_url:
            raise ValueError("storage_key or source_url is required")
        return self


class ImageRead(ImageCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    dish_id: UUID


class ImagePatch(BaseModel):
    variant_id: UUID | None = None
    storage_key: str | None = Field(default=None, max_length=1000)
    source_url: str | None = Field(default=None, max_length=2000)
    uri: str | None = Field(default=None, max_length=1000)
    alt_text: str | None = Field(default=None, max_length=300)
    is_primary: bool | None = None
    approval_status: ImageApprovalStatus | None = None
    review_status: ReviewStatus | None = None


class ModifierGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    is_required: bool = False
    min_selections: int = Field(default=0, ge=0)
    max_selections: int = Field(default=1, ge=1)
    display_order: int = Field(default=0, ge=0)
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_bounds(self) -> ModifierGroupCreate:
        self.name = _text(self.name, "name")
        if self.sort_order is not None:
            self.display_order = self.sort_order
        if self.max_selections < self.min_selections:
            raise ValueError("max_selections must be at least min_selections")
        return self


class ModifierGroupPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    is_required: bool | None = None
    min_selections: int | None = Field(default=None, ge=0)
    max_selections: int | None = Field(default=None, ge=1)
    display_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ModifierOptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    price_delta: Decimal = Field(default=Decimal("0"), decimal_places=2)
    display_order: int = Field(default=0, ge=0)
    is_active: bool = True

    @model_validator(mode="after")
    def normalize(self) -> ModifierOptionCreate:
        self.name = _text(self.name, "name")
        return self


class ModifierOptionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    price_delta: Decimal | None = Field(default=None, decimal_places=2)
    display_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ModifierOptionRead(ModifierOptionCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    group_id: UUID


class ModifierGroupRead(ModifierGroupCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    dish_id: UUID
    options: list[ModifierOptionRead] = Field(default_factory=list)


class PublishRequest(BaseModel):
    confirm: bool = False


class PublicationStatusRead(BaseModel):
    menu_id: UUID
    status: MenuStatus
    ready: bool
    blockers: list[str] = Field(default_factory=list)
