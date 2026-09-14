from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.billing.models import (
    DiningInvoice,
    DiningInvoiceLine,
    DiningInvoiceOrder,
)
from ainza_restaurant.billing.schemas import InvoiceFinalizeRequest
from ainza_restaurant.billing.service import BillingConflict, BillingService
from ainza_restaurant.db.base import Base
from ainza_restaurant.dining.models import DiningSession, RestaurantTable
from ainza_restaurant.dining.service import DiningConflict, DiningService
from ainza_restaurant.domain.enums import (
    DiningSessionStartedVia,
    DiningSessionStatus,
    MenuStatus,
    MerchandisingStatus,
    OfferScopeType,
    OfferType,
    RestaurantType,
    ReviewStatus,
)
from ainza_restaurant.kitchen.service import KitchenService
from ainza_restaurant.main import app
from ainza_restaurant.menu.models import Category, Dish, Menu, ModifierGroup, ModifierOption
from ainza_restaurant.merchandising.models import Offer
from ainza_restaurant.ordering.schemas import (
    CartItemCreate,
    CartOfferSelect,
    CartSubmitRequest,
)
from ainza_restaurant.ordering.service import CartConflict, CartService
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


async def restaurant_fixture(
    session: AsyncSession, *, prices_include_tax: bool = False, tax_rate: str = "5.00"
) -> dict[str, object]:
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
    session.add(outlet)
    await session.flush()
    tax_profile = OutletTaxProfile(
        outlet_id=outlet.id,
        legal_business_name="Urban Tadka Foods LLP",
        restaurant_type=RestaurantType.STANDALONE,
        gst_registered=True,
        gst_state_code="24",
        gstin="24AAAAA0000A1Z5",
        gstin_confirmed=True,
        configured_tax_rate_percent=Decimal(tax_rate),
        prices_include_tax=prices_include_tax,
        tax_configuration_confirmed=True,
        tax_rates_confirmed=True,
        no_auto_tax_rates_confirmed=True,
    )
    menu = Menu(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="Dinner",
        status=MenuStatus.PUBLISHED,
        published_at=NOW,
    )
    session.add_all([tax_profile, menu])
    await session.flush()
    mains = Category(menu_id=menu.id, name="Mains", slug="mains")
    session.add(mains)
    await session.flush()
    tikka = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Paneer Tikka",
        base_price=Decimal("280.00"),
        review_status=ReviewStatus.CONFIRMED,
        tax_category_code="GST_FOOD",
    )
    naan = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Butter Naan",
        base_price=Decimal("60.00"),
        review_status=ReviewStatus.CONFIRMED,
    )
    thali = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Inclusive Thali",
        base_price=Decimal("1050.00"),
        review_status=ReviewStatus.CONFIRMED,
    )
    session.add_all([tikka, naan, thali])
    await session.flush()
    extras = ModifierGroup(dish_id=tikka.id, name="Add Extras", min_selections=0, max_selections=1)
    session.add(extras)
    await session.flush()
    dip = ModifierOption(group_id=extras.id, name="Extra Dip", price_delta=Decimal("20.00"))
    offer = Offer(
        outlet_id=outlet.id,
        name="Round Discount",
        offer_type=OfferType.FLAT,
        scope_type=OfferScopeType.ALL_ITEMS,
        status=MerchandisingStatus.ACTIVE,
        starts_at=NOW - timedelta(hours=1),
        ends_at=NOW + timedelta(hours=1),
        discount_value=Decimal("100.00"),
        activation_confirmed=True,
    )
    table = RestaurantTable(
        outlet_id=outlet.id,
        label="T1",
        normalized_label="t1",
        public_qr_code=f"qr-{uuid4().hex}",
    )
    session.add_all([dip, offer, table])
    await session.flush()
    dining_session = DiningSession(
        table_id=table.id,
        public_session_token=f"session-{uuid4().hex}",
        status=DiningSessionStatus.OPEN,
        started_via=DiningSessionStartedVia.QR,
        opened_at=NOW,
    )
    session.add(dining_session)
    await session.commit()
    return locals()


