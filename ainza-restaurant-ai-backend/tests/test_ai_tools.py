from __future__ import annotations

import importlib.metadata
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.ai.context import AIActorType, AIToolContext, ToolExecutionAuthorization
from ainza_restaurant.ai.db_models import (
    AIConversation,
    AIConversationMessage,
    AIMessageRole,
    AIMessageStatus,
)
from ainza_restaurant.ai.models import AIMessage, AIModelResponse, AIToolSafetyLevel
from ainza_restaurant.ai.providers.base import ToolCallingModelProvider
from ainza_restaurant.ai.service import CustomerAIConversationService
from ainza_restaurant.ai.tools.definitions import AIToolDefinition
from ainza_restaurant.ai.tools.executor import AIToolExecutor
from ainza_restaurant.ai.tools.registry import AIToolRegistry, build_default_registry
from ainza_restaurant.availability.models import IngredientAvailabilityOverride
from ainza_restaurant.billing.schemas import InvoiceFinalizeRequest
from ainza_restaurant.billing.service import BillingService
from ainza_restaurant.db.base import Base
from ainza_restaurant.dining.models import DiningSession, RestaurantTable
from ainza_restaurant.domain.enums import (
    AllergenStatus,
    AvailabilityStatus,
    DietaryClassification,
    DiningOrderStatus,
    DiningSessionStartedVia,
    DiningSessionStatus,
    MenuStatus,
    MerchandisingStatus,
    OfferScopeType,
    OfferType,
    RestaurantType,
    ReviewStatus,
    SpiceLevel,
)
from ainza_restaurant.kitchen.models import KitchenTicket
from ainza_restaurant.kitchen.service import KitchenService
from ainza_restaurant.main import app
from ainza_restaurant.menu.models import Category, Dish, DishIngredient, Ingredient, Menu
from ainza_restaurant.merchandising.models import Offer
from ainza_restaurant.ordering.models import DiningOrder
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
        currency_code="INR",
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
    other_mains = Category(menu_id=other_menu.id, name="Mains", slug="mains")
    session.add_all([mains, other_mains])
    await session.flush()
    paneer = Ingredient(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="Paneer",
        normalized_name="paneer",
    )
    other_paneer = Ingredient(
        restaurant_id=restaurant.id,
        outlet_id=other_outlet.id,
        name="Paneer",
        normalized_name="paneer-other",
    )
    session.add_all([paneer, other_paneer])
    await session.flush()
    tikka = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Paneer Tikka",
        base_price=Decimal("280.00"),
        review_status=ReviewStatus.CONFIRMED,
        dietary_classification=DietaryClassification.VEGETARIAN,
        vegan_status=AvailabilityStatus.UNKNOWN,
        jain_status=AvailabilityStatus.UNKNOWN,
        spice_level=SpiceLevel.UNKNOWN,
        allergen_information_status=AllergenStatus.UNKNOWN,
    )
    naan = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Butter Naan",
        base_price=Decimal("60.00"),
        review_status=ReviewStatus.CONFIRMED,
        dietary_classification=DietaryClassification.VEGETARIAN,
    )
    pending = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Pending Paneer Roll",
        base_price=Decimal("120.00"),
        review_status=ReviewStatus.PENDING_REVIEW,
        dietary_classification=DietaryClassification.VEGETARIAN,
    )
    other_dish = Dish(
        menu_id=other_menu.id,
        category_id=other_mains.id,
        name="Other Paneer",
        base_price=Decimal("310.00"),
        review_status=ReviewStatus.CONFIRMED,
        dietary_classification=DietaryClassification.VEGETARIAN,
    )
    session.add_all([tikka, naan, pending, other_dish])
    await session.flush()
    session.add_all(
        [
            DishIngredient(
                dish_id=tikka.id,
                ingredient_id=paneer.id,
                is_required_for_availability=True,
            ),
            DishIngredient(
                dish_id=other_dish.id,
                ingredient_id=other_paneer.id,
                is_required_for_availability=True,
            ),
        ]
    )
    offer = Offer(
        outlet_id=outlet.id,
        name="Flat 50",
        offer_type=OfferType.FLAT,
        scope_type=OfferScopeType.ALL_ITEMS,
        status=MerchandisingStatus.ACTIVE,
        starts_at=NOW - timedelta(days=30),
        ends_at=NOW + timedelta(days=3650),
        discount_value=Decimal("50.00"),
        activation_confirmed=True,
    )
    expired_offer = Offer(
        outlet_id=outlet.id,
        name="Expired",
        offer_type=OfferType.FLAT,
        scope_type=OfferScopeType.ALL_ITEMS,
        status=MerchandisingStatus.ACTIVE,
        starts_at=NOW - timedelta(days=3),
        ends_at=NOW - timedelta(days=1),
        discount_value=Decimal("90.00"),
        activation_confirmed=True,
    )
    table = RestaurantTable(
        outlet_id=outlet.id,
        label="T2",
        normalized_label="t2",
        public_qr_code=f"qr-{uuid4().hex}",
    )
    other_table = RestaurantTable(
        outlet_id=other_outlet.id,
        label="T9",
        normalized_label="t9",
        public_qr_code=f"qr-{uuid4().hex}",
    )
    session.add_all([offer, expired_offer, table, other_table])
    await session.flush()
    dining_session = DiningSession(
        table_id=table.id,
        public_session_token=f"session-{uuid4().hex}",
        status=DiningSessionStatus.OPEN,
        started_via=DiningSessionStartedVia.QR,
        opened_at=NOW,
    )
    other_session = DiningSession(
        table_id=other_table.id,
        public_session_token=f"session-{uuid4().hex}",
        status=DiningSessionStatus.OPEN,
        started_via=DiningSessionStartedVia.QR,
        opened_at=NOW,
    )
    session.add_all([dining_session, other_session])
    await session.commit()
    return locals()


