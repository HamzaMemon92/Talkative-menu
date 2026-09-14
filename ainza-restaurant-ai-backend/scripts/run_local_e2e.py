# ruff: noqa: E501
from __future__ import annotations

import asyncio

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ainza_restaurant.billing.models import DiningInvoice
from ainza_restaurant.billing.schemas import InvoiceFinalizeRequest
from ainza_restaurant.billing.service import BillingService
from ainza_restaurant.core.config import get_settings
from ainza_restaurant.dining.models import RestaurantTable
from ainza_restaurant.dining.schemas import ManualSessionStartRequest
from ainza_restaurant.dining.service import DiningConflict, DiningService
from ainza_restaurant.kitchen.models import KitchenTicket
from ainza_restaurant.kitchen.service import KitchenService
from ainza_restaurant.menu.models import Dish, DishVariant, ModifierOption
from ainza_restaurant.ordering.models import DiningOrder
from ainza_restaurant.ordering.schemas import CartItemCreate, CartSubmitRequest
from ainza_restaurant.ordering.service import CartConflict, CartService
from ainza_restaurant.restaurants.models import Restaurant, RestaurantOutlet

E2E_DATABASE = "ainza_restaurant_e2e"
FIXTURE_SLUG = "urban-tadka-e2e"


async def main() -> None:
    engine = create_async_engine(
        make_url(get_settings().database_url).set(database=E2E_DATABASE), pool_pre_ping=True
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            if await session.scalar(text("SELECT current_database()")) != E2E_DATABASE:
                raise RuntimeError("refusing to run against a non-E2E database")
            restaurant = await session.scalar(
                select(Restaurant).where(Restaurant.slug == FIXTURE_SLUG)
            )
            assert restaurant is not None
            outlet = await session.scalar(
                select(RestaurantOutlet).where(RestaurantOutlet.restaurant_id == restaurant.id)
            )
            assert outlet is not None
            table = await session.scalar(
                select(RestaurantTable).where(
                    RestaurantTable.outlet_id == outlet.id, RestaurantTable.label == "T2"
                )
            )
            assert table is not None
            dishes = {
                item.name: item
                for item in (
                    await session.execute(
                        select(Dish)
                        .join_from(Dish, Dish.menu)
                        .where(text("menus.outlet_id = :outlet"))
                        .params(outlet=outlet.id)
                    )
                ).scalars()
            }
            variant = await session.scalar(
                select(DishVariant).where(
                    DishVariant.dish_id == dishes["Veg Biryani"].id, DishVariant.name == "Large"
                )
            )
            modifier = await session.scalar(
                select(ModifierOption).where(ModifierOption.name == "Extra Mint Chutney")
            )
            assert variant is not None and modifier is not None
            dining = DiningService(session)
            started = await dining.start_manual_session(table.id, ManualSessionStartRequest())
            token = started.session.public_session_token
            print("[PASS] T2 DiningSession")
            try:
                await dining.start_manual_session(table.id, ManualSessionStartRequest())
            except DiningConflict:
                print("[PASS] duplicate open DiningSession rejected")
            else:
                raise AssertionError("duplicate open session accepted")
            cart_service = CartService(session)
            cart = await cart_service.get_cart(token)
            cart = await cart_service.add_item(
                token,
                CartItemCreate(
                    dish_id=dishes["Paneer Tikka"].id,
                    quantity=1,
                    modifier_option_ids=[modifier.id],
                    expected_version=cart.version,
                ),
            )
            cart = await cart_service.add_item(
                token,
                CartItemCreate(
                    dish_id=dishes["Veg Biryani"].id,
                    variant_id=variant.id,
                    quantity=1,
                    expected_version=cart.version,
                ),
            )
            stale = cart.version
            cart = await cart_service.add_item(
                token,
                CartItemCreate(
                    dish_id=dishes["Butter Naan"].id, quantity=1, expected_version=cart.version
                ),
            )
            try:
                await cart_service.add_item(
                    token,
                    CartItemCreate(
                        dish_id=dishes["Tandoori Roti"].id, quantity=1, expected_version=stale
                    ),
                )
            except CartConflict:
                print("[PASS] stale Cart version rejected")
            else:
                raise AssertionError("stale cart mutation accepted")
            try:
                await cart_service.add_item(
                    token,
                    CartItemCreate(
                        dish_id=dishes["Crispy Corn"].id, quantity=1, expected_version=cart.version
                    ),
                )
            except CartConflict:
                print("[PASS] sold-out Crispy Corn rejected")
            else:
                raise AssertionError("sold-out dish accepted")
            print("[PASS] shared Cart")
            try:
                await cart_service.submit_cart(
                    token,
                    CartSubmitRequest(
                        confirm=False, quote_token=cart.quote_token, idempotency_key="e2e-r1"
                    ),
                )
            except CartConflict:
                print("[PASS] explicit confirmation boundary")
            order1 = await cart_service.submit_cart(
                token,
                CartSubmitRequest(
                    confirm=True, quote_token=cart.quote_token, idempotency_key="e2e-r1"
                ),
            )
            retry = await cart_service.submit_cart(
                token,
                CartSubmitRequest(
                    confirm=True, quote_token=cart.quote_token, idempotency_key="e2e-r1"
                ),
            )
            assert retry.id == order1.id
            print("[PASS] Round 1 and idempotency")
            kitchen = KitchenService(session)
            ticket1 = await session.scalar(
                select(KitchenTicket).where(KitchenTicket.dining_order_id == order1.id)
            )
            assert ticket1 is not None
            await kitchen.ready_ticket(ticket1.id)
            await kitchen.serve_ticket(ticket1.id)
            print("[PASS] KOT Round 1 served")
            cart = await cart_service.get_cart(token)
            cart = await cart_service.add_item(
                token,
                CartItemCreate(
                    dish_id=dishes["Dal Makhani"].id, quantity=1, expected_version=cart.version
                ),
            )
            order2 = await cart_service.submit_cart(
                token,
                CartSubmitRequest(
                    confirm=True, quote_token=cart.quote_token, idempotency_key="e2e-r2"
                ),
            )
            ticket2 = await session.scalar(
                select(KitchenTicket).where(KitchenTicket.dining_order_id == order2.id)
            )
            assert ticket2 is not None
            await kitchen.ready_ticket(ticket2.id)
            await kitchen.serve_ticket(ticket2.id)
            print("[PASS] Round 2 and KOT served")
            billing = BillingService(session)
            preview = await billing.get_preview(token)
            assert preview.invoice_total is not None and preview.currency_code == "INR"
            invoice = await billing.finalize_invoice(
                token,
                InvoiceFinalizeRequest(
                    confirm=True,
                    billing_quote_token=preview.billing_quote_token,
                    idempotency_key="e2e-invoice",
                ),
            )
            assert (
                invoice.id
                == (
                    await billing.finalize_invoice(
                        token,
                        InvoiceFinalizeRequest(
                            confirm=True,
                            billing_quote_token=preview.billing_quote_token,
                            idempotency_key="e2e-invoice",
                        ),
                    )
                ).id
            )
            print(f"[PASS] bill preview and invoice: INR {preview.invoice_total}")
            try:
                await cart_service.add_item(
                    token, CartItemCreate(dish_id=dishes["Dal Makhani"].id, quantity=1)
                )
            except CartConflict:
                print("[PASS] post-invoice ordering locked")
            else:
                raise AssertionError("post-invoice order accepted")
            closed = await dining.close_session(token, confirm=True)
            assert closed.status.value == "closed"
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(DiningOrder)
                    .where(DiningOrder.dining_session_id == started.session.id)
                )
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(DiningInvoice)
                    .where(DiningInvoice.dining_session_id == started.session.id)
                )
                == 1
            )
            print("[PASS] session closed and final PostgreSQL assertions")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