async def submit_order(
    session: AsyncSession,
    token: str,
    items: list[tuple[Dish, int, list[ModifierOption]]],
    *,
    idempotency_key: str,
    offer: Offer | None = None,
) -> None:
    cart_service = CartService(session, now=lambda: NOW)
    cart = await cart_service.get_cart(token)
    for dish, quantity, modifiers in items:
        cart = await cart_service.add_item(
            token,
            CartItemCreate(
                dish_id=dish.id,
                quantity=quantity,
                modifier_option_ids=[modifier.id for modifier in modifiers],
                expected_version=cart.version,
            ),
        )
    if offer is not None:
        cart = await cart_service.select_offer(
            token, CartOfferSelect(offer_id=offer.id, expected_version=cart.version)
        )
    await cart_service.submit_cart(
        token,
        CartSubmitRequest(
            confirm=True, quote_token=cart.quote_token, idempotency_key=idempotency_key
        ),
    )


async def serve_all(session: AsyncSession, outlet_id: object) -> None:
    tickets = await KitchenService(session, now=lambda: NOW).list_tickets(outlet_id)
    for ticket in tickets:
        await KitchenService(session, now=lambda: NOW).ready_ticket(ticket.id)
        await KitchenService(session, now=lambda: NOW).serve_ticket(ticket.id)


@pytest.mark.asyncio
async def test_bill_preview_aggregates_rounds_exclusive_tax_and_blockers(
    session: AsyncSession,
) -> None:
    data = await restaurant_fixture(session)
    token = data["dining_session"].public_session_token
    await submit_order(
        session,
        token,
        [(data["tikka"], 2, [data["dip"]]), (data["naan"], 4, [])],
        idempotency_key="round-1",
    )
    await submit_order(
        session,
        token,
        [(data["tikka"], 2, []), (data["naan"], 3, [])],
        idempotency_key="round-2",
        offer=data["offer"],
    )

    preview = await BillingService(session, now=lambda: NOW).get_preview(token)
    assert preview.subtotal_before_discount == Decimal("1580.00")
    assert preview.discount_total == Decimal("100.00")
    assert preview.subtotal_after_discount == Decimal("1480.00")
    assert preview.taxable_amount == Decimal("1480.00")
    assert preview.tax_amount == Decimal("74.00")
    assert preview.invoice_total == Decimal("1554.00")
    assert preview.finalizable is False
    assert preview.blockers == ["active_orders_not_served"]

    await serve_all(session, data["outlet"].id)
    ready = await BillingService(session, now=lambda: NOW).get_preview(token)
    assert ready.finalizable is True
    assert ready.blockers == []
    assert ready.billing_quote_token != preview.billing_quote_token

    cart = await CartService(session, now=lambda: NOW).add_item(
        token, CartItemCreate(dish_id=data["naan"].id, quantity=1)
    )
    with_cart = await BillingService(session, now=lambda: NOW).get_preview(token)
    assert with_cart.finalizable is False
    assert "cart_not_empty" in with_cart.blockers
    await CartService(session, now=lambda: NOW).remove_item(
        token, cart.items[0].id, expected_version=cart.version
    )


@pytest.mark.asyncio
async def test_inclusive_tax_zero_rate_and_missing_explicit_tax_config(
    session: AsyncSession,
) -> None:
    data = await restaurant_fixture(session, prices_include_tax=True)
    token = data["dining_session"].public_session_token
    await submit_order(session, token, [(data["thali"], 1, [])], idempotency_key="inclusive")
    await serve_all(session, data["outlet"].id)

    preview = await BillingService(session, now=lambda: NOW).get_preview(token)
    assert preview.taxable_amount == Decimal("1000.00")
    assert preview.tax_amount == Decimal("50.00")
    assert preview.invoice_total == Decimal("1050.00")

    data["tax_profile"].configured_tax_rate_percent = Decimal("0.00")
    await session.commit()
    zero = await BillingService(session, now=lambda: NOW).get_preview(token)
    assert zero.taxable_amount == Decimal("1050.00")
    assert zero.tax_amount == Decimal("0.00")
    assert zero.invoice_total == Decimal("1050.00")
    assert zero.finalizable is True

    data["tax_profile"].configured_tax_rate_percent = None
    await session.commit()
    missing = await BillingService(session, now=lambda: NOW).get_preview(token)
    assert missing.taxable_amount is None
    assert missing.tax_amount is None
    assert missing.invoice_total is None
    assert missing.tax_configuration.configured is False
    assert "tax_configuration_incomplete" in missing.blockers


