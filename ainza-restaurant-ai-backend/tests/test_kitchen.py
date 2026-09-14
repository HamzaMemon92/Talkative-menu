from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.availability.models import IngredientAvailabilityOverride
from ainza_restaurant.billing.schemas import InvoiceFinalizeRequest
from ainza_restaurant.billing.service import BillingService
from ainza_restaurant.db.base import Base
from ainza_restaurant.dining.models import DiningSession, RestaurantTable
from ainza_restaurant.dining.service import DiningConflict, DiningService
from ainza_restaurant.domain.enums import (
    AvailabilityReasonCode,
    DiningOrderStatus,
    DiningSessionStartedVia,
    DiningSessionStatus,
    KitchenTicketItemStatus,
    KitchenTicketStatus,
    MenuStatus,
    MerchandisingStatus,
    OfferScopeType,
    OfferType,
    RestaurantType,
    ReviewStatus,
)
from ainza_restaurant.kitchen.models import KitchenTicket, KitchenTicketItem
from ainza_restaurant.kitchen.service import KitchenConflict, KitchenService
from ainza_restaurant.main import app
from ainza_restaurant.menu.models import (
    Category,
    Dish,
    DishIngredient,
    Ingredient,
    Menu,
    ModifierGroup,
    ModifierOption,
)
from ainza_restaurant.merchandising.models import Offer, TodaysSpecial
from ainza_restaurant.ordering.models import CartItem, DiningOrder
from ainza_restaurant.ordering.schemas import CartItemCreate, CartOfferSelect, CartSubmitRequest
from ainza_restaurant.ordering.service import CartService
from ainza_restaurant.restaurants.models import OutletTaxProfile, Restaurant, RestaurantOutlet

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


