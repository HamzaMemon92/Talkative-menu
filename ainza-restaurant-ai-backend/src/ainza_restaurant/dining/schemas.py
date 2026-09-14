from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ainza_restaurant.domain.enums import DiningSessionStartedVia, DiningSessionStatus


def _required_label(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("label must not be blank")
    return value


class TableCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    area_name: str | None = Field(default=None, max_length=120)
    capacity: int | None = Field(default=None, gt=0)
    display_order: int = Field(default=0, ge=0)
    is_active: bool = True

    @field_validator("label")
    @classmethod
    def trim_label(cls, value: str) -> str:
        return _required_label(value)

    @field_validator("area_name")
    @classmethod
    def trim_area(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class TablePatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    area_name: str | None = Field(default=None, max_length=120)
    capacity: int | None = Field(default=None, gt=0)
    display_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @field_validator("label")
    @classmethod
    def trim_label(cls, value: str | None) -> str | None:
        return _required_label(value) if value is not None else None

    @field_validator("area_name")
    @classmethod
    def trim_area(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class ConfirmRequest(BaseModel):
    confirm: bool


class SessionStartRequest(BaseModel):
    party_size: int | None = Field(default=None, gt=0)
    join_existing: bool = False


class ManualSessionStartRequest(BaseModel):
    party_size: int | None = Field(default=None, gt=0)


class TableRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    outlet_id: UUID
    label: str
    area_name: str | None
    capacity: int | None
    display_order: int
    is_active: bool
    public_qr_code: str
    qr_code_rotated_at: datetime | None
    has_open_session: bool = False
    created_at: datetime
    updated_at: datetime


class PublicRestaurantContext(BaseModel):
    id: UUID
    name: str


class PublicOutletContext(BaseModel):
    id: UUID
    name: str
    timezone: str


class PublicTableContext(BaseModel):
    id: UUID
    label: str
    area_name: str | None
    capacity: int | None


class CustomerMenuContext(BaseModel):
    available: bool
    outlet_id: UUID
    route: str


class DiningSessionRead(BaseModel):
    id: UUID
    public_session_token: str
    status: DiningSessionStatus
    party_size: int | None
    started_via: DiningSessionStartedVia
    opened_at: datetime
    closed_at: datetime | None
    table: PublicTableContext
    outlet: PublicOutletContext
    customer_menu: CustomerMenuContext


class ActiveSessionRead(BaseModel):
    table_id: UUID
    session: DiningSessionRead | None


class QRResolutionRead(BaseModel):
    restaurant: PublicRestaurantContext
    outlet: PublicOutletContext
    table: PublicTableContext
    customer_menu: CustomerMenuContext
    current_session_exists: bool
    active_session_token: str | None = None
    template_id: None = None
    frontend_url: None = None


class SessionStartRead(BaseModel):
    session: DiningSessionRead
    joined_existing: bool