@pytest.mark.asyncio
async def test_finalize_invoice_idempotency_snapshots_and_ordering_lock(
    session: AsyncSession,
) -> None:
    data = await restaurant_fixture(session)
    token = data["dining_session"].public_session_token
    await submit_order(
        session,
        token,
        [(data["tikka"], 1, [data["dip"]]), (data["naan"], 1, [])],
        idempotency_key="round-1",
    )
    await serve_all(session, data["outlet"].id)
    billing = BillingService(session, now=lambda: NOW)
    preview = await billing.get_preview(token)

    with pytest.raises(BillingConflict) as no_confirm:
        await billing.finalize_invoice(
            token,
            InvoiceFinalizeRequest(
                confirm=False,
                billing_quote_token=preview.billing_quote_token,
                idempotency_key="invoice-1",
            ),
        )
    assert no_confirm.value.code == "invoice_confirmation_required"
    data["tax_profile"].configured_tax_rate_percent = Decimal("6.00")
    await session.commit()
    with pytest.raises(BillingConflict) as stale:
        await billing.finalize_invoice(
            token,
            InvoiceFinalizeRequest(
                confirm=True,
                billing_quote_token=preview.billing_quote_token,
                idempotency_key="invoice-1",
            ),
        )
    assert stale.value.code == "billing_quote_stale"
    data["tax_profile"].configured_tax_rate_percent = Decimal("5.00")
    data["tax_profile"].legal_business_name = "Urban Tadka Snapshot LLP"
    await session.commit()
    fresh = await billing.get_preview(token)
    invoice = await billing.finalize_invoice(
        token,
        InvoiceFinalizeRequest(
            confirm=True,
            billing_quote_token=fresh.billing_quote_token,
            idempotency_key="invoice-1",
        ),
    )
    retry = await billing.finalize_invoice(
        token,
        InvoiceFinalizeRequest(
            confirm=True,
            billing_quote_token=fresh.billing_quote_token,
            idempotency_key="invoice-1",
        ),
    )
    assert retry.id == invoice.id
    assert await session.scalar(select(func.count()).select_from(DiningInvoice)) == 1
    assert await session.scalar(select(func.count()).select_from(DiningInvoiceLine)) == 2
    assert invoice.invoice_reference.startswith("INV-")
    assert invoice.legal_business_name_snapshot == "Urban Tadka Snapshot LLP"
    paneer_line = next(line for line in invoice.lines if line.dish_name_snapshot == "Paneer Tikka")
    assert paneer_line.modifiers[0].modifier_option_name_snapshot == "Extra Dip"

    data["restaurant"].name = "Changed Restaurant"
    data["outlet"].name = "Changed Outlet"
    data["tax_profile"].legal_business_name = "Changed Legal"
    data["tikka"].name = "Changed Dish"
    data["dip"].name = "Changed Dip"
    await session.commit()
    unchanged = await billing.get_invoice(invoice.id)
    assert unchanged.restaurant_name_snapshot == "Urban Tadka"
    assert unchanged.outlet_name_snapshot == "Urban Tadka - Vesu"
    assert unchanged.legal_business_name_snapshot == "Urban Tadka Snapshot LLP"
    unchanged_paneer = next(
        line for line in unchanged.lines if line.dish_name_snapshot == "Paneer Tikka"
    )
    assert unchanged_paneer.modifiers[0].modifier_option_name_snapshot == "Extra Dip"

    with pytest.raises(BillingConflict) as second_key:
        await billing.finalize_invoice(
            token,
            InvoiceFinalizeRequest(
                confirm=True,
                billing_quote_token=fresh.billing_quote_token,
                idempotency_key="invoice-2",
            ),
        )
    assert second_key.value.code == "invoice_already_finalized"
    with pytest.raises(CartConflict) as add_block:
        await CartService(session, now=lambda: NOW).add_item(
            token, CartItemCreate(dish_id=data["naan"].id, quantity=1)
        )
    assert add_block.value.code == "ordering_closed_for_billing"
    assert (await CartService(session, now=lambda: NOW).get_cart(token)).item_count == 0


