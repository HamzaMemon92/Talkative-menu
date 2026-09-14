from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.billing.models import DiningInvoice
from ainza_restaurant.customer_menu.service import CustomerMenuNotFound, CustomerMenuService
from ainza_restaurant.dining.models import DiningSession, RestaurantTable
from ainza_restaurant.dining.schemas import (
    ActiveSessionRead,
    CustomerMenuContext,
    DiningSessionRead,
    ManualSessionStartRequest,
    PublicOutletContext,
    PublicRestaurantContext,
    PublicTableContext,
    QRResolutionRead,
    SessionStartRead,
    SessionStartRequest,
    TableCreate,
    TablePatch,
    TableRead,
)
from ainza_restaurant.domain.enums import (
    DiningOrderStatus,
    DiningSessionStartedVia,
    DiningSessionStatus,
    RestaurantStatus,
)
from ainza_restaurant.ordering.models import CartItem, DiningCart, DiningOrder
from ainza_restaurant.restaurants.models import Restaurant, RestaurantOutlet


class DiningNotFound(LookupError):
    code = "table_not_found"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class DiningConflict(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "dining_conflict",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class DiningService:
    def __init__(self, session: AsyncSession, *, now: Callable[[], datetime] | None = None) -> None:
        self.session = session
        self._now = now or (lambda: datetime.now(UTC))

    def now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    async def create_table(self, outlet_id: UUID, data: TableCreate) -> TableRead:
        await self._active_outlet(outlet_id)
        table = RestaurantTable(
            outlet_id=outlet_id,
            label=data.label,
            normalized_label=normalize_label(data.label),
            area_name=data.area_name,
            capacity=data.capacity,
            display_order=data.display_order,
            is_active=data.is_active,
            public_qr_code=await self._unique_qr_code(),
        )
        self.session.add(table)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise DiningConflict(
                "duplicate active table label", code="duplicate_table_label"
            ) from exc
        await self.session.refresh(table)
        return await self.get_table(table.id)

    async def list_tables(self, outlet_id: UUID) -> list[TableRead]:
        await self._outlet(outlet_id)
        result = await self.session.execute(
            select(RestaurantTable)
            .where(RestaurantTable.outlet_id == outlet_id)
            .order_by(RestaurantTable.display_order, RestaurantTable.label, RestaurantTable.id)
        )
        tables = list(result.scalars())
        open_ids = await self._open_session_table_ids([table.id for table in tables])
        return [self._table_read(table, table.id in open_ids) for table in tables]

    async def get_table(self, table_id: UUID) -> TableRead:
        table = await self._table(table_id)
        return self._table_read(table, await self._has_open_session(table.id))

    async def patch_table(self, table_id: UUID, data: TablePatch) -> TableRead:
        table = await self._table(table_id)
        values = data.model_dump(exclude_unset=True)
        if values.get("label") is not None:
            table.label = values["label"]
            table.normalized_label = normalize_label(values["label"])
        if "area_name" in values:
            table.area_name = values["area_name"]
        if "capacity" in values:
            table.capacity = values["capacity"]
        if "display_order" in values:
            table.display_order = values["display_order"]
        if "is_active" in values:
            if values["is_active"] is False and await self._has_open_session(table.id):
                raise DiningConflict("table has an open session", code="table_has_open_session")
            table.is_active = values["is_active"]
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise DiningConflict(
                "duplicate active table label", code="duplicate_table_label"
            ) from exc
        await self.session.refresh(table)
        return await self.get_table(table.id)

    async def rotate_qr(self, table_id: UUID, *, confirm: bool) -> TableRead:
        if not confirm:
            raise DiningConflict(
                "QR rotation requires confirm=true", code="qr_confirmation_required"
            )
        table = await self._table(table_id)
        table.public_qr_code = await self._unique_qr_code()
        table.qr_code_rotated_at = self.now()
        await self.session.commit()
        await self.session.refresh(table)
        return await self.get_table(table.id)

    async def resolve_qr(self, public_qr_code: str) -> QRResolutionRead:
        table, outlet, restaurant = await self._table_context_for_qr(public_qr_code)
        active = await self._active_session_for_table(table.id)
        return QRResolutionRead(
            restaurant=PublicRestaurantContext(id=restaurant.id, name=restaurant.name),
            outlet=PublicOutletContext(id=outlet.id, name=outlet.name, timezone=outlet.timezone),
            table=self._public_table(table),
            customer_menu=await self._customer_menu_context(outlet.id),
            current_session_exists=active is not None,
            active_session_token=active.public_session_token if active else None,
        )

    async def start_session_from_qr(
        self, public_qr_code: str, data: SessionStartRequest
    ) -> SessionStartRead:
        table, outlet, _restaurant = await self._table_context_for_qr(public_qr_code)
        return await self._start_session(
            table,
            outlet,
            party_size=data.party_size,
            join_existing=data.join_existing,
            started_via=DiningSessionStartedVia.QR,
        )

    async def start_manual_session(
        self, table_id: UUID, data: ManualSessionStartRequest
    ) -> SessionStartRead:
        table, outlet, _restaurant = await self._active_table_context(table_id)
        return await self._start_session(
            table,
            outlet,
            party_size=data.party_size,
            join_existing=False,
            started_via=DiningSessionStartedVia.MANUAL,
        )

    async def get_session(self, public_session_token: str) -> DiningSessionRead:
        session = await self._session_by_token(public_session_token)
        table, outlet, _restaurant = await self._table_context(session.table_id)
        return await self._session_read(session, table, outlet)

    async def active_session_for_table(self, table_id: UUID) -> ActiveSessionRead:
        table, outlet, _restaurant = await self._table_context(table_id)
        session = await self._active_session_for_table(table.id)
        return ActiveSessionRead(
            table_id=table.id,
            session=await self._session_read(session, table, outlet) if session else None,
        )

    async def close_session(self, public_session_token: str, *, confirm: bool) -> DiningSessionRead:
        if not confirm:
            raise DiningConflict(
                "session close requires confirm=true", code="session_confirmation_required"
            )
        session = await self._session_by_token(public_session_token)
        table, outlet, _restaurant = await self._table_context(session.table_id)
        if session.status == DiningSessionStatus.CLOSED:
            return await self._session_read(session, table, outlet)
        cart_items = await self.session.scalar(
            select(func.count())
            .select_from(CartItem)
            .join(DiningCart, DiningCart.id == CartItem.cart_id)
            .where(DiningCart.dining_session_id == session.id)
        )
        if cart_items:
            raise DiningConflict("session has nonempty cart", code="session_has_nonempty_cart")
        active_orders = await self.session.scalar(
            select(func.count())
            .select_from(DiningOrder)
            .where(
                DiningOrder.dining_session_id == session.id,
                DiningOrder.status != DiningOrderStatus.SERVED,
            )
        )
        if active_orders:
            raise DiningConflict("session has active orders", code="session_has_active_orders")
        orders_count = await self.session.scalar(
            select(func.count())
            .select_from(DiningOrder)
            .where(DiningOrder.dining_session_id == session.id)
        )
        if orders_count:
            invoice_id = await self.session.scalar(
                select(DiningInvoice.id).where(DiningInvoice.dining_session_id == session.id)
            )
            if invoice_id is None:
                raise DiningConflict(
                    "session requires finalized invoice",
                    code="session_invoice_required",
                )
        session.status = DiningSessionStatus.CLOSED
        session.closed_at = self.now()
        await self.session.commit()
        await self.session.refresh(session)
        return await self._session_read(session, table, outlet)

    async def _start_session(
        self,
        table: RestaurantTable,
        outlet: RestaurantOutlet,
        *,
        party_size: int | None,
        join_existing: bool,
        started_via: DiningSessionStartedVia,
    ) -> SessionStartRead:
        table_id = table.id
        outlet_id = outlet.id
        existing = await self._active_session_for_table(table_id)
        if existing is not None:
            if not join_existing:
                raise DiningConflict(
                    "table already has an open session", code="table_session_already_open"
                )
            return SessionStartRead(
                session=await self._session_read(existing, table, outlet),
                joined_existing=True,
            )
        now = self.now()
        new_session = DiningSession(
            table_id=table_id,
            public_session_token=await self._unique_session_token(),
            status=DiningSessionStatus.OPEN,
            party_size=party_size,
            started_via=started_via,
            opened_at=now,
        )
        self.session.add(new_session)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            existing_after_race = await self._active_session_for_table(table_id)
            if existing_after_race is not None and join_existing:
                table_after_race = await self._table(table_id)
                outlet_after_race = await self._outlet(outlet_id)
                return SessionStartRead(
                    session=await self._session_read(
                        existing_after_race, table_after_race, outlet_after_race
                    ),
                    joined_existing=True,
                )
            raise DiningConflict(
                "table already has an open session", code="table_session_already_open"
            ) from exc
        await self.session.refresh(new_session)
        return SessionStartRead(
            session=await self._session_read(new_session, table, outlet),
            joined_existing=False,
        )

    async def _active_outlet(self, outlet_id: UUID) -> RestaurantOutlet:
        outlet = await self._outlet(outlet_id)
        restaurant_status = getattr(outlet.restaurant.status, "value", outlet.restaurant.status)
        if not outlet.is_active or restaurant_status != RestaurantStatus.ACTIVE.value:
            raise DiningConflict("outlet is not active", code="table_wrong_outlet")
        return outlet

    async def _outlet(self, outlet_id: UUID) -> RestaurantOutlet:
        result = await self.session.execute(
            select(RestaurantOutlet, Restaurant)
            .join(Restaurant, Restaurant.id == RestaurantOutlet.restaurant_id)
            .where(RestaurantOutlet.id == outlet_id)
        )
        row = result.one_or_none()
        if row is None:
            raise DiningNotFound("outlet not found", code="table_not_found")
        outlet, restaurant = row
        outlet = cast(RestaurantOutlet, outlet)
        restaurant = cast(Restaurant, restaurant)
        outlet.restaurant = restaurant
        return outlet

    async def _table(self, table_id: UUID) -> RestaurantTable:
        table = await self.session.get(RestaurantTable, table_id)
        if table is None:
            raise DiningNotFound("table not found", code="table_not_found")
        return table

    async def _active_table_context(
        self, table_id: UUID
    ) -> tuple[RestaurantTable, RestaurantOutlet, Restaurant]:
        table, outlet, restaurant = await self._table_context(table_id)
        if not table.is_active:
            raise DiningConflict("table is inactive", code="qr_not_available")
        restaurant_status = getattr(restaurant.status, "value", restaurant.status)
        if not outlet.is_active or restaurant_status != RestaurantStatus.ACTIVE.value:
            raise DiningConflict("table is not available", code="qr_not_available")
        return table, outlet, restaurant

    async def _table_context(
        self, table_id: UUID
    ) -> tuple[RestaurantTable, RestaurantOutlet, Restaurant]:
        result = await self.session.execute(
            select(RestaurantTable, RestaurantOutlet, Restaurant)
            .join(RestaurantOutlet, RestaurantOutlet.id == RestaurantTable.outlet_id)
            .join(Restaurant, Restaurant.id == RestaurantOutlet.restaurant_id)
            .where(RestaurantTable.id == table_id)
        )
        row = result.one_or_none()
        if row is None:
            raise DiningNotFound("table not found", code="table_not_found")
        table, outlet, restaurant = row
        return table, outlet, restaurant

    async def _table_context_for_qr(
        self, public_qr_code: str
    ) -> tuple[RestaurantTable, RestaurantOutlet, Restaurant]:
        result = await self.session.execute(
            select(RestaurantTable, RestaurantOutlet, Restaurant)
            .join(RestaurantOutlet, RestaurantOutlet.id == RestaurantTable.outlet_id)
            .join(Restaurant, Restaurant.id == RestaurantOutlet.restaurant_id)
            .where(RestaurantTable.public_qr_code == public_qr_code)
        )
        row = result.one_or_none()
        if row is None:
            raise DiningNotFound("QR code not found", code="qr_not_found")
        table, outlet, restaurant = row
        restaurant_status = getattr(restaurant.status, "value", restaurant.status)
        if (
            not table.is_active
            or not outlet.is_active
            or restaurant_status != RestaurantStatus.ACTIVE.value
        ):
            raise DiningNotFound("QR code is not available", code="qr_not_available")
        return table, outlet, restaurant

    async def _active_session_for_table(self, table_id: UUID) -> DiningSession | None:
        return (
            await self.session.execute(
                select(DiningSession).where(
                    DiningSession.table_id == table_id,
                    DiningSession.status == DiningSessionStatus.OPEN,
                )
            )
        ).scalar_one_or_none()

    async def _has_open_session(self, table_id: UUID) -> bool:
        return await self._active_session_for_table(table_id) is not None

    async def _open_session_table_ids(self, table_ids: list[UUID]) -> set[UUID]:
        if not table_ids:
            return set()
        result = await self.session.execute(
            select(DiningSession.table_id).where(
                DiningSession.table_id.in_(table_ids),
                DiningSession.status == DiningSessionStatus.OPEN,
            )
        )
        return set(result.scalars())

    async def _session_by_token(self, public_session_token: str) -> DiningSession:
        session = (
            await self.session.execute(
                select(DiningSession).where(
                    DiningSession.public_session_token == public_session_token
                )
            )
        ).scalar_one_or_none()
        if session is None:
            raise DiningNotFound("dining session not found", code="dining_session_not_found")
        return session

    async def _customer_menu_context(self, outlet_id: UUID) -> CustomerMenuContext:
        route = f"/api/v1/outlets/{outlet_id}/customer-menu"
        try:
            await CustomerMenuService(self.session, now=self._now).get_menu(outlet_id)
            available = True
        except CustomerMenuNotFound:
            available = False
        return CustomerMenuContext(available=available, outlet_id=outlet_id, route=route)

    async def _session_read(
        self, session: DiningSession, table: RestaurantTable, outlet: RestaurantOutlet
    ) -> DiningSessionRead:
        return DiningSessionRead(
            id=session.id,
            public_session_token=session.public_session_token,
            status=session.status,
            party_size=session.party_size,
            started_via=session.started_via,
            opened_at=as_utc(session.opened_at),
            closed_at=as_utc(session.closed_at) if session.closed_at else None,
            table=self._public_table(table),
            outlet=PublicOutletContext(id=outlet.id, name=outlet.name, timezone=outlet.timezone),
            customer_menu=await self._customer_menu_context(outlet.id),
        )

    def _table_read(self, table: RestaurantTable, has_open_session: bool) -> TableRead:
        return TableRead(
            id=table.id,
            outlet_id=table.outlet_id,
            label=table.label,
            area_name=table.area_name,
            capacity=table.capacity,
            display_order=table.display_order,
            is_active=table.is_active,
            public_qr_code=table.public_qr_code,
            qr_code_rotated_at=table.qr_code_rotated_at,
            has_open_session=has_open_session,
            created_at=table.created_at,
            updated_at=table.updated_at,
        )

    def _public_table(self, table: RestaurantTable) -> PublicTableContext:
        return PublicTableContext(
            id=table.id,
            label=table.label,
            area_name=table.area_name,
            capacity=table.capacity,
        )

    async def _unique_qr_code(self) -> str:
        for _ in range(10):
            token = secrets.token_urlsafe(32)
            exists = (
                await self.session.execute(
                    select(RestaurantTable.public_qr_code).where(
                        RestaurantTable.public_qr_code == token
                    )
                )
            ).first()
            if exists is None:
                return token
        raise DiningConflict("could not generate unique QR code", code="token_generation_failed")

    async def _unique_session_token(self) -> str:
        for _ in range(10):
            token = secrets.token_urlsafe(32)
            exists = (
                await self.session.execute(
                    select(DiningSession.public_session_token).where(
                        DiningSession.public_session_token == token
                    )
                )
            ).first()
            if exists is None:
                return token
        raise DiningConflict(
            "could not generate unique session token", code="token_generation_failed"
        )


def normalize_label(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
