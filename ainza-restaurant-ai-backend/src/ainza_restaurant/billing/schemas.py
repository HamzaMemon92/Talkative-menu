from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from ainza_restaurant.domain.enums import DiningInvoiceStatus, DiningOrderStatus, RestaurantType


class BillingRoundSummaryRead(BaseModel):
    dining_order_id: UUID
    round_number: int
    status: DiningOrderStatus
    subtotal_before_discount: Decimal
    discount_amount: Decimal
    subtotal_after_discount: Decimal


class BillingTaxConfigurationRead(BaseModel):
    configured: bool
    tax_rate_percent: Decimal | None
    prices_include_tax: bool | None
    tax_configuration_confirmed: bool
    gst_registered: bool | None
    gstin: str | None
    legal_business_name: str | None
    restaurant_type: RestaurantType | None


class BillPreviewRead(BaseModel):
    dining_session_id: UUID
    dining_session_token: str
    outlet_id: UUID
    outlet_name: str
    currency_code: str
    round_summaries: list[BillingRoundSummaryRead] = Field(default_factory=list)
    subtotal_before_discount: Decimal
    discount_total: Decimal
    subtotal_after_discount: Decimal
    tax_configuration: BillingTaxConfigurationRead
    taxable_amount: Decimal | None
    tax_amount: Decimal | None
    invoice_total: Decimal | None
    finalizable: bool
    blockers: list[str] = Field(default_factory=list)
    billing_quote_token: str


class InvoiceFinalizeRequest(BaseModel):
    confirm: bool
    billing_quote_token: str
    idempotency_key: str = Field(min_length=1, max_length=120)

    @field_validator("idempotency_key")
    @classmethod
    def trim_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("idempotency_key must not be blank")
        return value


class InvoiceOrderRead(BaseModel):
    dining_order_id: UUID
    round_number_snapshot: int


class InvoiceLineModifierRead(BaseModel):
    modifier_option_id: UUID | None
    modifier_group_name_snapshot: str
    modifier_option_name_snapshot: str
    price_delta_snapshot: Decimal


class InvoiceLineRead(BaseModel):
    id: UUID
    dining_order_id: UUID
    dining_order_item_id: UUID | None
    round_number_snapshot: int
    dish_name_snapshot: str
    variant_name_snapshot: str | None
    quantity: int
    configured_unit_price_snapshot: Decimal
    line_subtotal_snapshot: Decimal
    customer_note_snapshot: str | None
    tax_category_code_snapshot: str | None
    display_order: int
    modifiers: list[InvoiceLineModifierRead] = Field(default_factory=list)


class InvoiceRead(BaseModel):
    id: UUID
    dining_session_id: UUID
    outlet_id: UUID
    invoice_reference: str
    status: DiningInvoiceStatus
    currency_code: str
    subtotal_before_discount: Decimal
    discount_total: Decimal
    subtotal_after_discount: Decimal
    taxable_amount: Decimal
    tax_rate_snapshot: Decimal
    prices_include_tax_snapshot: bool
    tax_amount: Decimal
    invoice_total: Decimal
    restaurant_name_snapshot: str
    outlet_name_snapshot: str
    legal_business_name_snapshot: str
    restaurant_type_snapshot: RestaurantType
    gst_registered_snapshot: bool
    gstin_snapshot: str | None
    state_snapshot: str | None
    country_code_snapshot: str
    finalized_at: datetime
    created_at: datetime
    orders: list[InvoiceOrderRead] = Field(default_factory=list)
    lines: list[InvoiceLineRead] = Field(default_factory=list)
