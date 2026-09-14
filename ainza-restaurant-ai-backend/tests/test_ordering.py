from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.availability.models import IngredientAvailabilityOverride
from ainza_restaurant.db.base import Base
from ainza_restaurant.dining.models import DiningSession, RestaurantTable
from ainza_restaurant.dining.service import DiningConflict, DiningService
from ainza_restaurant.domain.enums import (
    AvailabilityReasonCode,
    DiningOrderStatus,
    DiningSessionStartedVia,
    DiningSessionStatus,
    MenuStatus,
    MerchandisingStatus,
    OfferScopeType,
    OfferType,
    ReviewStatus,
)
from ainza_restaurant.menu.models import (
    Category,
    Dish,
    DishIngredient,
    DishVariant,
    Ingredient,
    Menu,
    ModifierGroup,
    ModifierOption,
)
from ainza_restaurant.merchandising.models import Offer, TodaysSpecial
from ainza_restaurant.ordering.models import DiningOrder
from ainza_restaurant.ordering.schemas import (
    CartBatchAddItem,
    CartItemCreate,
    CartOfferSelect,
    CartSubmitRequest,
)
from ainza_restaurant.ordering.service import CartConflict, CartService
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
    mains = Category(menu_id=menu.id, name="Mains", slug="mains")
    drinks = Category(menu_id=menu.id, name="Drinks", slug="drinks")
    session.add_all([mains, drinks])
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
        tax_category_code="GST_FOOD",
    )
    naan = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Butter Naan",
        base_price=Decimal("60.00"),
        review_status=ReviewStatus.CONFIRMED,
    )
    biryani = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Paneer Biryani",
        base_price=Decimal("320.00"),
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
    pending = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Pending Roll",
        base_price=Decimal("120.00"),
        review_status=ReviewStatus.PENDING_REVIEW,
    )
    inactive = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Inactive Kebab",
        base_price=Decimal("220.00"),
        review_status=ReviewStatus.CONFIRMED,
        is_active=False,
    )
    draft_dish = Dish(
        menu_id=draft_menu.id,
        name="Draft Dish",
        base_price=Decimal("100.00"),
        review_status=ReviewStatus.CONFIRMED,
    )
    pizza = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Farmhouse Pizza",
        review_status=ReviewStatus.CONFIRMED,
    )
    session.add_all([tikka, naan, biryani, coffee, brownie, pending, inactive, draft_dish, pizza])
    await session.flush()
    small = DishVariant(
        dish_id=pizza.id, name="Small", normalized_name="small", price=Decimal("249.00")
    )
    large = DishVariant(
        dish_id=pizza.id, name="Large", normalized_name="large", price=Decimal("449.00")
    )
    inactive_variant = DishVariant(
        dish_id=pizza.id,
        name="Personal",
        normalized_name="personal",
        price=Decimal("199.00"),
        is_active=False,
    )
    extras = ModifierGroup(dish_id=tikka.id, name="Add Extras", min_selections=0, max_selections=3)
    required = ModifierGroup(
        dish_id=coffee.id, name="Milk Choice", min_selections=1, max_selections=1
    )
    session.add_all([small, large, inactive_variant, extras, required])
    await session.flush()
    dip = ModifierOption(group_id=extras.id, name="Extra Dip", price_delta=Decimal("20.00"))
    cheese = ModifierOption(group_id=extras.id, name="Extra Cheese", price_delta=Decimal("40.00"))
    dairy = ModifierOption(group_id=required.id, name="Dairy", price_delta=Decimal("0.00"))
    inactive_option = ModifierOption(
        group_id=extras.id,
        name="Old Sauce",
        price_delta=Decimal("10.00"),
        is_active=False,
    )
    session.add_all([dip, cheese, dairy, inactive_option])
    await session.flush()
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
            ends_at=NOW + timedelta(hours=1),
            status=MerchandisingStatus.ACTIVE,
            activation_confirmed=True,
            activated_at=NOW,
        )
    )
    offer = Offer(
        outlet_id=outlet.id,
        name="20 percent above 1500",
        offer_type=OfferType.PERCENTAGE,
        scope_type=OfferScopeType.ALL_ITEMS,
        status=MerchandisingStatus.ACTIVE,
        starts_at=NOW - timedelta(hours=1),
        ends_at=NOW + timedelta(hours=1),
        minimum_subtotal=Decimal("1500.00"),
        discount_value=Decimal("20.00"),
        maximum_discount=Decimal("500.00"),
        activation_confirmed=True,
        activated_at=NOW,
    )
    other_offer = Offer(
        outlet_id=other_outlet.id,
        name="Other outlet offer",
        offer_type=OfferType.FLAT,
        scope_type=OfferScopeType.ALL_ITEMS,
        status=MerchandisingStatus.ACTIVE,
        starts_at=NOW - timedelta(hours=1),
        ends_at=NOW + timedelta(hours=1),
        discount_value=Decimal("100.00"),
        activation_confirmed=True,
    )
    session.add_all([offer, other_offer])
    table = RestaurantTable(
        outlet_id=outlet.id, label="T1", normalized_label="t1", public_qr_code="qr-t1"
    )
    other_table = RestaurantTable(
        outlet_id=outlet.id, label="T2", normalized_label="t2", public_qr_code="qr-t2"
    )
    session.add_all([table, other_table])
    await session.flush()
    dining_session = DiningSession(
        table_id=table.id,
        public_session_token="session-one",
        status=DiningSessionStatus.OPEN,
        started_via=DiningSessionStartedVia.QR,
        opened_at=NOW,
    )
    other_dining_session = DiningSession(
        table_id=other_table.id,
        public_session_token="session-two",
        status=DiningSessionStatus.OPEN,
        started_via=DiningSessionStartedVia.QR,
        opened_at=NOW,
    )
    session.add_all([dining_session, other_dining_session])
    await session.commit()
    return locals()


