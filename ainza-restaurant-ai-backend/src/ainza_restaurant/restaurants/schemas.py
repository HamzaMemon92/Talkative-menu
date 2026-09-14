from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
from ainza_restaurant.restaurants.domain import normalize_slug, validate_gstin


def _required_text(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must not be blank")
    return value


def _validate_timezone(value: str) -> str:
    value = value.strip()
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        # Windows installations without the optional tzdata package still
        # need to accept the product's India-first default.
        if value == "Asia/Kolkata":
            return value
        raise ValueError("timezone must be a valid IANA time zone") from exc
    return value


def _validate_currency_code(value: str) -> str:
    value = value.strip().upper()
    if len(value) != 3 or not value.isalpha():
        raise ValueError("currency_code must be a three-letter ISO 4217 code")
    return value


class RestaurantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=220)
    legal_name: str | None = Field(default=None, max_length=200)
    status: RestaurantStatus = RestaurantStatus.ACTIVE

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        return _required_text(value, "name")

    @field_validator("slug")
    @classmethod
    def normalize_slug_value(cls, value: str | None) -> str | None:
        return normalize_slug(value) if value is not None else None


class RestaurantPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=220)
    legal_name: str | None = Field(default=None, max_length=200)
    status: RestaurantStatus | None = None

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str | None) -> str | None:
        return _required_text(value, "name") if value is not None else None

    @field_validator("slug")
    @classmethod
    def normalize_slug_value(cls, value: str | None) -> str | None:
        return normalize_slug(value) if value is not None else None


class RestaurantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    legal_name: str | None
    status: RestaurantStatus
    onboarding_status: OnboardingStatus
    finalized_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OutletCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address_line1: str = Field(min_length=1, max_length=250)
    address_line2: str | None = Field(default=None, max_length=250)
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(min_length=1, max_length=20)
    country: str = Field(default="IN", min_length=2, max_length=2)
    timezone: str = Field(default="Asia/Kolkata", min_length=1, max_length=64)
    currency_code: str = Field(default="INR", min_length=3, max_length=3)
    is_primary: bool | None = None
    is_active: bool = True

    @field_validator("name", "address_line1", "city", "state", "postal_code")
    @classmethod
    def trim_required(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        value = value.strip().upper()
        if not value.isalpha():
            raise ValueError("country must be a two-letter ISO country code")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return _validate_timezone(value)

    @field_validator("currency_code")
    @classmethod
    def validate_currency_code(cls, value: str) -> str:
        return _validate_currency_code(value)


class OutletPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address_line1: str | None = Field(default=None, min_length=1, max_length=250)
    address_line2: str | None = Field(default=None, max_length=250)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    state: str | None = Field(default=None, min_length=1, max_length=100)
    postal_code: str | None = Field(default=None, min_length=1, max_length=20)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    is_primary: bool | None = None
    is_active: bool | None = None

    @field_validator("name", "address_line1", "city", "state", "postal_code")
    @classmethod
    def trim_optional(cls, value: str | None, info: Any) -> str | None:
        return _required_text(value, info.field_name) if value is not None else None

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if not value.isalpha():
            raise ValueError("country must be a two-letter ISO country code")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        return _validate_timezone(value) if value is not None else None

    @field_validator("currency_code")
    @classmethod
    def validate_currency_code(cls, value: str | None) -> str | None:
        return _validate_currency_code(value) if value is not None else None


class OutletRead(OutletCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    restaurant_id: UUID
    is_primary: bool
    is_active: bool
    currency_code: str
    created_at: datetime
    updated_at: datetime


class OperatingIntervalInput(BaseModel):
    weekday: int = Field(ge=0, le=6)
    opens_at: time | None = None
    closes_at: time | None = None
    is_full_day: bool = False

    @model_validator(mode="after")
    def validate_shape(self) -> OperatingIntervalInput:
        if self.is_full_day:
            if (self.opens_at is None) != (self.closes_at is None):
                raise ValueError("full-day intervals require both times or neither")
            if self.opens_at is not None and self.opens_at != self.closes_at:
                raise ValueError("full-day intervals must have matching times")
        elif self.opens_at is None or self.closes_at is None:
            raise ValueError("opens_at and closes_at are required unless is_full_day is true")
        elif self.opens_at == self.closes_at:
            raise ValueError(
                "opens_at and closes_at must differ; set is_full_day=true for a full day"
            )
        return self


class OperatingHoursReplace(BaseModel):
    intervals: list[OperatingIntervalInput] = Field(default_factory=list)


class OperatingIntervalRead(OperatingIntervalInput):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    outlet_id: UUID


class OperatingHoursRead(BaseModel):
    outlet_id: UUID
    intervals: list[OperatingIntervalRead]


class TaxProfileUpsert(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    legal_business_name: str | None = Field(default=None, max_length=200)
    restaurant_type: RestaurantType | None = None
    gst_registered: bool | None = None
    gst_state_code: str | None = Field(default=None, min_length=2, max_length=2)
    gstin: str | None = None
    gstin_confirmed: bool = False
    configured_tax_rate_percent: Decimal | None = Field(default=None, ge=0, le=100)
    prices_include_tax: bool | None = None
    tax_configuration_confirmed: bool = False
    # Compatibility aliases from the first implementation.
    no_auto_tax_rates_confirmed: bool = False
    tax_rates_confirmed: bool = False
    confirm_no_auto_tax_rates: bool | None = None

    @field_validator("legal_business_name")
    @classmethod
    def trim_legal_name(cls, value: str | None) -> str | None:
        return _required_text(value, "legal_business_name") if value is not None else None

    @field_validator("restaurant_type")
    @classmethod
    def trim_restaurant_type(cls, value: RestaurantType | None) -> RestaurantType | None:
        return value

    @field_validator("gst_state_code")
    @classmethod
    def normalize_state_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) != 2 or not value.isdigit():
            raise ValueError("gst_state_code must contain exactly two digits")
        return value

    @field_validator("gstin")
    @classmethod
    def check_gstin(cls, value: str | None) -> str | None:
        return validate_gstin(value)

    @model_validator(mode="after")
    def validate_tax_rules(self) -> TaxProfileUpsert:
        if self.confirm_no_auto_tax_rates:
            self.no_auto_tax_rates_confirmed = True
        if self.gst_registered is True and not self.gstin:
            raise ValueError("gstin is required when gst_registered is true")
        if self.gstin and self.gst_registered is False:
            raise ValueError("gstin cannot be supplied when gst_registered is false")
        if self.gst_state_code and self.gst_registered is False:
            raise ValueError("gst_state_code cannot be supplied when gst_registered is false")
        if self.gstin_confirmed and not self.gstin:
            raise ValueError("gstin_confirmed cannot be true without a GSTIN")
        if self.gstin and not self.gstin_confirmed:
            raise ValueError("gstin_confirmed must be true when a GSTIN is supplied")
        if self.gst_registered is True and not self.gst_state_code:
            raise ValueError("gst_state_code is required when gst_registered is true")
        return self


class TaxProfileRead(TaxProfileUpsert):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    outlet_id: UUID
    created_at: datetime
    updated_at: datetime


class FoodPolicyUpsert(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    halal_policy: HalalPolicy = HalalPolicy.UNKNOWN
    halal_status: HalalStatus | None = None
    halal_certification_status: HalalCertificationStatus = HalalCertificationStatus.UNKNOWN
    halal_certificate_reference: str | None = Field(default=None, max_length=500)
    halal_certification: HalalCertificationStatus | None = None
    pork_served_status: PorkPolicy = PorkPolicy.UNKNOWN
    alcohol_served_status: AlcoholPolicy = AlcoholPolicy.UNKNOWN
    notes: str | None = Field(default=None, max_length=1000)
    information_confirmed: bool = False
    # Legacy aliases retained for existing Task 002 clients.
    pork_policy: PorkPolicy | None = None
    alcohol_policy: AlcoholPolicy | None = None
    confirmation: bool | None = None
    confirmed: bool | None = None
    policy_confirmed: bool | None = None
    food_policy_confirmed: bool | None = None
    confirm: bool | None = None

    @model_validator(mode="after")
    def require_confirmation(self) -> FoodPolicyUpsert:
        if self.halal_certification is not None:
            self.halal_certification_status = self.halal_certification
        legacy_fields = {"halal_status", "pork_policy", "alcohol_policy", "confirmation"}
        if self.halal_status is not None:
            self.halal_policy = (
                HalalPolicy.ALL_NONVEG_MEAT_RESTAURANT_DECLARED_HALAL
                if self.halal_status == HalalStatus.HALAL
                else (
                    HalalPolicy.RESTAURANT_DECLARED_NOT_HALAL
                    if self.halal_status == HalalStatus.NOT_HALAL
                    else (
                        HalalPolicy.SELECTED_ITEMS_ONLY
                        if self.halal_status == HalalStatus.PARTIAL
                        else HalalPolicy.UNKNOWN
                    )
                )
            )
        if self.pork_policy is not None:
            self.pork_served_status = self.pork_policy
        if self.alcohol_policy is not None:
            self.alcohol_served_status = self.alcohol_policy
        if self.confirmation is not None:
            self.information_confirmed = self.confirmation
        if (
            self.confirm is True
            or self.confirmed is True
            or self.policy_confirmed is True
            or self.food_policy_confirmed is True
        ):
            self.confirmation = True
        if (
            self.__class__.__name__ != "FoodPolicyRead"
            and not self.information_confirmed
            and legacy_fields.intersection(self.model_fields_set)
        ):
            raise ValueError("confirmation must be true")
        return self


class FoodPolicyRead(FoodPolicyUpsert):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    outlet_id: UUID
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def expose_confirmation_alias(self) -> FoodPolicyRead:
        self.confirmation = self.information_confirmed
        self.confirmed = self.information_confirmed
        self.policy_confirmed = self.information_confirmed
        self.food_policy_confirmed = self.information_confirmed
        self.halal_status = (
            HalalStatus.HALAL
            if self.halal_policy == HalalPolicy.ALL_NONVEG_MEAT_RESTAURANT_DECLARED_HALAL
            else (
                HalalStatus.NOT_HALAL
                if self.halal_policy == HalalPolicy.RESTAURANT_DECLARED_NOT_HALAL
                else (
                    HalalStatus.PARTIAL
                    if self.halal_policy == HalalPolicy.SELECTED_ITEMS_ONLY
                    else HalalStatus.UNKNOWN
                )
            )
        )
        self.pork_policy = self.pork_served_status
        self.alcohol_policy = self.alcohol_served_status
        self.halal_certification = self.halal_certification_status
        return self


class LegacyTaxProfileUpsert(BaseModel):
    """Compatibility payload for the pre-versioned Task 002 routes."""

    gstin: str | None = None
    gstin_confirmed: bool = False
    no_auto_tax_rates_confirmed: bool = False
    tax_rates_confirmed: bool = False
    confirm_no_auto_tax_rates: bool | None = None

    @field_validator("gstin")
    @classmethod
    def check_gstin(cls, value: str | None) -> str | None:
        return validate_gstin(value)

    @model_validator(mode="after")
    def require_confirmation(self) -> LegacyTaxProfileUpsert:
        if self.gstin and not self.gstin_confirmed:
            raise ValueError("gstin_confirmed must be true when a GSTIN is supplied")
        if self.confirm_no_auto_tax_rates:
            self.no_auto_tax_rates_confirmed = True
        if not self.no_auto_tax_rates_confirmed:
            raise ValueError("explicitly confirm that tax rates must not be auto-populated")
        return self


class ReadinessCheck(BaseModel):
    code: str
    passed: bool
    message: str
    outlet_id: UUID | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class MissingRequirement(BaseModel):
    code: str
    message: str
    outlet_id: UUID | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class OnboardingReadiness(BaseModel):
    restaurant_id: UUID
    status: OnboardingStatus
    ready: bool
    is_ready: bool
    finalized: bool
    checks: list[ReadinessCheck]
    missing_requirements: list[MissingRequirement]
    # Compatibility fields retained for clients of the first Task 002 API.
    blocking_reasons: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class FinalizeRequest(BaseModel):
    confirm: bool

    @field_validator("confirm")
    @classmethod
    def require_confirmation(cls, value: bool) -> bool:
        if not value:
            raise ValueError("confirm must be true")
        return value


class FinalizationResponse(BaseModel):
    restaurant: RestaurantRead
    readiness: OnboardingReadiness
