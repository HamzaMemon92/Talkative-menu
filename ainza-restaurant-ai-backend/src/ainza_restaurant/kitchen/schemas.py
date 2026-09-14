from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from ainza_restaurant.domain.enums import KitchenTicketItemStatus, KitchenTicketStatus


class KitchenTicketItemModifierRead(BaseModel):
    modifier_group_name_snapshot: str
    modifier_option_name_snapshot: str


class KitchenTicketItemRead(BaseModel):
    id: UUID
    dining_order_item_id: UUID
    dish_name_snapshot: str
    variant_name_snapshot: str | None
    quantity: int
    customer_note_snapshot: str | None
    modifiers: list[KitchenTicketItemModifierRead]
    status: KitchenTicketItemStatus
    queued_at: datetime
    started_at: datetime | None
    ready_at: datetime | None
    served_at: datetime | None


class KitchenTicketRead(BaseModel):
    id: UUID
    outlet_id: UUID
    dining_order_id: UUID
    dining_session_id: UUID
    round_number: int
    table_label_snapshot: str
    submitted_at: datetime
    status: KitchenTicketStatus
    created_at: datetime
    started_at: datetime | None
    ready_at: datetime | None
    served_at: datetime | None
    items: list[KitchenTicketItemRead]
