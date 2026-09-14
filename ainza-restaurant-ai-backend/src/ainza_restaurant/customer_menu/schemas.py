from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from ainza_restaurant.domain.enums import (
    AlcoholPolicy,
    AllergenStatus,
    AvailabilityStatus,
    BadgeCode,
    DietaryClassification,
    HalalCertificationStatus,
    HalalOverride,
    HalalPolicy,
    ImageApprovalStatus,
    ItemType,
    OfferScopeType,
    OfferType,
    PorkPolicy,
    SpiceLevel,
)


class CustomerRestaurantRead(BaseModel):
    id: UUID
    name: str
    slug: str


class CustomerOutletRead(BaseModel):
    id: UUID
    restaurant_id: UUID
    name: str
    city: str
    state: str
    country: str
    timezone: str
    currency_code: str


class CustomerMenuSummaryRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    published_at: datetime | None
    prices_include_tax: bool | None


class CustomerFoodPolicyRead(BaseModel):
    information_confirmed: bool
    halal_policy: HalalPolicy
    halal_certification_status: HalalCertificationStatus
    pork_policy: PorkPolicy
    alcohol_policy: AlcoholPolicy
    platform_verified: bool = False


class CustomerAvailabilityRead(BaseModel):
    available: bool
    status: str
    message: str | None = None


class CustomerImageRead(BaseModel):
    id: UUID
    variant_id: UUID | None
    storage_key: str | None
    source_url: str | None
    alt_text: str | None
    mime_type: str | None
    width: int | None
    height: int | None
    sort_order: int
    is_primary: bool
    approval_status: ImageApprovalStatus


class CustomerIngredientRead(BaseModel):
    id: UUID
    name: str


class CustomerModifierOptionRead(BaseModel):
    id: UUID
    name: str
    price_delta: Decimal
    display_order: int


class CustomerModifierGroupRead(BaseModel):
    id: UUID
    name: str
    is_required: bool
    min_selections: int
    max_selections: int
    display_order: int
    options: list[CustomerModifierOptionRead] = Field(default_factory=list)


class CustomerCuisineRead(BaseModel):
    id: UUID
    name: str


class CustomerPricingRead(BaseModel):
    currency_code: str
    catalog_price: Decimal | None
    effective_price: Decimal | None
    has_special_price: bool
    special_price: Decimal | None
    starting_price: Decimal | None = None


class CustomerVariantRead(BaseModel):
    id: UUID
    name: str
    catalog_price: Decimal
    effective_price: Decimal
    has_special_price: bool
    special_price: Decimal | None
    is_todays_special: bool
    special_ends_at: datetime | None
    display_order: int
    primary_image: CustomerImageRead | None
    images: list[CustomerImageRead] = Field(default_factory=list)


class CustomerDishRead(BaseModel):
    id: UUID
    menu_id: UUID
    category_id: UUID
    name: str
    description: str | None
    item_type: ItemType
    dietary_classification: DietaryClassification
    vegan_status: AvailabilityStatus
    jain_status: AvailabilityStatus
    halal_status: HalalOverride
    spice_level: SpiceLevel
    ingredient_description: str | None
    allergen_information_status: AllergenStatus
    allergen_notes: str | None
    badges: list[BadgeCode] = Field(default_factory=list)
    is_todays_special: bool
    special_display_note: str | None
    special_ends_at: datetime | None
    is_featured: bool
    featured_display_order: int | None
    available: bool
    availability: CustomerAvailabilityRead
    pricing: CustomerPricingRead
    variants: list[CustomerVariantRead] = Field(default_factory=list)
    primary_image: CustomerImageRead | None
    images: list[CustomerImageRead] = Field(default_factory=list)
    modifiers: list[CustomerModifierGroupRead] = Field(default_factory=list)
    ingredients: list[CustomerIngredientRead] = Field(default_factory=list)
    cuisines: list[CustomerCuisineRead] = Field(default_factory=list)
    display_order: int


class CustomerCategoryRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    display_order: int
    dishes: list[CustomerDishRead] = Field(default_factory=list)


class CustomerOfferRefRead(BaseModel):
    id: UUID
    name: str


class CustomerComboItemRead(BaseModel):
    dish_id: UUID
    dish_name: str
    variant_id: UUID | None
    variant_name: str | None
    required_quantity: int


class CustomerOfferRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    offer_type: OfferType
    scope_type: OfferScopeType
    minimum_subtotal: Decimal | None
    discount_value: Decimal | None
    maximum_discount: Decimal | None
    combo_price: Decimal | None
    starts_at: datetime
    ends_at: datetime
    dish_scope: list[CustomerOfferRefRead] = Field(default_factory=list)
    category_scope: list[CustomerOfferRefRead] = Field(default_factory=list)
    combo_items: list[CustomerComboItemRead] = Field(default_factory=list)
    stacking_applied: bool = False
    auto_best_offer_selected: bool = False


class CustomerMenuRead(BaseModel):
    restaurant: CustomerRestaurantRead
    outlet: CustomerOutletRead
    menu: CustomerMenuSummaryRead
    food_policy: CustomerFoodPolicyRead
    featured_dishes: list[CustomerDishRead] = Field(default_factory=list)
    categories: list[CustomerCategoryRead] = Field(default_factory=list)
    offers: list[CustomerOfferRead] = Field(default_factory=list)
    generated_at: datetime


class CustomerMenuFilters(BaseModel):
    category_id: UUID | None = None
    cuisine_id: UUID | None = None
    item_type: ItemType | None = None
    dietary_classification: DietaryClassification | None = None
    vegan_status: AvailabilityStatus | None = None
    jain_status: AvailabilityStatus | None = None
    halal_status: HalalOverride | None = None
    spice_level: SpiceLevel | None = None
    available: bool | None = None
    is_featured: bool | None = None
    is_todays_special: bool | None = None
    price_min: Decimal | None = Field(default=None, ge=Decimal("0"))
    price_max: Decimal | None = Field(default=None, ge=Decimal("0"))

    @model_validator(mode="after")
    def validate_price_range(self) -> CustomerMenuFilters:
        if self.price_min is not None and self.price_max is not None:
            if self.price_min > self.price_max:
                raise ValueError("price_min must not exceed price_max")
        return self
