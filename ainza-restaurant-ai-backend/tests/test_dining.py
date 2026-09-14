from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.availability.models import IngredientAvailabilityOverride
from ainza_restaurant.customer_menu.service import CustomerMenuService
from ainza_restaurant.db.base import Base
from ainza_restaurant.dining.models import DiningSession, RestaurantTable
from ainza_restaurant.dining.schemas import (
    ConfirmRequest,
    ManualSessionStartRequest,
    SessionStartRequest,
    TableCreate,
    TablePatch,
)
from ainza_restaurant.dining.service import DiningConflict, DiningNotFound, DiningService
from ainza_restaurant.domain.enums import (
    AvailabilityReasonCode,
    DiningSessionStartedVia,
    DiningSessionStatus,
    MenuStatus,
    RestaurantStatus,
    ReviewStatus,
)
from ainza_restaurant.menu.models import Category, Dish, DishIngredient, Ingredient, Menu
from ainza_restaurant.restaurants.models import Restaurant, RestaurantOutlet

NOW = datetime(2026, 9, 10, 14, 30, tzinfo=UTC)


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        yield db
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _urban_tadka(session: AsyncSession) -> dict[str, object]:
    restaurant = Restaurant(name="Urban Tadka", slug=f"urban-tadka-{uuid4().hex}")
    inactive_restaurant = Restaurant(
        name="Inactive Brand",
        slug=f"inactive-brand-{uuid4().hex}",
        status=RestaurantStatus.INACTIVE,
    )
    session.add_all([restaurant, inactive_restaurant])
    await session.flush()
    outlet = RestaurantOutlet(
        restaurant_id=restaurant.id,
        name="Urban Tadka - Vesu",
        address_line1="1 Vesu Road",
        city="Surat",
        state="Gujarat",
        postal_code="395007",
        timezone="Asia/Kolkata",
        is_primary=True,
    )
    second_outlet = RestaurantOutlet(
        restaurant_id=restaurant.id,
        name="Urban Tadka - Adajan",
        address_line1="1 Adajan Road",
        city="Surat",
        state="Gujarat",
        postal_code="395009",
        timezone="Asia/Kolkata",
    )
    inactive_outlet = RestaurantOutlet(
        restaurant_id=restaurant.id,
        name="Inactive Outlet",
        address_line1="2 Vesu Road",
        city="Surat",
        state="Gujarat",
        postal_code="395007",
        timezone="Asia/Kolkata",
        is_active=False,
    )
    inactive_brand_outlet = RestaurantOutlet(
        restaurant_id=inactive_restaurant.id,
        name="Inactive Brand Outlet",
        address_line1="3 Vesu Road",
        city="Surat",
        state="Gujarat",
        postal_code="395007",
        timezone="Asia/Kolkata",
    )
    session.add_all([outlet, second_outlet, inactive_outlet, inactive_brand_outlet])
    await session.flush()
    menu = Menu(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="Dinner",
        status=MenuStatus.PUBLISHED,
        published_at=NOW,
    )
    draft_menu = Menu(restaurant_id=restaurant.id, outlet_id=outlet.id, name="Draft")
    session.add_all([menu, draft_menu])
    await session.flush()
    category = Category(menu_id=menu.id, name="Main Course", slug="main-course")
    paneer = Ingredient(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="Paneer",
        normalized_name="paneer",
    )
    session.add_all([category, paneer])
    await session.flush()
    biryani = Dish(
        menu_id=menu.id,
        category_id=category.id,
        name="Paneer Biryani",
        base_price=Decimal("320.00"),
        review_status=ReviewStatus.CONFIRMED,
    )
    pending = Dish(
        menu_id=menu.id,
        category_id=category.id,
        name="Pending Paneer Roll",
        base_price=Decimal("120.00"),
        review_status=ReviewStatus.PENDING_REVIEW,
    )
    draft_dish = Dish(
        menu_id=draft_menu.id,
        name="Draft Dish",
        base_price=Decimal("100.00"),
        review_status=ReviewStatus.CONFIRMED,
    )
    session.add_all([biryani, pending, draft_dish])
    await session.flush()
    session.add(
        DishIngredient(
            dish_id=biryani.id,
            ingredient_id=paneer.id,
            is_required_for_availability=True,
        )
    )
    await session.commit()
    return locals()


