from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from ainza_restaurant.domain.enums import (
    AvailabilityAction,
    AvailabilityDurationMode,
    AvailabilityProposalStatus,
    AvailabilityReasonCode,
    AvailabilityTargetType,
)


class AvailabilityProposalCreate(BaseModel):
    target_type: AvailabilityTargetType
    target_id: UUID
    action: AvailabilityAction
    duration_mode: AvailabilityDurationMode | None = None
    requested_until: datetime | None = None
    reason_code: AvailabilityReasonCode | None = None
    reason_note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_action_duration(self) -> AvailabilityProposalCreate:
        if self.action == AvailabilityAction.MARK_UNAVAILABLE and self.duration_mode is None:
            raise ValueError("duration_mode is required for mark_unavailable")
        if self.action == AvailabilityAction.RESTORE and self.duration_mode is not None:
            raise ValueError("duration_mode is not allowed for restore")
        if self.duration_mode == AvailabilityDurationMode.UNTIL_TIMESTAMP:
            if self.requested_until is None:
                raise ValueError("requested_until is required for until_timestamp")
            if self.requested_until.tzinfo is None:
                raise ValueError("requested_until must be timezone-aware")
        elif self.requested_until is not None:
            raise ValueError("requested_until is only valid with until_timestamp")
        return self


class AvailabilityConfirmRequest(BaseModel):
    confirm: bool

    @field_validator("confirm")
    @classmethod
    def require_confirm(cls, value: bool) -> bool:
        if not value:
            raise ValueError("confirm must be true")
        return value


class AvailabilityCancelRequest(BaseModel):
    confirm: bool = True


class AvailabilityTargetRead(BaseModel):
    type: AvailabilityTargetType
    id: UUID
    name: str


class AvailabilityAffectedDishRead(BaseModel):
    dish_id: UUID
    name: str
    category_id: UUID | None = None
    catalog_active: bool


class AvailabilityProposalRead(BaseModel):
    id: UUID
    outlet_id: UUID
    target: AvailabilityTargetRead
    action: AvailabilityAction
    duration_mode: AvailabilityDurationMode | None
    requested_until: datetime | None
    computed_expires_at: datetime | None
    reason_code: AvailabilityReasonCode | None
    reason_note: str | None
    status: AvailabilityProposalStatus
    proposal_expires_at: datetime
    current_outlet_time: datetime | None = None
    affected_dishes: list[AvailabilityAffectedDishRead] = Field(default_factory=list)
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AvailabilityCauseRead(BaseModel):
    type: AvailabilityTargetType
    override_id: UUID
    dish_id: UUID | None = None
    dish_name: str | None = None
    ingredient_id: UUID | None = None
    ingredient_name: str | None = None
    reason_code: AvailabilityReasonCode
    reason_note: str | None
    starts_at: datetime
    expires_at: datetime | None
    source_proposal_id: UUID


class DishAvailabilityRead(BaseModel):
    dish_id: UUID
    dish_name: str
    outlet_id: UUID | None
    menu_id: UUID
    category_id: UUID | None
    catalog_active: bool
    available: bool
    blocking_causes: list[AvailabilityCauseRead] = Field(default_factory=list)


class IngredientAvailabilityRead(BaseModel):
    ingredient_id: UUID
    ingredient_name: str
    outlet_id: UUID | None
    available: bool
    active_overrides: list[AvailabilityCauseRead] = Field(default_factory=list)


class OutletAvailabilityRead(BaseModel):
    outlet_id: UUID
    current_outlet_time: datetime
    dishes: list[DishAvailabilityRead] = Field(default_factory=list)
