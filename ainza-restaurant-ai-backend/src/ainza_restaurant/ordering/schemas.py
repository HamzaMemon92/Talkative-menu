from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from ainza_restaurant.domain.enums import DiningOrderStatus, OfferType


class CartItemCreate(BaseModel):
    dish_id: UUID
    variant_id: UUID | None = None
    quantity: int = Field(gt=0, le=99)
    modifier_option_ids: list[UUID] = Field(default_factory=list)
    customer_note: str | None = Field(default=None, max_length=500)
    expected_version: int | None = Field(default=None, ge=1)

    @field_validator("modifier_option_ids")
    @classmethod
    def no_duplicate_modifiers(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("modifier_option_ids must not contain duplicates")
        return value

    @field_validator("customer_note")
    @classmethod
    def trim_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class CartItemPatch(BaseModel):
    quantity: int | None = Field(default=None, gt=0, le=99)
    modifier_option_ids: list[UUID] | None = None
    customer_note: str | None = Field(default=None, max_length=500)
    expected_version: int | None = Field(default=None, ge=1)

    @field_validator("modifier_option_ids")
    @classmethod
    def no_duplicate_modifiers(cls, value: list[UUID] | None) -> list[UUID] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("modifier_option_ids must not contain duplicates")
        return value

    @field_validator("customer_note")
    @classmethod
    def trim_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class CartItemRemoveRequest(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)


class CartOfferSelect(BaseModel):
    offer_id: UUID | None = None
    expected_version: int | None = Field(default=None, ge=1)


class CartSubmitRequest(BaseModel):
    confirm: bool
    quote_token: str
    idempotency_key: str = Field(min_length=1, max_length=120)

    @field_validator("idempotency_key")
    @classmethod
    def trim_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("idempotency_key must not be blank")
        return value


class CartModifierRead(BaseModel):
    modifier_option_id: UUID
    modifier_group_id: UUID
    modifier_group_name: str
    modifier_option_name: str
    price_delta: Decimal


class CartItemPricingRead(BaseModel):
    catalog_unit_price: Decimal
    special_unit_price: Decimal | None
    effective_base_unit_price: Decimal
    modifier_unit_total: Decimal
    configured_unit_price: Decimal
    quantity: int
    line_subtotal: Decimal


class CartItemRead(BaseModel):
    id: UUID
    dish_id: UUID
    dish_name: str
    variant_id: UUID | None
    variant_name: str | None
    quantity: int
    customer_note: str | None
    available: bool
    availability_status: str
    pricing: CartItemPricingRead
    modifiers: list[CartModifierRead] = Field(default_factory=list)


class SelectedOfferRead(BaseModel):
    offer_id: UUID | None
    name: str | None
    offer_type: OfferType | None
    effective: bool
    eligible: bool
    amount_to_threshold: Decimal | None
    discount_amount: Decimal
    stacking_applied: bool = False
    auto_best_offer_selected: bool = False


class CartRead(BaseModel):
    dining_session_token: str
    version: int
    currency_code: str
    item_count: int
    quantity_count: int
    items: list[CartItemRead] = Field(default_factory=list)
    subtotal_before_offer: Decimal
    selected_offer: SelectedOfferRead
    discount_amount: Decimal
    subtotal_after_discount: Decimal
    tax_calculated: bool = False
    final_bill_calculated: bool = False
    can_submit: bool
    unavailable_item_ids: list[UUID] = Field(default_factory=list)
    quote_token: str


class CartBatchAddItem(BaseModel):
    """One semantic batch addition; requirement controls failure handling."""

    dish_id: UUID | None = None
    variant_id: UUID | None = None
    quantity: int = Field(gt=0, le=99)
    modifier_option_ids: list[UUID] = Field(default_factory=list)
    customer_note: str | None = Field(default=None, max_length=500)
    required: bool = True
    requested_reference: str | None = Field(default=None, max_length=200)


class CartBatchAddItemResult(BaseModel):
    index: int
    dish_id: UUID | None = None
    requested_quantity: int
    added_quantity: int = 0
    status: str
    reason: str | None = None
    requested_reference: str | None = None


class CartBatchAddRead(BaseModel):
    cart: CartRead
    overall_status: str
    items: list[CartBatchAddItemResult] = Field(default_factory=list)


class OrderItemModifierRead(BaseModel):
    modifier_option_id: UUID | None
    modifier_group_name_snapshot: str
    modifier_option_name_snapshot: str
    price_delta_snapshot: Decimal


class OrderItemRead(BaseModel):
    id: UUID
    dish_id: UUID
    variant_id: UUID | None
    dish_name_snapshot: str
    variant_name_snapshot: str | None
    quantity: int
    customer_note_snapshot: str | None
    catalog_unit_price_snapshot: Decimal
    special_unit_price_snapshot: Decimal | None
    effective_base_unit_price_snapshot: Decimal
    modifier_unit_total_snapshot: Decimal
    configured_unit_price_snapshot: Decimal
    line_subtotal_snapshot: Decimal
    tax_category_code_snapshot: str | None
    modifiers: list[OrderItemModifierRead] = Field(default_factory=list)


class OrderRead(BaseModel):
    id: UUID
    dining_session_id: UUID
    round_number: int
    status: DiningOrderStatus
    currency_code: str
    subtotal_before_discount: Decimal
    discount_amount: Decimal
    subtotal_after_discount: Decimal
    selected_offer_id: UUID | None
    offer_name_snapshot: str | None
    offer_type_snapshot: OfferType | None
    idempotency_key: str
    submitted_at: datetime
    items: list[OrderItemRead] = Field(default_factory=list)
    tax_calculated: bool = False
    final_bill_calculated: bool = False