def customer_context(data: dict[str, object]) -> AIToolContext:
    return AIToolContext(
        actor_type=AIActorType.CUSTOMER,
        outlet_id=data["outlet"].id,
        dining_session_token=data["dining_session"].public_session_token,
    )


def owner_context(data: dict[str, object]) -> AIToolContext:
    return AIToolContext(actor_type=AIActorType.OWNER, outlet_id=data["outlet"].id)


@pytest.mark.asyncio
async def test_registry_schema_export_permissions_and_validation(session: AsyncSession) -> None:
    registry = build_default_registry()
    customer_names = {tool.name for tool in registry.list_tools_for_actor(AIActorType.CUSTOMER)}
    owner_names = {tool.name for tool in registry.list_tools_for_actor(AIActorType.OWNER)}
    assert {
        "menu_get",
        "menu_search",
        "menu_get_dish",
        "dish_get_availability",
        "offers_get_effective",
        "cart_get",
        "cart_add_item",
        "cart_update_item",
        "cart_remove_item",
        "cart_select_offer",
        "cart_submit",
        "orders_get_session",
        "bill_get_preview",
    } <= customer_names
    assert {
        "owner_get_availability",
        "owner_create_availability_proposal",
        "owner_get_availability_proposal",
        "owner_confirm_availability_proposal",
    } <= owner_names
    assert customer_names.isdisjoint(owner_names)

    json.dumps(registry.get_tool_schemas(AIActorType.CUSTOMER))
    json.dumps(registry.get_tool_schemas(AIActorType.OWNER))
    assert "owner_confirm_availability_proposal" not in {
        item["name"] for item in registry.get_tool_schemas(AIActorType.CUSTOMER)
    }
    assert registry.get("cart_submit").safety_level == AIToolSafetyLevel.CONSEQUENTIAL_MUTATION
    assert registry.get("owner_confirm_availability_proposal").requires_confirmation is True

    duplicate = AIToolRegistry()
    duplicate.register(registry.get("menu_get"))
    with pytest.raises(ValueError):
        duplicate.register(registry.get("menu_get"))

    data = await urban_tadka(session)
    executor = AIToolExecutor(registry, now=lambda: NOW)
    unknown = await executor.execute(session, "missing_tool", {}, customer_context(data))
    assert unknown.ok is False
    assert unknown.error is not None
    assert unknown.error.code == "ai_tool_not_found"

    unsafe = await executor.execute(
        session,
        "cart_add_item",
        {"dish_id": str(data["tikka"].id), "quantity": 1, "price": "1.00"},
        customer_context(data),
    )
    assert unsafe.ok is False
    assert unsafe.error is not None
    assert unsafe.error.code == "ai_tool_validation_error"

    nested_unsafe = await executor.execute(
        session,
        "menu_search",
        {"query": "paneer", "filters": {"price": "1.00"}},
        customer_context(data),
    )
    assert nested_unsafe.ok is False
    assert nested_unsafe.error is not None
    assert nested_unsafe.error.code == "ai_tool_validation_error"


