from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.base import ExecutableOption

from ainza_restaurant.domain.enums import (
    DiningOrderStatus,
    KitchenTicketItemStatus,
    KitchenTicketStatus,
)
from ainza_restaurant.kitchen.models import KitchenTicket, KitchenTicketItem
from ainza_restaurant.kitchen.schemas import (
    KitchenTicketItemModifierRead,
    KitchenTicketItemRead,
    KitchenTicketRead,
)
from ainza_restaurant.ordering.models import (
    DiningOrder,
    DiningOrderItem,
)


class KitchenNotFound(LookupError):
    code = "kitchen_ticket_not_found"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class KitchenConflict(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "kitchen_conflict",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class KitchenService:
    def __init__(self, session: AsyncSession, *, now: Callable[[], datetime] | None = None) -> None:
        self.session = session
        self._now = now or (lambda: datetime.now(UTC))

    def now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    async def create_ticket_for_order(
        self,
        order_id: UUID,
        *,
        outlet_id: UUID,
        table_label_snapshot: str,
    ) -> KitchenTicket:
        existing = await self._ticket_for_order_or_none(order_id)
        if existing is not None:
            return existing
        order = await self._order_with_items(order_id)
        if not order.items:
            raise KitchenConflict("order has no items", code="kitchen_order_missing")
        now = self.now()
        ticket = KitchenTicket(
            outlet_id=outlet_id,
            dining_order_id=order.id,
            table_label_snapshot=table_label_snapshot,
            status=KitchenTicketStatus.QUEUED,
        )
        ticket.items = [
            KitchenTicketItem(
                dining_order_item_id=item.id,
                status=KitchenTicketItemStatus.QUEUED,
                queued_at=now,
            )
            for item in sorted(order.items, key=lambda value: (value.created_at, str(value.id)))
        ]
        self.session.add(ticket)
        await self.session.flush()
        return ticket

    async def list_tickets(
        self, outlet_id: UUID, *, status: KitchenTicketStatus | None = None
    ) -> list[KitchenTicketRead]:
        query = (
            select(KitchenTicket)
            .options(*ticket_load_options())
            .where(KitchenTicket.outlet_id == outlet_id)
            .order_by(KitchenTicket.created_at, KitchenTicket.id)
        )
        if status is not None:
            query = query.where(KitchenTicket.status == status)
        result = await self.session.execute(query)
        return [self._ticket_read(ticket) for ticket in result.scalars()]

    async def get_ticket(self, ticket_id: UUID) -> KitchenTicketRead:
        return self._ticket_read(await self._ticket(ticket_id))

    async def start_ticket(self, ticket_id: UUID) -> KitchenTicketRead:
        ticket = await self._ticket(ticket_id)
        now = self.now()
        for item in ticket.items:
            if item.status == KitchenTicketItemStatus.QUEUED:
                self._move_to_preparing(item, now)
        self._sync_aggregate(ticket, now)
        await self.session.commit()
        return await self.get_ticket(ticket.id)

    async def ready_ticket(self, ticket_id: UUID) -> KitchenTicketRead:
        ticket = await self._ticket(ticket_id)
        now = self.now()
        for item in ticket.items:
            if item.status in (
                KitchenTicketItemStatus.QUEUED,
                KitchenTicketItemStatus.PREPARING,
            ):
                self._move_to_ready(item, now)
        self._sync_aggregate(ticket, now)
        await self.session.commit()
        return await self.get_ticket(ticket.id)

    async def serve_ticket(self, ticket_id: UUID) -> KitchenTicketRead:
        ticket = await self._ticket(ticket_id)
        if any(
            item.status not in (KitchenTicketItemStatus.READY, KitchenTicketItemStatus.SERVED)
            for item in ticket.items
        ):
            raise KitchenConflict(
                "ticket has queued or preparing items", code="kitchen_ticket_not_ready"
            )
        now = self.now()
        for item in ticket.items:
            if item.status == KitchenTicketItemStatus.READY:
                self._move_to_served(item, now)
        self._sync_aggregate(ticket, now)
        await self.session.commit()
        return await self.get_ticket(ticket.id)

    async def start_item(self, ticket_item_id: UUID) -> KitchenTicketRead:
        ticket = await self._ticket_for_item(ticket_item_id)
        item = self._ticket_item(ticket, ticket_item_id)
        now = self.now()
        if item.status == KitchenTicketItemStatus.QUEUED:
            self._move_to_preparing(item, now)
        elif item.status != KitchenTicketItemStatus.PREPARING:
            raise KitchenConflict("invalid kitchen transition", code="kitchen_invalid_transition")
        self._sync_aggregate(ticket, now)
        await self.session.commit()
        return await self.get_ticket(ticket.id)

    async def ready_item(self, ticket_item_id: UUID) -> KitchenTicketRead:
        ticket = await self._ticket_for_item(ticket_item_id)
        item = self._ticket_item(ticket, ticket_item_id)
        now = self.now()
        if item.status in (KitchenTicketItemStatus.QUEUED, KitchenTicketItemStatus.PREPARING):
            self._move_to_ready(item, now)
        elif item.status != KitchenTicketItemStatus.READY:
            raise KitchenConflict("invalid kitchen transition", code="kitchen_invalid_transition")
        self._sync_aggregate(ticket, now)
        await self.session.commit()
        return await self.get_ticket(ticket.id)

    async def serve_item(self, ticket_item_id: UUID) -> KitchenTicketRead:
        ticket = await self._ticket_for_item(ticket_item_id)
        item = self._ticket_item(ticket, ticket_item_id)
        now = self.now()
        if item.status == KitchenTicketItemStatus.READY:
            self._move_to_served(item, now)
        elif item.status != KitchenTicketItemStatus.SERVED:
            raise KitchenConflict("invalid kitchen transition", code="kitchen_invalid_transition")
        self._sync_aggregate(ticket, now)
        await self.session.commit()
        return await self.get_ticket(ticket.id)

    async def _order_with_items(self, order_id: UUID) -> DiningOrder:
        order = (
            await self.session.execute(
                select(DiningOrder)
                .options(selectinload(DiningOrder.items))
                .where(DiningOrder.id == order_id)
            )
        ).scalar_one_or_none()
        if order is None:
            raise KitchenNotFound("order not found", code="kitchen_order_missing")
        return order

    async def _ticket_for_order_or_none(self, order_id: UUID) -> KitchenTicket | None:
        return (
            await self.session.execute(
                select(KitchenTicket)
                .options(*ticket_load_options())
                .where(KitchenTicket.dining_order_id == order_id)
            )
        ).scalar_one_or_none()

    async def _ticket(self, ticket_id: UUID) -> KitchenTicket:
        ticket = (
            await self.session.execute(
                select(KitchenTicket)
                .options(*ticket_load_options())
                .where(KitchenTicket.id == ticket_id)
            )
        ).scalar_one_or_none()
        if ticket is None:
            raise KitchenNotFound("kitchen ticket not found", code="kitchen_ticket_not_found")
        return ticket

    async def _ticket_for_item(self, ticket_item_id: UUID) -> KitchenTicket:
        ticket = (
            await self.session.execute(
                select(KitchenTicket)
                .join(KitchenTicketItem, KitchenTicketItem.kitchen_ticket_id == KitchenTicket.id)
                .options(*ticket_load_options())
                .where(KitchenTicketItem.id == ticket_item_id)
            )
        ).scalar_one_or_none()
        if ticket is None:
            raise KitchenNotFound("kitchen item not found", code="kitchen_item_not_found")
        return ticket

    def _ticket_item(self, ticket: KitchenTicket, ticket_item_id: UUID) -> KitchenTicketItem:
        item = next((value for value in ticket.items if value.id == ticket_item_id), None)
        if item is None:
            raise KitchenNotFound("kitchen item not found", code="kitchen_item_not_found")
        return item

    def _move_to_preparing(self, item: KitchenTicketItem, now: datetime) -> None:
        item.status = KitchenTicketItemStatus.PREPARING
        if item.started_at is None:
            item.started_at = now

    def _move_to_ready(self, item: KitchenTicketItem, now: datetime) -> None:
        item.status = KitchenTicketItemStatus.READY
        if item.ready_at is None:
            item.ready_at = now

    def _move_to_served(self, item: KitchenTicketItem, now: datetime) -> None:
        item.status = KitchenTicketItemStatus.SERVED
        if item.served_at is None:
            item.served_at = now

    def _sync_aggregate(self, ticket: KitchenTicket, now: datetime) -> None:
        item_statuses = [item.status for item in ticket.items]
        if not item_statuses or all(
            status == KitchenTicketItemStatus.QUEUED for status in item_statuses
        ):
            ticket_status = KitchenTicketStatus.QUEUED
            order_status = DiningOrderStatus.SUBMITTED
        elif all(status == KitchenTicketItemStatus.SERVED for status in item_statuses):
            ticket_status = KitchenTicketStatus.SERVED
            order_status = DiningOrderStatus.SERVED
        elif all(
            status in (KitchenTicketItemStatus.READY, KitchenTicketItemStatus.SERVED)
            for status in item_statuses
        ):
            ticket_status = KitchenTicketStatus.READY
            order_status = DiningOrderStatus.READY
        else:
            ticket_status = KitchenTicketStatus.IN_PROGRESS
            order_status = DiningOrderStatus.IN_PREPARATION

        ticket.status = ticket_status
        ticket.order.status = order_status
        if ticket_status != KitchenTicketStatus.QUEUED and ticket.started_at is None:
            ticket.started_at = now
        if ticket_status in (KitchenTicketStatus.READY, KitchenTicketStatus.SERVED):
            if ticket.ready_at is None:
                ticket.ready_at = now
        if ticket_status == KitchenTicketStatus.SERVED and ticket.served_at is None:
            ticket.served_at = now

    def _ticket_read(self, ticket: KitchenTicket) -> KitchenTicketRead:
        items = sorted(ticket.items, key=lambda value: (value.order_item.created_at, str(value.id)))
        return KitchenTicketRead(
            id=ticket.id,
            outlet_id=ticket.outlet_id,
            dining_order_id=ticket.dining_order_id,
            dining_session_id=ticket.order.dining_session_id,
            round_number=ticket.order.round_number,
            table_label_snapshot=ticket.table_label_snapshot,
            submitted_at=as_utc(ticket.order.submitted_at),
            status=ticket.status,
            created_at=as_utc(ticket.created_at),
            started_at=as_utc(ticket.started_at) if ticket.started_at else None,
            ready_at=as_utc(ticket.ready_at) if ticket.ready_at else None,
            served_at=as_utc(ticket.served_at) if ticket.served_at else None,
            items=[
                KitchenTicketItemRead(
                    id=item.id,
                    dining_order_item_id=item.dining_order_item_id,
                    dish_name_snapshot=item.order_item.dish_name_snapshot,
                    variant_name_snapshot=item.order_item.variant_name_snapshot,
                    quantity=item.order_item.quantity,
                    customer_note_snapshot=item.order_item.customer_note_snapshot,
                    modifiers=[
                        KitchenTicketItemModifierRead(
                            modifier_group_name_snapshot=modifier.modifier_group_name_snapshot,
                            modifier_option_name_snapshot=modifier.modifier_option_name_snapshot,
                        )
                        for modifier in sorted(
                            item.order_item.modifiers,
                            key=lambda value: (
                                value.modifier_group_name_snapshot,
                                value.modifier_option_name_snapshot,
                                str(value.id),
                            ),
                        )
                    ],
                    status=item.status,
                    queued_at=as_utc(item.queued_at),
                    started_at=as_utc(item.started_at) if item.started_at else None,
                    ready_at=as_utc(item.ready_at) if item.ready_at else None,
                    served_at=as_utc(item.served_at) if item.served_at else None,
                )
                for item in items
            ],
        )


def ticket_load_options() -> tuple[ExecutableOption, ...]:
    return (
        selectinload(KitchenTicket.order),
        selectinload(KitchenTicket.items)
        .selectinload(KitchenTicketItem.order_item)
        .selectinload(DiningOrderItem.modifiers),
    )


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