@pytest.mark.asyncio
async def test_session_close_requires_invoice_for_served_orders_but_not_zero_orders(
    session: AsyncSession,
) -> None:
    data = await restaurant_fixture(session)
    token = data["dining_session"].public_session_token
    await submit_order(session, token, [(data["naan"], 1, [])], idempotency_key="round-1")
    await serve_all(session, data["outlet"].id)
    with pytest.raises(DiningConflict) as missing:
        await DiningService(session, now=lambda: NOW).close_session(token, confirm=True)
    assert missing.value.code == "session_invoice_required"

    preview = await BillingService(session, now=lambda: NOW).get_preview(token)
    await BillingService(session, now=lambda: NOW).finalize_invoice(
        token,
        InvoiceFinalizeRequest(
            confirm=True,
            billing_quote_token=preview.billing_quote_token,
            idempotency_key="invoice-close",
        ),
    )
    still_open = await session.get(DiningSession, data["dining_session"].id)
    assert still_open is not None
    assert still_open.status == DiningSessionStatus.OPEN
    closed = await DiningService(session, now=lambda: NOW).close_session(token, confirm=True)
    assert closed.status == DiningSessionStatus.CLOSED

    other_data = await restaurant_fixture(session)
    zero = await DiningService(session, now=lambda: NOW).close_session(
        other_data["dining_session"].public_session_token, confirm=True
    )
    assert zero.status == DiningSessionStatus.CLOSED


@pytest.mark.asyncio
async def test_finalize_rolls_back_when_line_creation_fails(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = await restaurant_fixture(session)
    token = data["dining_session"].public_session_token
    await submit_order(session, token, [(data["naan"], 1, [])], idempotency_key="round-1")
    await serve_all(session, data["outlet"].id)
    preview = await BillingService(session, now=lambda: NOW).get_preview(token)

    async def fail_lines(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("forced invoice line failure")

    monkeypatch.setattr(BillingService, "_create_invoice_lines", fail_lines)
    with pytest.raises(RuntimeError, match="forced invoice line failure"):
        await BillingService(session, now=lambda: NOW).finalize_invoice(
            token,
            InvoiceFinalizeRequest(
                confirm=True,
                billing_quote_token=preview.billing_quote_token,
                idempotency_key="invoice-boom",
            ),
        )
    assert await session.scalar(select(func.count()).select_from(DiningInvoice)) == 0
    assert await session.scalar(select(func.count()).select_from(DiningInvoiceOrder)) == 0
    assert await session.scalar(select(func.count()).select_from(DiningInvoiceLine)) == 0


@pytest.mark.asyncio
async def test_bill_preview_query_count_and_routes() -> None:
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
            data = await restaurant_fixture(db)
            token = data["dining_session"].public_session_token
            for index in range(12):
                await submit_order(
                    db,
                    token,
                    [(data["naan"], 1, [])],
                    idempotency_key=f"round-{index}",
                )
            await serve_all(db, data["outlet"].id)
            statements = 0
            preview = await BillingService(db, now=lambda: NOW).get_preview(token)
            assert len(preview.round_summaries) == 12
            assert statements < 9
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    paths = set(app.openapi()["paths"])
    assert "/api/v1/dining-sessions/{session_token}/bill-preview" in paths
    assert "/api/v1/dining-sessions/{session_token}/invoice/finalize" in paths
    assert "/api/v1/dining-sessions/{session_token}/invoice" in paths
    assert "/api/v1/invoices/{invoice_id}" in paths
    assert all("/payments" not in path and "/refund" not in path for path in paths)
