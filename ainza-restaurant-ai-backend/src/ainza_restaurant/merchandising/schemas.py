from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from ainza_restaurant.domain.enums import (
    MerchandisingStatus,
    OfferScopeType,
    OfferType,
    SpecialDurationMode,
)


class ConfirmRequest(BaseModel):
    confirm: bool

    @field_validator("confirm")
    @classmethod
    def require_confirm(cls, value: bool) -> bool:
        if not value:
            raise ValueError("confirm must be true")
        return value


class SpecialCreate(BaseModel):
    dish_id: UUID
    variant_id: UUID | None = None
    special_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    duration_mode: SpecialDurationMode = SpecialDurationMode.UNTIL_SERVICE_END
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    display_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_duration(self) -> SpecialCreate:
        if self.duration_mode == SpecialDurationMode.UNTIL_TIMESTAMP:
            if self.ends_at is None:
                raise ValueError("ends_at is required for until_timestamp")
            if self.ends_at.tzinfo is None:
                raise ValueError("ends_at must be timezone-aware")
            if self.starts_at is not None and self.starts_at.tzinfo is None:
                raise ValueError("starts_at must be timezone-aware")
        return self


class SpecialPatch(BaseModel):
    special_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    display_note: str | None = Field(default=None, max_length=500)


class SpecialRead(BaseModel):
    id: UUID
    outlet_id: UUID
    dish_id: UUID
    variant_id: UUID | None
    special_price: Decimal | None
    starts_at: datetime
    ends_at: datetime
    status: MerchandisingStatus
    activation_confirmed: bool
    display_note: str | None
    effective_active: bool
    dish_available: bool | None = None
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None
    deactivated_at: datetime | None


class FeaturedCreate(BaseModel):
    dish_id: UUID
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    display_order: int = Field(default=0, ge=0)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class FeaturedPatch(BaseModel):
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    display_order: int | None = Field(default=None, ge=0)


class FeaturedRead(BaseModel):
    id: UUID
    outlet_id: UUID
    dish_id: UUID
    starts_at: datetime
    ends_at: datetime | None
    status: MerchandisingStatus
    display_order: int
    activation_confirmed: bool
    effective_active: bool
    dish_available: bool | None = None
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None
    deactivated_at: datetime | None


class OfferCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    offer_type: OfferType
    scope_type: OfferScopeType = OfferScopeType.ALL_ITEMS
    starts_at: datetime
    ends_at: datetime
    minimum_subtotal: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    discount_value: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    maximum_discount: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    combo_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)

    @model_validator(mode="after")
    def validate_offer(self) -> OfferCreate:
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("offer timestamps must be timezone-aware")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.offer_type == OfferType.PERCENTAGE:
            if self.discount_value is None or not (
                Decimal("0") < self.discount_value <= Decimal("100")
            ):
                raise ValueError("percentage discount must be greater than 0 and at most 100")
        if self.offer_type == OfferType.FLAT:
            if self.discount_value is None or self.discount_value <= 0:
                raise ValueError("flat discount must be greater than 0")
        if self.offer_type == OfferType.COMBO_FIXED_PRICE:
            if self.combo_price is None:
                raise ValueError("combo_price is required")
        return self


class OfferPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    minimum_subtotal: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    discount_value: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    maximum_discount: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    combo_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)


class ScopeDishReplace(BaseModel):
    dish_ids: list[UUID] = Field(default_factory=list)


class ScopeCategoryReplace(BaseModel):
    category_ids: list[UUID] = Field(default_factory=list)


class ComboItemInput(BaseModel):
    dish_id: UUID
    variant_id: UUID | None = None
    required_quantity: int = Field(ge=1)


class ComboItemsReplace(BaseModel):
    items: list[ComboItemInput] = Field(default_factory=list)


class OfferRead(BaseModel):
    id: UUID
    outlet_id: UUID
    name: str
    description: str | None
    offer_type: OfferType
    scope_type: OfferScopeType
    status: MerchandisingStatus
    starts_at: datetime
    ends_at: datetime
    minimum_subtotal: Decimal | None
    discount_value: Decimal | None
    maximum_discount: Decimal | None
    combo_price: Decimal | None
    activation_confirmed: bool
    effective_active: bool
    dish_scope_ids: list[UUID] = Field(default_factory=list)
    category_scope_ids: list[UUID] = Field(default_factory=list)
    combo_items: list[ComboItemInput] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None
    paused_at: datetime | None
    deactivated_at: datetime | None


class PreviewItem(BaseModel):
    dish_id: UUID
    variant_id: UUID | None = None
    quantity: int = Field(ge=1)


class OfferPreviewRequest(BaseModel):
    items: list[PreviewItem] = Field(default_factory=list)


class PreviewLineRead(BaseModel):
    dish_id: UUID
    variant_id: UUID | None
    quantity: int
    unit_price: Decimal
    line_subtotal: Decimal
    eligible: bool
    available: bool


class OfferPreviewRead(BaseModel):
    offer_id: UUID
    eligible: bool
    can_fulfill: bool
    regular_subtotal: Decimal
    eligible_subtotal: Decimal
    minimum_subtotal: Decimal | None
    amount_to_threshold: Decimal
    discount_amount: Decimal
    post_discount_subtotal: Decimal
    complete_combo_count: int = 0
    line_items: list[PreviewLineRead] = Field(default_factory=list)
    tax_calculated: bool = False
    final_invoice_created: bool = False