async def urban_tadka(session: AsyncSession) -> dict[str, object]:
    restaurant = Restaurant(name="Urban Tadka", slug=f"urban-tadka-{uuid4().hex}")
    session.add(restaurant)
    await session.flush()
    outlet = RestaurantOutlet(
        restaurant_id=restaurant.id,
        name="Urban Tadka - Vesu",
        address_line1="1 Vesu Road",
        city="Surat",
        state="Gujarat",
        postal_code="395007",
        timezone="Asia/Kolkata",
        currency_code="INR",
        is_primary=True,
    )
    other_outlet = RestaurantOutlet(
        restaurant_id=restaurant.id,
        name="Urban Tadka - Adajan",
        address_line1="1 Adajan Road",
        city="Surat",
        state="Gujarat",
        postal_code="395009",
        timezone="Asia/Kolkata",
    )
    session.add_all([outlet, other_outlet])
    await session.flush()
    session.add(
        OutletTaxProfile(
            outlet_id=outlet.id,
            legal_business_name="Urban Tadka Foods LLP",
            restaurant_type=RestaurantType.STANDALONE,
            gst_registered=True,
            gst_state_code="24",
            gstin="24AAAAA0000A1Z5",
            gstin_confirmed=True,
            configured_tax_rate_percent=Decimal("5.00"),
            prices_include_tax=False,
            tax_configuration_confirmed=True,
            tax_rates_confirmed=True,
            no_auto_tax_rates_confirmed=True,
        )
    )
    menu = Menu(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="Dinner",
        status=MenuStatus.PUBLISHED,
        published_at=NOW,
    )
    other_menu = Menu(
        restaurant_id=restaurant.id,
        outlet_id=other_outlet.id,
        name="Other Dinner",
        status=MenuStatus.PUBLISHED,
        published_at=NOW,
    )
    session.add_all([menu, other_menu])
    await session.flush()
    mains = Category(menu_id=menu.id, name="Mains", slug="mains")
    drinks = Category(menu_id=menu.id, name="Drinks", slug="drinks")
    other_drinks = Category(menu_id=other_menu.id, name="Drinks", slug="drinks")
    session.add_all([mains, drinks, other_drinks])
    await session.flush()
    paneer = Ingredient(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="Paneer",
        normalized_name="paneer",
    )
    session.add(paneer)
    await session.flush()
    tikka = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Paneer Tikka",
        base_price=Decimal("280.00"),
        review_status=ReviewStatus.CONFIRMED,
    )
    naan = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Butter Naan",
        base_price=Decimal("60.00"),
        review_status=ReviewStatus.CONFIRMED,
    )
    coffee = Dish(
        menu_id=menu.id,
        category_id=drinks.id,
        name="Cold Coffee",
        base_price=Decimal("140.00"),
        review_status=ReviewStatus.CONFIRMED,
    )
    brownie = Dish(
        menu_id=menu.id,
        category_id=drinks.id,
        name="Brownie",
        base_price=Decimal("180.00"),
        review_status=ReviewStatus.CONFIRMED,
    )
    biryani = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Paneer Biryani",
        base_price=Decimal("320.00"),
        review_status=ReviewStatus.CONFIRMED,
    )
    other_brownie = Dish(
        menu_id=other_menu.id,
        category_id=other_drinks.id,
        name="Brownie",
        base_price=Decimal("180.00"),
        review_status=ReviewStatus.CONFIRMED,
    )
    session.add_all([tikka, naan, coffee, brownie, biryani, other_brownie])
    await session.flush()
    extras = ModifierGroup(dish_id=tikka.id, name="Add Extras", min_selections=0, max_selections=2)
    session.add(extras)
    await session.flush()
    dip = ModifierOption(group_id=extras.id, name="Extra Dip", price_delta=Decimal("20.00"))
    session.add(dip)
    session.add(
        DishIngredient(
            dish_id=biryani.id,
            ingredient_id=paneer.id,
            is_required_for_availability=True,
        )
    )
    session.add(
        TodaysSpecial(
            outlet_id=outlet.id,
            dish_id=biryani.id,
            special_price=Decimal("279.00"),
            starts_at=NOW - timedelta(hours=1),
            ends_at=NOW + timedelta(minutes=30),
            status=MerchandisingStatus.ACTIVE,
            activation_confirmed=True,
        )
    )
    offer = Offer(
        outlet_id=outlet.id,
        name="Round Discount",
        offer_type=OfferType.FLAT,
        scope_type=OfferScopeType.ALL_ITEMS,
        status=MerchandisingStatus.ACTIVE,
        starts_at=NOW - timedelta(hours=1),
        ends_at=NOW + timedelta(hours=1),
        discount_value=Decimal("50.00"),
        activation_confirmed=True,
    )
    session.add(offer)
    table = RestaurantTable(
        outlet_id=outlet.id, label="T2", normalized_label="t2", public_qr_code="qr-t2"
    )
    other_table = RestaurantTable(
        outlet_id=other_outlet.id, label="T5", normalized_label="t5", public_qr_code="qr-t5"
    )
    session.add_all([table, other_table])
    await session.flush()
    dining_session = DiningSession(
        table_id=table.id,
        public_session_token="session-t2",
        status=DiningSessionStatus.OPEN,
        started_via=DiningSessionStartedVia.QR,
        opened_at=NOW,
    )
    other_session = DiningSession(
        table_id=other_table.id,
        public_session_token="session-t5",
        status=DiningSessionStatus.OPEN,
        started_via=DiningSessionStartedVia.QR,
        opened_at=NOW,
    )
    session.add_all([dining_session, other_session])
    await session.commit()
    return locals()