@pytest.mark.asyncio
async def test_batch_cart_add_is_atomic_and_skips_missing_conditionals(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    service = CartService(session, now=lambda: NOW)

    result = await service.add_items_batch(
        "session-one",
        [
            CartBatchAddItem(dish_id=data["tikka"].id, quantity=1),
            CartBatchAddItem(dish_id=data["naan"].id, quantity=2),
            CartBatchAddItem(
                dish_id=None,
                quantity=1,
                required=False,
                requested_reference="Buttermilk",
            ),
        ],
    )
    assert [item.status for item in result.items] == ["added", "added", "skipped"]
    quantities = {item.dish_name: item.quantity for item in result.cart.items}
    assert quantities["Paneer Tikka"] == 1
    assert quantities["Butter Naan"] == 2
    assert result.cart.version == 2

    with pytest.raises(CartConflict) as error:
        await service.add_items_batch(
            "session-two",
            [
                CartBatchAddItem(dish_id=data["tikka"].id, quantity=1),
                CartBatchAddItem(dish_id=None, quantity=1, requested_reference="unknown"),
            ],
        )
    assert error.value.code == "cart_batch_item_unresolved"
    assert (await service.get_cart("session-two")).items == []


@pytest.mark.asyncio
async def test_shared_cart_pricing_modifiers_visibility_and_versions(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    service = CartService(session, now=lambda: NOW)

    empty = await service.get_cart("session-one")
    assert empty.version == 1
    assert empty.quote_token == (await service.get_cart("session-one")).quote_token
    cart = await service.add_item(
        "session-one",
        CartItemCreate(
            dish_id=data["tikka"].id,
            quantity=2,
            modifier_option_ids=[data["dip"].id],
            customer_note="  less spicy  ",
            expected_version=1,
        ),
    )

    assert cart.version == 2
    assert cart.item_count == 1
    assert cart.quantity_count == 2
    assert cart.items[0].customer_note == "less spicy"
    assert cart.items[0].pricing.configured_unit_price == Decimal("300.00")
    assert cart.subtotal_before_offer == Decimal("600.00")
    assert cart.tax_calculated is False
    assert cart.final_bill_calculated is False

    with pytest.raises(CartConflict) as stale:
        await service.add_item(
            "session-one",
            CartItemCreate(dish_id=data["naan"].id, quantity=1, expected_version=1),
        )
    assert stale.value.code == "cart_version_conflict"

    for dish_key in ("pending", "inactive", "draft_dish"):
        with pytest.raises(CartConflict):
            await service.add_item(
                "session-one", CartItemCreate(dish_id=data[dish_key].id, quantity=1)
            )

    other_cart = await service.add_item(
        "session-two", CartItemCreate(dish_id=data["naan"].id, quantity=1)
    )
    assert other_cart.dining_session_token == "session-two"
    assert other_cart.subtotal_before_offer == Decimal("60.00")
    assert (await service.get_cart("session-one")).subtotal_before_offer == Decimal("600.00")


@pytest.mark.asyncio
async def test_variants_modifier_bounds_specials_and_availability(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    service = CartService(session, now=lambda: NOW)

    with pytest.raises(CartConflict) as missing_variant:
        await service.add_item("session-one", CartItemCreate(dish_id=data["pizza"].id, quantity=1))
    assert missing_variant.value.code == "cart_variant_required"
    with pytest.raises(CartConflict):
        await service.add_item(
            "session-one",
            CartItemCreate(
                dish_id=data["pizza"].id, variant_id=data["inactive_variant"].id, quantity=1
            ),
        )
    with pytest.raises(CartConflict):
        await service.add_item("session-one", CartItemCreate(dish_id=data["coffee"].id, quantity=1))
    with pytest.raises(CartConflict):
        await service.add_item(
            "session-one",
            CartItemCreate(
                dish_id=data["tikka"].id,
                quantity=1,
                modifier_option_ids=[data["inactive_option"].id],
            ),
        )

    cart = await service.add_item(
        "session-one",
        CartItemCreate(dish_id=data["pizza"].id, variant_id=data["large"].id, quantity=1),
    )
    cart = await service.add_item(
        "session-one",
        CartItemCreate(
            dish_id=data["coffee"].id,
            quantity=1,
            modifier_option_ids=[data["dairy"].id],
            expected_version=cart.version,
        ),
    )
    cart = await service.add_item(
        "session-one",
        CartItemCreate(dish_id=data["biryani"].id, quantity=1, expected_version=cart.version),
    )
    assert cart.subtotal_before_offer == Decimal("868.00")
    biryani_line = next(item for item in cart.items if item.dish_id == data["biryani"].id)
    assert biryani_line.pricing.special_unit_price == Decimal("279.00")

    later = CartService(session, now=lambda: NOW + timedelta(hours=2))
    repriced = await later.get_cart("session-one")
    assert repriced.subtotal_before_offer == Decimal("909.00")
    assert repriced.quote_token != cart.quote_token

    session.add(
        IngredientAvailabilityOverride(
            ingredient_id=data["paneer"].id,
            starts_at=NOW,
            expires_at=None,
            reason_code=AvailabilityReasonCode.OUT_OF_STOCK,
            reason_note="Paneer finished",
            source_proposal_id=uuid4(),
        )
    )
    await session.commit()
    unavailable = await service.get_cart("session-one")
    assert unavailable.can_submit is False
    assert len(unavailable.unavailable_item_ids) == 1
    with pytest.raises(CartConflict) as blocked:
        await service.submit_cart(
            "session-one",
            CartSubmitRequest(
                confirm=True, quote_token=unavailable.quote_token, idempotency_key="blocked"
            ),
        )
    assert blocked.value.code == "cart_contains_unavailable_items"


@pytest.mark.asyncio
async def test_offer_selection_submit_snapshot_idempotency_and_rounds(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    service = CartService(session, now=lambda: NOW)

    cart = await service.add_item(
        "session-one",
        CartItemCreate(
            dish_id=data["tikka"].id,
            quantity=4,
            modifier_option_ids=[data["dip"].id],
            expected_version=1,
        ),
    )
    cart = await service.add_item(
        "session-one",
        CartItemCreate(dish_id=data["naan"].id, quantity=5, expected_version=cart.version),
    )
    assert cart.subtotal_before_offer == Decimal("1500.00")
    with pytest.raises(CartConflict) as cross_outlet:
        await service.select_offer("session-one", CartOfferSelect(offer_id=data["other_offer"].id))
    assert cross_outlet.value.code == "cart_offer_not_effective"

    discounted = await service.select_offer(
        "session-one", CartOfferSelect(offer_id=data["offer"].id, expected_version=cart.version)
    )
    assert discounted.discount_amount == Decimal("300.00")
    assert discounted.subtotal_after_discount == Decimal("1200.00")
    assert discounted.selected_offer.auto_best_offer_selected is False
    assert discounted.selected_offer.stacking_applied is False
    with pytest.raises(CartConflict) as no_confirm:
        await service.submit_cart(
            "session-one",
            CartSubmitRequest(
                confirm=False, quote_token=discounted.quote_token, idempotency_key="r1"
            ),
        )
    assert no_confirm.value.code == "order_submission_confirmation_required"

    order = await service.submit_cart(
        "session-one",
        CartSubmitRequest(confirm=True, quote_token=discounted.quote_token, idempotency_key="r1"),
    )
    assert order.round_number == 1
    assert order.status == DiningOrderStatus.SUBMITTED
    assert order.subtotal_before_discount == Decimal("1500.00")
    assert order.discount_amount == Decimal("300.00")
    items_by_name = {item.dish_name_snapshot: item for item in order.items}
    assert set(items_by_name) == {"Paneer Tikka", "Butter Naan"}
    assert items_by_name["Paneer Tikka"].modifiers[0].modifier_option_name_snapshot == "Extra Dip"
    assert items_by_name["Paneer Tikka"].tax_category_code_snapshot == "GST_FOOD"
    assert order.tax_calculated is False
    assert order.final_bill_calculated is False
    assert (await service.get_cart("session-one")).item_count == 0

    data["tikka"].name = "Renamed Paneer Tikka"
    data["dip"].name = "Renamed Dip"
    await session.commit()
    same = await service.submit_cart(
        "session-one",
        CartSubmitRequest(confirm=True, quote_token=discounted.quote_token, idempotency_key="r1"),
    )
    assert same.id == order.id
    same_tikka = next(item for item in same.items if item.dish_id == data["tikka"].id)
    assert same_tikka.dish_name_snapshot == "Paneer Tikka"
    assert same_tikka.modifiers[0].modifier_option_name_snapshot == "Extra Dip"

    cart = await service.add_item(
        "session-one", CartItemCreate(dish_id=data["brownie"].id, quantity=1)
    )
    second = await service.submit_cart(
        "session-one",
        CartSubmitRequest(confirm=True, quote_token=cart.quote_token, idempotency_key="r2"),
    )
    assert second.round_number == 2
    assert [order.round_number for order in await service.list_orders("session-one")] == [1, 2]


@pytest.mark.asyncio
async def test_stale_quote_and_close_session_with_cart(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    service = CartService(session, now=lambda: NOW)
    cart = await service.add_item(
        "session-one", CartItemCreate(dish_id=data["naan"].id, quantity=2)
    )
    data["naan"].base_price = Decimal("70.00")
    await session.commit()
    with pytest.raises(CartConflict) as stale:
        await service.submit_cart(
            "session-one",
            CartSubmitRequest(confirm=True, quote_token=cart.quote_token, idempotency_key="stale"),
        )
    assert stale.value.code == "cart_quote_stale"
    stale_order = await session.scalar(
        select(DiningOrder).where(DiningOrder.idempotency_key == "stale")
    )
    assert stale_order is None
    assert (await service.get_cart("session-one")).item_count == 1

    with pytest.raises(DiningConflict) as close_blocked:
        await DiningService(session, now=lambda: NOW).close_session("session-one", confirm=True)
    assert close_blocked.value.code == "session_has_nonempty_cart"

    fresh = await service.get_cart("session-one")
    empty = await service.remove_item(
        "session-one", fresh.items[0].id, expected_version=fresh.version
    )
    assert empty.item_count == 0
    closed = await DiningService(session, now=lambda: NOW).close_session(
        "session-one", confirm=True
    )
    assert closed.status == DiningSessionStatus.CLOSED
    assert (await service.list_orders("session-one")) == []