@pytest.mark.asyncio
async def test_table_lifecycle_qr_rotation_and_resolution(session: AsyncSession) -> None:
    data = await _urban_tadka(session)
    service = DiningService(session, now=lambda: NOW)
    second_outlet_id = data["second_outlet"].id
    t1 = await service.create_table(
        data["outlet"].id,
        TableCreate(label=" T1 ", area_name=" Main Hall ", capacity=4),
    )
    t2 = await service.create_table(data["outlet"].id, TableCreate(label="T2", display_order=2))
    patio = await service.create_table(
        data["outlet"].id, TableCreate(label="Patio 1", capacity=None, display_order=3)
    )
    family = await service.create_table(
        data["outlet"].id, TableCreate(label="Family Cabin", display_order=4)
    )

    assert t1.label == "T1"
    assert t1.capacity == 4
    assert t2.capacity is None
    assert t1.is_active is True
    assert len(t1.public_qr_code) > 30
    assert str(t1.id) not in t1.public_qr_code
    assert (
        len({t1.public_qr_code, t2.public_qr_code, patio.public_qr_code, family.public_qr_code})
        == 4
    )
    assert [table.label for table in await service.list_tables(data["outlet"].id)] == [
        "T1",
        "T2",
        "Patio 1",
        "Family Cabin",
    ]

    with pytest.raises(DiningConflict) as duplicate:
        await service.create_table(data["outlet"].id, TableCreate(label="  t1 "))
    assert duplicate.value.code == "duplicate_table_label"
    same_label_other_outlet = await service.create_table(second_outlet_id, TableCreate(label="T1"))
    assert same_label_other_outlet.outlet_id == second_outlet_id

    patched = await service.patch_table(
        t1.id, TablePatch(area_name=None, capacity=None, display_order=5)
    )
    assert patched.area_name is None
    assert patched.capacity is None
    assert patched.public_qr_code == t1.public_qr_code

    resolution = await service.resolve_qr(t1.public_qr_code)
    assert resolution.restaurant.name == "Urban Tadka"
    assert resolution.outlet.name == "Urban Tadka - Vesu"
    assert resolution.table.label == "T1"
    assert resolution.customer_menu.route == f"/api/v1/outlets/{data['outlet'].id}/customer-menu"
    assert resolution.customer_menu.available is True
    assert resolution.template_id is None
    assert resolution.frontend_url is None

    with pytest.raises(DiningConflict) as no_confirm:
        await service.rotate_qr(t1.id, confirm=False)
    assert no_confirm.value.code == "qr_confirmation_required"
    rotated = await service.rotate_qr(t1.id, confirm=True)
    assert rotated.public_qr_code != t1.public_qr_code
    with pytest.raises(DiningNotFound) as old_code:
        await service.resolve_qr(t1.public_qr_code)
    assert old_code.value.code == "qr_not_found"
    assert (await service.resolve_qr(rotated.public_qr_code)).table.label == "T1"

    inactive_table = await service.patch_table(t2.id, TablePatch(is_active=False))
    with pytest.raises(DiningNotFound) as inactive_qr:
        await service.resolve_qr(inactive_table.public_qr_code)
    assert inactive_qr.value.code == "qr_not_available"


@pytest.mark.asyncio
async def test_qr_session_join_close_and_new_party_flow(session: AsyncSession) -> None:
    data = await _urban_tadka(session)
    service = DiningService(session, now=lambda: NOW)
    table = await service.create_table(data["outlet"].id, TableCreate(label="T2"))

    start = await service.start_session_from_qr(
        table.public_qr_code, SessionStartRequest(party_size=4)
    )
    assert start.joined_existing is False
    assert start.session.status == DiningSessionStatus.OPEN
    assert start.session.started_via == DiningSessionStartedVia.QR
    assert start.session.party_size == 4
    assert len(start.session.public_session_token) > 30
    assert start.session.customer_menu.available is True

    with pytest.raises(DiningConflict) as duplicate:
        await service.start_session_from_qr(table.public_qr_code, SessionStartRequest())
    assert duplicate.value.code == "table_session_already_open"
    joined = await service.start_session_from_qr(
        table.public_qr_code, SessionStartRequest(join_existing=True)
    )
    assert joined.joined_existing is True
    assert joined.session.public_session_token == start.session.public_session_token
    assert await session.scalar(select(func.count()).select_from(DiningSession)) == 1

    read = await service.get_session(start.session.public_session_token)
    assert read.table.label == "T2"
    assert (await service.active_session_for_table(table.id)).session is not None
    with pytest.raises(DiningNotFound) as missing:
        await service.get_session("missing-token")
    assert missing.value.code == "dining_session_not_found"

    with pytest.raises(DiningConflict) as close_without_confirm:
        await service.close_session(start.session.public_session_token, confirm=False)
    assert close_without_confirm.value.code == "session_confirmation_required"
    closed = await service.close_session(start.session.public_session_token, confirm=True)
    assert closed.status == DiningSessionStatus.CLOSED
    assert closed.closed_at == NOW
    second_close = await service.close_session(start.session.public_session_token, confirm=True)
    assert second_close.closed_at == closed.closed_at
    assert (await service.active_session_for_table(table.id)).session is None

    new_party = await service.start_session_from_qr(table.public_qr_code, SessionStartRequest())
    assert new_party.session.status == DiningSessionStatus.OPEN
    assert new_party.session.public_session_token != start.session.public_session_token
    assert await session.scalar(select(func.count()).select_from(DiningSession)) == 2