@pytest.mark.asyncio
async def test_submit_automatically_creates_one_kot_with_order_snapshots(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    cart_service = CartService(session, now=lambda: NOW)
    cart = await cart_service.add_item(
        "session-t2",
        CartItemCreate(
            dish_id=data["tikka"].id,
            quantity=2,
            modifier_option_ids=[data["dip"].id],
            customer_note="Less spicy if possible",
        ),
    )
    cart = await cart_service.add_item(
        "session-t2",
        CartItemCreate(dish_id=data["naan"].id, quantity=4, expected_version=cart.version),
    )
    cart = await cart_service.add_item(
        "session-t2",
        CartItemCreate(dish_id=data["coffee"].id, quantity=2, expected_version=cart.version),
    )
    cart = await cart_service.select_offer(
        "session-t2", CartOfferSelect(offer_id=data["offer"].id, expected_version=cart.version)
    )

    order = await cart_service.submit_cart(
        "session-t2",
        CartSubmitRequest(confirm=True, quote_token=cart.quote_token, idempotency_key="r1"),
    )
    ticket = await KitchenService(session, now=lambda: NOW).list_tickets(data["outlet"].id)

    assert order.status == DiningOrderStatus.SUBMITTED
    assert await session.scalar(select(func.count()).select_from(KitchenTicket)) == 1
    assert await session.scalar(select(func.count()).select_from(KitchenTicketItem)) == 3
    assert ticket[0].outlet_id == data["outlet"].id
    assert ticket[0].table_label_snapshot == "T2"
    assert ticket[0].round_number == 1
    assert ticket[0].status == KitchenTicketStatus.QUEUED
    assert {item.status for item in ticket[0].items} == {KitchenTicketItemStatus.QUEUED}
    assert {item.dish_name_snapshot for item in ticket[0].items} == {
        "Paneer Tikka",
        "Butter Naan",
        "Cold Coffee",
    }
    tikka = next(item for item in ticket[0].items if item.dish_name_snapshot == "Paneer Tikka")
    assert tikka.quantity == 2
    assert tikka.customer_note_snapshot == "Less spicy if possible"
    assert tikka.modifiers[0].modifier_option_name_snapshot == "Extra Dip"
    assert (await cart_service.get_cart("session-t2")).item_count == 0

    same = await cart_service.submit_cart(
        "session-t2",
        CartSubmitRequest(confirm=True, quote_token=cart.quote_token, idempotency_key="r1"),
    )
    assert same.id == order.id
    assert await session.scalar(select(func.count()).select_from(KitchenTicket)) == 1

    data["table"].label = "Renamed Table"
    data["tikka"].name = "Smoky Paneer Tikka"
    data["dip"].name = "Mint Dip"
    data["offer"].name = "Changed Offer"
    data["tikka"].base_price = Decimal("999.00")
    session.add(
        IngredientAvailabilityOverride(
            ingredient_id=data["paneer"].id,
            starts_at=NOW,
            expires_at=None,
            reason_code=AvailabilityReasonCode.OUT_OF_STOCK,
            reason_note="Future orders only",
            source_proposal_id=uuid4(),
        )
    )
    await session.commit()
    unchanged = await KitchenService(session, now=lambda: NOW + timedelta(hours=1)).get_ticket(
        ticket[0].id
    )
    unchanged_tikka = next(
        item for item in unchanged.items if item.dish_name_snapshot == "Paneer Tikka"
    )
    assert unchanged.table_label_snapshot == "T2"
    assert unchanged_tikka.modifiers[0].modifier_option_name_snapshot == "Extra Dip"


@pytest.mark.asyncio
async def test_item_transitions_aggregate_status_and_timestamps(session: AsyncSession) -> None:
    _data = await urban_tadka(session)
    cart_service = CartService(session, now=lambda: NOW)
    cart = await cart_service.add_item(
        "session-t2", CartItemCreate(dish_id=_data["tikka"].id, quantity=1)
    )
    cart = await cart_service.add_item(
        "session-t2",
        CartItemCreate(dish_id=_data["naan"].id, quantity=1, expected_version=cart.version),
    )
    cart = await cart_service.add_item(
        "session-t2",
        CartItemCreate(dish_id=_data["coffee"].id, quantity=1, expected_version=cart.version),
    )
    order = await cart_service.submit_cart(
        "session-t2",
        CartSubmitRequest(confirm=True, quote_token=cart.quote_token, idempotency_key="flow"),
    )
    ticket = (await KitchenService(session, now=lambda: NOW).list_tickets(_data["outlet"].id))[0]
    items = {item.dish_name_snapshot: item for item in ticket.items}

    at_ready = NOW + timedelta(minutes=1)
    ticket = await KitchenService(session, now=lambda: at_ready).ready_item(items["Cold Coffee"].id)
    assert ticket.status == KitchenTicketStatus.IN_PROGRESS
    first_order_status = (await cart_service.list_orders("session-t2"))[0].status
    assert first_order_status == DiningOrderStatus.IN_PREPARATION
    coffee = next(item for item in ticket.items if item.dish_name_snapshot == "Cold Coffee")
    assert coffee.ready_at == at_ready
    unchanged = await KitchenService(
        session, now=lambda: at_ready + timedelta(minutes=5)
    ).ready_item(coffee.id)
    assert next(item for item in unchanged.items if item.id == coffee.id).ready_at == at_ready

    ticket = await KitchenService(session, now=lambda: NOW + timedelta(minutes=2)).start_ticket(
        ticket.id
    )
    assert ticket.status == KitchenTicketStatus.IN_PROGRESS
    coffee_status = next(
        item for item in ticket.items if item.dish_name_snapshot == "Cold Coffee"
    ).status
    assert coffee_status == KitchenTicketItemStatus.READY
    for name in ("Paneer Tikka", "Butter Naan"):
        assert next(item for item in ticket.items if item.dish_name_snapshot == name).status == (
            KitchenTicketItemStatus.PREPARING
        )

    with pytest.raises(KitchenConflict) as serve_unready:
        await KitchenService(session, now=lambda: NOW).serve_ticket(ticket.id)
    assert serve_unready.value.code == "kitchen_ticket_not_ready"
    with pytest.raises(KitchenConflict):
        await KitchenService(session, now=lambda: NOW).start_item(coffee.id)

    ticket = await KitchenService(session, now=lambda: NOW + timedelta(minutes=3)).serve_item(
        coffee.id
    )
    assert ticket.status == KitchenTicketStatus.IN_PROGRESS
    first_order_status = (await cart_service.list_orders("session-t2"))[0].status
    assert first_order_status == DiningOrderStatus.IN_PREPARATION
    with pytest.raises(KitchenConflict):
        await KitchenService(session, now=lambda: NOW).ready_item(coffee.id)

    ticket = await KitchenService(session, now=lambda: NOW + timedelta(minutes=4)).ready_ticket(
        ticket.id
    )
    assert ticket.status == KitchenTicketStatus.READY
    assert (await cart_service.list_orders("session-t2"))[0].status == DiningOrderStatus.READY
    ticket = await KitchenService(session, now=lambda: NOW + timedelta(minutes=5)).serve_ticket(
        ticket.id
    )
    assert ticket.status == KitchenTicketStatus.SERVED
    assert {item.status for item in ticket.items} == {KitchenTicketItemStatus.SERVED}
    assert (await cart_service.list_orders("session-t2"))[0].status == DiningOrderStatus.SERVED
    stored_session = await session.get(DiningSession, order.dining_session_id)
    assert stored_session is not None
    assert stored_session.status == DiningSessionStatus.OPEN


@pytest.mark.asyncio
async def test_session_close_requires_all_rounds_served_and_cart_empty(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    cart_service = CartService(session, now=lambda: NOW)
    dining = DiningService(session, now=lambda: NOW)
    cart = await cart_service.add_item(
        "session-t2", CartItemCreate(dish_id=data["brownie"].id, quantity=1)
    )
    with pytest.raises(DiningConflict) as cart_block:
        await dining.close_session("session-t2", confirm=True)
    assert cart_block.value.code == "session_has_nonempty_cart"
    await cart_service.remove_item("session-t2", cart.items[0].id, expected_version=cart.version)

    cart = await cart_service.add_item(
        "session-t2", CartItemCreate(dish_id=data["naan"].id, quantity=1)
    )
    order1 = await cart_service.submit_cart(
        "session-t2",
        CartSubmitRequest(confirm=True, quote_token=cart.quote_token, idempotency_key="round-1"),
    )
    with pytest.raises(DiningConflict) as submitted_block:
        await dining.close_session("session-t2", confirm=True)
    assert submitted_block.value.code == "session_has_active_orders"

    ticket1 = (await KitchenService(session, now=lambda: NOW).list_tickets(data["outlet"].id))[0]
    await KitchenService(session, now=lambda: NOW).ready_ticket(ticket1.id)
    with pytest.raises(DiningConflict) as ready_block:
        await dining.close_session("session-t2", confirm=True)
    assert ready_block.value.code == "session_has_active_orders"
    await KitchenService(session, now=lambda: NOW).serve_ticket(ticket1.id)

    cart = await cart_service.add_item(
        "session-t2", CartItemCreate(dish_id=data["brownie"].id, quantity=1)
    )
    order2 = await cart_service.submit_cart(
        "session-t2",
        CartSubmitRequest(confirm=True, quote_token=cart.quote_token, idempotency_key="round-2"),
    )
    assert order1.id != order2.id
    tickets = await KitchenService(session, now=lambda: NOW).list_tickets(data["outlet"].id)
    assert len(tickets) == 2
    with pytest.raises(DiningConflict):
        await dining.close_session("session-t2", confirm=True)
    ticket2 = next(ticket for ticket in tickets if ticket.dining_order_id == order2.id)
    await KitchenService(session, now=lambda: NOW).ready_ticket(ticket2.id)
    await KitchenService(session, now=lambda: NOW).serve_ticket(ticket2.id)
    with pytest.raises(DiningConflict) as invoice_block:
        await dining.close_session("session-t2", confirm=True)
    assert invoice_block.value.code == "session_invoice_required"
    preview = await BillingService(session, now=lambda: NOW).get_preview("session-t2")
    await BillingService(session, now=lambda: NOW).finalize_invoice(
        "session-t2",
        InvoiceFinalizeRequest(
            confirm=True,
            billing_quote_token=preview.billing_quote_token,
            idempotency_key="invoice-close",
        ),
    )
    closed = await dining.close_session("session-t2", confirm=True)
    assert closed.status == DiningSessionStatus.CLOSED
    assert (await cart_service.list_orders("session-t2"))[-1].status == DiningOrderStatus.SERVED


@pytest.mark.asyncio
async def test_queue_filters_cross_outlet_reads_constraints_and_no_status_patch(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    cart_service = CartService(session, now=lambda: NOW)
    for key, dish in (("a", data["naan"]), ("b", data["brownie"])):
        cart = await cart_service.add_item(
            "session-t2", CartItemCreate(dish_id=dish.id, quantity=1)
        )
        await cart_service.submit_cart(
            "session-t2",
            CartSubmitRequest(confirm=True, quote_token=cart.quote_token, idempotency_key=key),
        )
    other_cart = await cart_service.add_item(
        "session-t5", CartItemCreate(dish_id=data["other_brownie"].id, quantity=1)
    )
    await cart_service.submit_cart(
        "session-t5",
        CartSubmitRequest(
            confirm=True, quote_token=other_cart.quote_token, idempotency_key="other"
        ),
    )

    kitchen = KitchenService(session, now=lambda: NOW)
    tickets = await kitchen.list_tickets(data["outlet"].id)
    assert len(tickets) == 2
    assert [ticket.id for ticket in tickets] == [
        ticket.id for ticket in await kitchen.list_tickets(data["outlet"].id)
    ]
    assert await kitchen.list_tickets(data["outlet"].id, status=KitchenTicketStatus.SERVED) == []
    other_tickets = await kitchen.list_tickets(data["other_outlet"].id)
    assert len(other_tickets) == 1
    detail = await kitchen.get_ticket(tickets[0].id)
    assert detail.items[0].status == KitchenTicketItemStatus.QUEUED
    assert detail == await kitchen.get_ticket(tickets[0].id)

    stored_ticket_item = await session.get(KitchenTicketItem, detail.items[0].id)
    assert stored_ticket_item is not None
    session.add(
        KitchenTicketItem(
            kitchen_ticket_id=stored_ticket_item.kitchen_ticket_id,
            dining_order_item_id=stored_ticket_item.dining_order_item_id,
            queued_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    route_paths = set(app.openapi()["paths"])
    assert "/api/v1/kitchen/tickets/{ticket_id}" in route_paths
    assert "/api/v1/orders/{order_id}/status" not in route_paths
    kitchen_or_order_paths = [
        path for path in route_paths if "/kitchen/" in path or "/orders/" in path
    ]
    assert all("cancel" not in path for path in kitchen_or_order_paths)


@pytest.mark.asyncio
async def test_kot_creation_failure_rolls_back_order_and_preserves_cart(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = await urban_tadka(session)
    cart_service = CartService(session, now=lambda: NOW)
    cart = await cart_service.add_item(
        "session-t2", CartItemCreate(dish_id=data["naan"].id, quantity=2)
    )

    async def fail_create(*_args: object, **_kwargs: object) -> KitchenTicket:
        raise RuntimeError("forced KOT failure")

    monkeypatch.setattr(KitchenService, "create_ticket_for_order", fail_create)
    with pytest.raises(RuntimeError, match="forced KOT failure"):
        await cart_service.submit_cart(
            "session-t2",
            CartSubmitRequest(confirm=True, quote_token=cart.quote_token, idempotency_key="boom"),
        )

    assert await session.scalar(select(func.count()).select_from(DiningOrder)) == 0
    assert await session.scalar(select(func.count()).select_from(KitchenTicket)) == 0
    assert await session.scalar(select(func.count()).select_from(KitchenTicketItem)) == 0
    assert await session.scalar(select(func.count()).select_from(CartItem)) == 1


@pytest.mark.asyncio
async def test_kitchen_queue_avoids_obvious_n_plus_one() -> None:
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
            data = await urban_tadka(db)
            cart_service = CartService(db, now=lambda: NOW)
            for index in range(12):
                cart = await cart_service.add_item(
                    "session-t2", CartItemCreate(dish_id=data["naan"].id, quantity=1)
                )
                await cart_service.submit_cart(
                    "session-t2",
                    CartSubmitRequest(
                        confirm=True,
                        quote_token=cart.quote_token,
                        idempotency_key=f"order-{index}",
                    ),
                )
            statements = 0
            tickets = await KitchenService(db, now=lambda: NOW).list_tickets(data["outlet"].id)
            assert len(tickets) == 12
            assert statements < 8
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()