@pytest.mark.asyncio
async def test_actor_isolation_confirmation_and_handler_short_circuit(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    registry = build_default_registry()
    executor = AIToolExecutor(registry, now=lambda: NOW)

    forbidden = await executor.execute(
        session,
        "owner_get_availability",
        {},
        customer_context(data),
    )
    assert forbidden.ok is False
    assert forbidden.error is not None
    assert forbidden.error.code == "ai_tool_forbidden"

    called = False

    class Empty(BaseModel):
        model_config = ConfigDict(extra="forbid")

    async def handler(
        _session: AsyncSession, _context: AIToolContext, _payload: BaseModel
    ) -> dict[str, bool]:
        nonlocal called
        called = True
        return {"called": True}

    custom = AIToolRegistry()
    custom.register(
        AIToolDefinition(
            name="owner_only",
            description="owner only",
            input_model=Empty,
            allowed_actor_types=frozenset({AIActorType.OWNER}),
            safety_level=AIToolSafetyLevel.READ_ONLY,
            requires_confirmation=False,
            handler=handler,
        )
    )
    blocked = await AIToolExecutor(custom, now=lambda: NOW).execute(
        session,
        "owner_only",
        {},
        customer_context(data),
    )
    assert blocked.ok is False
    assert called is False

    cart = await executor.execute(
        session,
        "cart_add_item",
        {"dish_id": str(data["naan"].id), "quantity": 1},
        customer_context(data),
    )
    assert cart.ok is True
    quote = cart.data["quote_token"]
    no_auth = await executor.execute(
        session,
        "cart_submit",
        {"quote_token": quote, "idempotency_key": "ai-order", "confirm": True},
        customer_context(data),
    )
    assert no_auth.ok is False
    assert no_auth.error is not None
    assert no_auth.error.code == "ai_confirmation_required"
    assert await session.scalar(select(func.count()).select_from(DiningOrder)) == 0


@pytest.mark.asyncio
async def test_customer_tools_flow_scope_unknowns_money_and_lifecycle(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    context = customer_context(data)

    menu = await executor.execute(session, "menu_get", {}, context)
    assert menu.ok is True
    names = [dish["name"] for category in menu.data["categories"] for dish in category["dishes"]]
    assert names == ["Butter Naan", "Paneer Tikka"]
    paneer = next(
        dish
        for category in menu.data["categories"]
        for dish in category["dishes"]
        if dish["name"] == "Paneer Tikka"
    )
    assert paneer["price"] == "280.00"
    assert paneer["dietary"] == "vegetarian"
    assert paneer["vegan"] == "unknown"
    assert paneer["jain"] == "unknown"
    assert paneer["spice"] == "unknown"
    assert paneer["allergen_info"] == "unknown"
    assert "description" not in paneer
    assert "pricing" not in paneer
    assert "availability" not in paneer
    assert "images" not in paneer
    assert "modifiers" not in paneer

    search = await executor.execute(
        session,
        "menu_search",
        {
            "query": "paneer",
            "filters": {"dietary_classification": "vegetarian"},
        },
        context,
    )
    assert search.ok is True
    assert [dish["name"] for dish in search.data] == ["Paneer Tikka"]
    assert "Pending Paneer Roll" not in [dish["name"] for dish in search.data]

    cross_dish = await executor.execute(
        session,
        "menu_get_dish",
        {"dish_id": str(data["other_dish"].id)},
        context,
    )
    assert cross_dish.ok is False
    assert cross_dish.error is not None
    assert cross_dish.error.code == "customer_menu_dish_wrong_outlet"

    cross_session_context = AIToolContext(
        actor_type=AIActorType.CUSTOMER,
        outlet_id=data["outlet"].id,
        dining_session_token=data["other_session"].public_session_token,
    )
    cross_session = await executor.execute(session, "cart_get", {}, cross_session_context)
    assert cross_session.ok is False
    assert cross_session.error is not None
    assert cross_session.error.code == "ai_scope_violation"

    offers = await executor.execute(session, "offers_get_effective", {}, context)
    assert offers.ok is True
    assert [offer["name"] for offer in offers.data] == ["Flat 50"]

    cart = await executor.execute(
        session,
        "cart_add_item",
        {"dish_id": str(data["tikka"].id), "quantity": 2},
        context,
    )
    assert cart.ok is True
    item_id = cart.data["items"][0]["id"]
    updated = await executor.execute(
        session,
        "cart_update_item",
        {
            "cart_item_id": item_id,
            "quantity": 1,
            "expected_cart_version": cart.data["version"],
        },
        context,
    )
    assert updated.ok is True
    selected = await executor.execute(
        session,
        "cart_select_offer",
        {"offer_id": str(data["offer"].id), "expected_cart_version": updated.data["version"]},
        context,
    )
    assert selected.ok is True
    removed = await executor.execute(
        session,
        "cart_remove_item",
        {
            "cart_item_id": item_id,
            "expected_cart_version": selected.data["version"],
        },
        context,
    )
    assert removed.ok is True
    cart = await executor.execute(
        session,
        "cart_add_item",
        {"dish_id": str(data["naan"].id), "quantity": 1},
        context,
    )
    stale = await executor.execute(
        session,
        "cart_submit",
        {"quote_token": "stale", "idempotency_key": "stale"},
        context,
        ToolExecutionAuthorization(explicit_user_confirmation=True),
    )
    assert stale.ok is False
    assert stale.error is not None
    assert stale.error.code == "cart_quote_stale"
    order = await executor.execute(
        session,
        "cart_submit",
        {"quote_token": cart.data["quote_token"], "idempotency_key": "ai-order"},
        context,
        ToolExecutionAuthorization(explicit_user_confirmation=True),
    )
    assert order.ok is True
    repeat = await executor.execute(
        session,
        "cart_submit",
        {"quote_token": cart.data["quote_token"], "idempotency_key": "ai-order"},
        context,
        ToolExecutionAuthorization(explicit_user_confirmation=True),
    )
    assert repeat.ok is True
    assert repeat.data["id"] == order.data["id"]
    assert await session.scalar(select(func.count()).select_from(KitchenTicket)) == 1

    data["naan"].base_price = Decimal("600.00")
    await session.commit()
    orders = await executor.execute(session, "orders_get_session", {}, context)
    assert orders.ok is True
    assert orders.data[0]["items"][0]["line_subtotal_snapshot"] == "60.00"
    bill = await executor.execute(session, "bill_get_preview", {}, context)
    assert bill.ok is True
    assert bill.data["subtotal_before_discount"] == "60.00"
    assert bill.data["discount_total"] == "50.00"
    assert bill.data["subtotal_after_discount"] == "10.00"
    assert bill.data["tax_amount"] == "0.50"

    ticket = (await KitchenService(session, now=lambda: NOW).list_tickets(data["outlet"].id))[0]
    await KitchenService(session, now=lambda: NOW).ready_ticket(ticket.id)
    await KitchenService(session, now=lambda: NOW).serve_ticket(ticket.id)
    preview = await BillingService(session, now=lambda: NOW).get_preview(
        data["dining_session"].public_session_token
    )
    await BillingService(session, now=lambda: NOW).finalize_invoice(
        data["dining_session"].public_session_token,
        InvoiceFinalizeRequest(
            confirm=True,
            billing_quote_token=preview.billing_quote_token,
            idempotency_key="invoice-ai",
        ),
    )
    locked = await executor.execute(
        session,
        "cart_add_item",
        {"dish_id": str(data["tikka"].id), "quantity": 1},
        context,
    )
    assert locked.ok is False
    assert locked.error is not None
    assert locked.error.code == "ordering_closed_for_billing"
    history = await executor.execute(session, "orders_get_session", {}, context)
    assert history.ok is True
    assert history.data[0]["status"] == DiningOrderStatus.SERVED.value


@pytest.mark.asyncio
async def test_current_total_all_four_authoritative_money_states(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    context = customer_context(data)

    empty = await executor.execute(session, "customer_total_summary", {}, context)
    assert empty.ok is True
    assert empty.data == {
        "state": "EMPTY",
        "cart_has_items": False,
        "cart_item_count": 0,
        "cart_total": None,
        "has_submitted_orders": False,
        "submitted_bill_total": None,
        "currency_code": "INR",
    }

    cart = await executor.execute(
        session,
        "cart_add_item",
        {"dish_id": str(data["naan"].id), "quantity": 2},
        context,
    )
    assert cart.ok is True
    cart_total = Decimal("120.00")
    cart_only = await executor.execute(session, "customer_total_summary", {}, context)
    assert cart_only.ok is True
    assert cart_only.data["state"] == "CART_ONLY"
    assert cart_only.data["cart_total"] == cart_total
    assert cart_only.data["submitted_bill_total"] is None

    submitted = await executor.execute(
        session,
        "cart_submit",
        {"quote_token": cart.data["quote_token"], "idempotency_key": "money-state-order"},
        context,
        ToolExecutionAuthorization(explicit_user_confirmation=True),
    )
    assert submitted.ok is True
    submitted_only = await executor.execute(session, "customer_total_summary", {}, context)
    assert submitted_only.ok is True
    assert submitted_only.data["state"] == "SUBMITTED_ONLY"
    assert submitted_only.data["submitted_bill_total"] == Decimal("126.00")
    assert submitted_only.data["cart_total"] is None

    second_cart = await executor.execute(
        session,
        "cart_add_item",
        {"dish_id": str(data["tikka"].id), "quantity": 1},
        context,
    )
    assert second_cart.ok is True
    both = await executor.execute(session, "customer_total_summary", {}, context)
    assert both.ok is True
    assert both.data["state"] == "BOTH"
    assert both.data["submitted_bill_total"] == Decimal("126.00")
    assert both.data["cart_total"] == Decimal("280.00")
    assert both.data["submitted_bill_total"] + both.data["cart_total"] == Decimal("406.00")


@pytest.mark.asyncio
async def test_v1_acceptance_contexts_are_isolated(session: AsyncSession) -> None:
    data = await urban_tadka(session)
    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    service = CustomerAIConversationService(session)
    conversation_a = await service.create_conversation(data["dining_session"].public_session_token)
    conversation_b = await service.create_conversation(
        data["other_session"].public_session_token
    )
    stored_a = await session.scalar(
        select(AIConversation).where(
            AIConversation.public_token == conversation_a.conversation_token
        )
    )
    stored_b = await session.scalar(
        select(AIConversation).where(
            AIConversation.public_token == conversation_b.conversation_token
        )
    )
    assert stored_a is not None
    assert stored_b is not None
    assert stored_a.pending_recommendation_interaction_json is None
    assert stored_b.pending_recommendation_interaction_json is None

    context_a = customer_context(data)
    context_b = AIToolContext(
        actor_type=AIActorType.CUSTOMER,
        outlet_id=data["other_outlet"].id,
        dining_session_token=data["other_session"].public_session_token,
    )
    added = await executor.execute(
        session,
        "cart_add_item",
        {"dish_id": str(data["naan"].id), "quantity": 1},
        context_a,
    )
    assert added.ok is True
    stored_a.pending_recommendation_interaction_json = {"single_use": True}
    session.add(
        AIConversationMessage(
            conversation_id=stored_a.id,
            client_message_id="acceptance-a",
            sequence_number=1,
            role=AIMessageRole.USER,
            status=AIMessageStatus.COMPLETED,
            content="temporary acceptance state",
        )
    )
    await session.commit()

    isolated_cart = await executor.execute(session, "cart_get", {}, context_b)
    isolated_total = await executor.execute(session, "customer_total_summary", {}, context_b)
    assert isolated_cart.ok is True
    assert isolated_cart.data["items"] == []
    assert isolated_total.ok is True
    assert isolated_total.data["state"] == "EMPTY"
    assert await session.scalar(
        select(func.count()).select_from(DiningOrder).where(
            DiningOrder.dining_session_id == data["other_session"].id
        )
    ) == 0
    await session.refresh(stored_b)
    assert stored_b.pending_recommendation_interaction_json is None
    assert await session.scalar(
        select(func.count()).select_from(AIConversationMessage).where(
            AIConversationMessage.conversation_id == stored_b.id
        )
    ) == 0
@pytest.mark.asyncio
async def test_owner_availability_flow_and_customer_safe_availability(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    owner = owner_context(data)
    customer = customer_context(data)

    availability = await executor.execute(session, "owner_get_availability", {}, owner)
    assert availability.ok is True
    assert availability.data["outlet_id"] == str(data["outlet"].id)

    proposal = await executor.execute(
        session,
        "owner_create_availability_proposal",
        {
            "target_type": "ingredient",
            "target_id": str(data["paneer"].id),
            "action": "mark_unavailable",
            "duration_mode": "indefinite",
            "reason_code": "out_of_stock",
            "reason_note": "Owner internal note",
            "confirm": True,
        },
        owner,
    )
    assert proposal.ok is False
    assert proposal.error is not None
    assert proposal.error.code == "ai_tool_validation_error"
    proposal = await executor.execute(
        session,
        "owner_create_availability_proposal",
        {
            "target_type": "ingredient",
            "target_id": str(data["paneer"].id),
            "action": "mark_unavailable",
            "duration_mode": "indefinite",
            "reason_code": "out_of_stock",
            "reason_note": "Owner internal note",
        },
        owner,
    )
    assert proposal.ok is True
    assert proposal.data["affected_dishes"][0]["name"] == "Paneer Tikka"
    assert (
        await session.scalar(select(func.count()).select_from(IngredientAvailabilityOverride)) == 0
    )
    sold_out_cart = await executor.execute(
        session,
        "cart_add_item",
        {"dish_id": str(data["tikka"].id), "quantity": 1},
        customer,
    )
    assert sold_out_cart.ok is True

    read = await executor.execute(
        session,
        "owner_get_availability_proposal",
        {"proposal_id": proposal.data["id"]},
        owner,
    )
    assert read.ok is True
    no_auth = await executor.execute(
        session,
        "owner_confirm_availability_proposal",
        {"proposal_id": proposal.data["id"], "confirm": True},
        owner,
    )
    assert no_auth.ok is False
    assert no_auth.error is not None
    assert no_auth.error.code == "ai_confirmation_required"
    assert (
        await session.scalar(select(func.count()).select_from(IngredientAvailabilityOverride)) == 0
    )

    confirmed = await executor.execute(
        session,
        "owner_confirm_availability_proposal",
        {"proposal_id": proposal.data["id"]},
        owner,
        ToolExecutionAuthorization(explicit_user_confirmation=True),
    )
    assert confirmed.ok is True
    assert (
        await session.scalar(select(func.count()).select_from(IngredientAvailabilityOverride)) == 1
    )

    customer_availability = await executor.execute(
        session,
        "dish_get_availability",
        {"dish_id": str(data["tikka"].id)},
        customer,
    )
    assert customer_availability.ok is True
    assert customer_availability.data["available"] is False
    assert "Owner internal note" not in json.dumps(customer_availability.data)

    blocked_submit = await executor.execute(
        session,
        "cart_submit",
        {"quote_token": sold_out_cart.data["quote_token"], "idempotency_key": "sold-out"},
        customer,
        ToolExecutionAuthorization(explicit_user_confirmation=True),
    )
    assert blocked_submit.ok is False
    assert blocked_submit.error is not None
    assert blocked_submit.error.code == "cart_contains_unavailable_items"

    cross_target = await executor.execute(
        session,
        "owner_create_availability_proposal",
        {
            "target_type": "ingredient",
            "target_id": str(data["other_paneer"].id),
            "action": "mark_unavailable",
            "duration_mode": "indefinite",
            "reason_code": "out_of_stock",
        },
        owner,
    )
    assert cross_target.ok is False
    assert cross_target.error is not None
    assert cross_target.error.code == "availability_target_wrong_outlet"

    wrong_owner = AIToolContext(actor_type=AIActorType.OWNER, outlet_id=data["other_outlet"].id)
    cross_proposal = await executor.execute(
        session,
        "owner_get_availability_proposal",
        {"proposal_id": proposal.data["id"]},
        wrong_owner,
    )
    assert cross_proposal.ok is False
    assert cross_proposal.error is not None
    assert cross_proposal.error.code == "ai_scope_violation"


@pytest.mark.asyncio
async def test_read_only_tools_no_mutation_provider_and_safety_audit(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    executor = AIToolExecutor(build_default_registry(), now=lambda: NOW)
    context = customer_context(data)
    before_orders = await session.scalar(select(func.count()).select_from(DiningOrder))
    before_overrides = await session.scalar(
        select(func.count()).select_from(IngredientAvailabilityOverride)
    )
    for tool, args in (
        ("menu_get", {}),
        ("menu_search", {"query": "paneer"}),
        ("dish_get_availability", {"dish_id": str(data["tikka"].id)}),
        ("cart_get", {}),
        ("bill_get_preview", {}),
        ("customer_total_summary", {}),
    ):
        result = await executor.execute(session, tool, args, context)
        assert result.ok is True
        json.dumps(result.model_dump(mode="json"))
    assert before_orders == await session.scalar(select(func.count()).select_from(DiningOrder))
    assert before_overrides == await session.scalar(
        select(func.count()).select_from(IngredientAvailabilityOverride)
    )

    total = await executor.execute(session, "customer_total_summary", {}, context)
    assert total.ok is True
    assert total.data["state"] == "EMPTY"

    class FakeProvider:
        async def generate(
            self,
            *,
            messages: list[AIMessage],
            tool_schemas: list[dict[str, object]],
        ) -> AIModelResponse:
            assert messages
            assert tool_schemas
            return AIModelResponse(message=AIMessage(role="assistant", content="stub"))

    provider: ToolCallingModelProvider = FakeProvider()
    response = await provider.generate(
        messages=[AIMessage(role="user", content="hello")],
        tool_schemas=build_default_registry().get_tool_schemas(AIActorType.CUSTOMER),
    )
    assert response.message is not None
    assert response.message.content == "stub"

    paths = set(app.openapi()["paths"])
    assert not any(path in paths for path in ("/chat", "/ai/message", "/talk-to-menu"))
    migration_files = sorted(
        path.name
        for path in (pytest.importorskip("pathlib").Path("migrations") / "versions").glob("*.py")
    )
    assert migration_files == [
        "002_restaurant_onboarding.py",
        "003_outlet_food_policy.py",
        "004_menu_catalog.py",
        "005_catalog_compliance.py",
        "006_food_policy_semantics.py",
        "007_real_time_availability.py",
        "008_merchandising_and_offers.py",
        "009_customer_menu_currency.py",
        "010_tables_and_dining_sessions.py",
        "011_cart_and_multi_round_orders.py",
        "012_kitchen_order_execution.py",
        "013_billing_tax_invoice.py",
        "014_customer_ai_conversations.py",
        "015_pending_recommendation_interaction.py",
    ]
    forbidden_dependencies = {
        "langchain",
        "llama-index",
        "transformers",
        "torch",
        "vllm",
        "ollama",
        "openai",
        "anthropic",
    }
    installed = {dist.metadata["Name"].casefold() for dist in importlib.metadata.distributions()}
    assert forbidden_dependencies.isdisjoint(installed)
    schemas = build_default_registry().get_tool_schemas(AIActorType.CUSTOMER)
    schema_text = json.dumps(schemas)
    assert "sql" not in schema_text.casefold()
    assert "eval" not in schema_text.casefold()


@pytest.mark.asyncio
async def test_safe_internal_error_does_not_leak_stack_sql_or_paths(session: AsyncSession) -> None:
    class Empty(BaseModel):
        model_config = ConfigDict(extra="forbid")

    async def boom(_session: AsyncSession, _context: AIToolContext, _payload: BaseModel) -> object:
        raise RuntimeError("SELECT * FROM secrets at C:/private/path")

    registry = AIToolRegistry()
    registry.register(
        AIToolDefinition(
            name="boom",
            description="boom",
            input_model=Empty,
            allowed_actor_types=frozenset({AIActorType.CUSTOMER}),
            safety_level=AIToolSafetyLevel.READ_ONLY,
            requires_confirmation=False,
            handler=boom,
        )
    )
    data = await urban_tadka(session)
    result = await AIToolExecutor(registry, now=lambda: NOW).execute(
        session,
        "boom",
        {},
        customer_context(data),
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "ai_tool_internal_error"
    serialized = json.dumps(result.model_dump(mode="json"))
    assert "SELECT" not in serialized
    assert "private" not in serialized
    assert "Traceback" not in serialized