@pytest.mark.asyncio
async def test_manual_session_table_deactivation_and_customer_menu_integration(
    session: AsyncSession,
) -> None:
    data = await _urban_tadka(session)
    service = DiningService(session, now=lambda: NOW)
    table = await service.create_table(data["outlet"].id, TableCreate(label="Family Cabin"))
    active_none = await service.active_session_for_table(table.id)
    assert active_none.session is None

    manual = await service.start_manual_session(
        table.id, ManualSessionStartRequest(party_size=None)
    )
    assert manual.session.started_via == DiningSessionStartedVia.MANUAL
    assert manual.session.party_size is None
    with pytest.raises(DiningConflict) as deactivate_open:
        await service.patch_table(table.id, TablePatch(is_active=False))
    assert deactivate_open.value.code == "table_has_open_session"

    session.add(
        IngredientAvailabilityOverride(
            ingredient_id=data["paneer"].id,
            starts_at=NOW,
            expires_at=None,
            reason_code=AvailabilityReasonCode.OUT_OF_STOCK,
            reason_note="Internal owner note",
            source_proposal_id=uuid4(),
        )
    )
    await session.commit()
    menu = await CustomerMenuService(session, now=lambda: NOW).get_menu(data["outlet"].id)
    dishes = [dish for category in menu.categories for dish in category.dishes]
    assert [dish.name for dish in dishes] == ["Paneer Biryani"]
    assert dishes[0].available is False
    assert "Internal owner note" not in menu.model_dump_json()

    await service.close_session(manual.session.public_session_token, confirm=True)
    deactivated = await service.patch_table(table.id, TablePatch(is_active=False))
    assert deactivated.is_active is False
    with pytest.raises(DiningNotFound) as inactive_start:
        await service.start_session_from_qr(table.public_qr_code, SessionStartRequest())
    assert inactive_start.value.code == "qr_not_available"


@pytest.mark.asyncio
async def test_database_integrity_and_cross_outlet_safety(session: AsyncSession) -> None:
    data = await _urban_tadka(session)
    service = DiningService(session, now=lambda: NOW)
    inactive_outlet_id = data["inactive_outlet"].id
    inactive_brand_outlet_id = data["inactive_brand_outlet"].id
    table = await service.create_table(data["outlet"].id, TableCreate(label="T1"))
    other = await service.create_table(data["second_outlet"].id, TableCreate(label="T1"))
    table_id = table.id
    other_table_id = other.id
    assert table.outlet_id != other.outlet_id

    first = DiningSession(
        table_id=table_id,
        public_session_token="token-one",
        status=DiningSessionStatus.OPEN,
        started_via=DiningSessionStartedVia.MANUAL,
        opened_at=NOW,
    )
    second = DiningSession(
        table_id=table_id,
        public_session_token="token-two",
        status=DiningSessionStatus.OPEN,
        started_via=DiningSessionStartedVia.MANUAL,
        opened_at=NOW,
    )
    session.add_all([first, second])
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    session.add(
        DiningSession(
            table_id=table_id,
            public_session_token="same-token",
            status=DiningSessionStatus.OPEN,
            started_via=DiningSessionStartedVia.MANUAL,
            opened_at=NOW,
        )
    )
    session.add(
        DiningSession(
            table_id=other_table_id,
            public_session_token="same-token",
            status=DiningSessionStatus.OPEN,
            started_via=DiningSessionStartedVia.MANUAL,
            opened_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    inactive_outlet_table = RestaurantTable(
        outlet_id=inactive_outlet_id,
        label="Hidden",
        normalized_label="hidden",
        public_qr_code="inactive-outlet-qr",
    )
    inactive_restaurant_table = RestaurantTable(
        outlet_id=inactive_brand_outlet_id,
        label="Hidden",
        normalized_label="hidden",
        public_qr_code="inactive-brand-qr",
    )
    session.add_all([inactive_outlet_table, inactive_restaurant_table])
    await session.commit()
    with pytest.raises(DiningNotFound) as inactive_outlet:
        await service.resolve_qr("inactive-outlet-qr")
    assert inactive_outlet.value.code == "qr_not_available"
    with pytest.raises(DiningNotFound) as inactive_brand:
        await service.resolve_qr("inactive-brand-qr")
    assert inactive_brand.value.code == "qr_not_available"


@pytest.mark.asyncio
async def test_table_list_open_session_state_avoids_obvious_n_plus_one() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    statements = 0

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def count_queries(*_args: object) -> None:
        nonlocal statements
        statements += 1

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            data = await _urban_tadka(db)
            service = DiningService(db, now=lambda: NOW)
            for index in range(60):
                await service.create_table(
                    data["outlet"].id,
                    TableCreate(label=f"T{index + 1}", display_order=index),
                )
            statements = 0
            tables = await service.list_tables(data["outlet"].id)
            assert len(tables) == 60
            assert statements < 8
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


def test_task007_payload_schemas_exclude_template_and_cart_order_fields() -> None:
    assert "template" not in "\n".join(RestaurantTable.__table__.columns.keys())
    assert "cart" not in "\n".join(DiningSession.__table__.columns.keys())
    assert "order" not in "\n".join(DiningSession.__table__.columns.keys())
    assert ConfirmRequest(confirm=True).confirm is True
