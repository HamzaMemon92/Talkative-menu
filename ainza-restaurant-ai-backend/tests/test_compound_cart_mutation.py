"""
Regression tests: compound cart mutation via CustomerAIConversationService.

Root cause: llama_cpp.py build_request() stripped tool_schemas from round 2
whenever in-flight messages contained a tool role message, so cart_update_item
and cart_remove_item could never be called after cart_get.
Fix: always include tool_schemas when non-empty.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.ai.models import AIMessage, AIModelResponse, AIToolCall
from ainza_restaurant.ai.service import CustomerAIConversationService
from ainza_restaurant.db.base import Base
from ainza_restaurant.dining.models import DiningSession, RestaurantTable
from ainza_restaurant.domain.enums import (
    AllergenStatus,
    AvailabilityStatus,
    DietaryClassification,
    DiningSessionStartedVia,
    DiningSessionStatus,
    MenuStatus,
    ReviewStatus,
    SpiceLevel,
)
from ainza_restaurant.menu.models import Category, Dish, Menu
from ainza_restaurant.ordering.schemas import CartItemCreate
from ainza_restaurant.ordering.service import CartService
from ainza_restaurant.restaurants.models import Restaurant, RestaurantOutlet
from tests.test_ai_tools import NOW


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        yield db
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _seed(session: AsyncSession) -> dict[str, object]:
    """Seed acceptance kitchen with kebab / kolhapuri / roti."""
    rid = uuid4().hex
    restaurant = Restaurant(name="Acceptance Kitchen", slug=f"acceptance-{rid}")
    session.add(restaurant)
    await session.flush()
    outlet = RestaurantOutlet(
        restaurant_id=restaurant.id,
        name="AK Main",
        address_line1="1 Test Rd",
        city="Surat",
        state="Gujarat",
        postal_code="395007",
        timezone="Asia/Kolkata",
        currency_code="INR",
        is_primary=True,
    )
    session.add(outlet)
    await session.flush()
    menu = Menu(
        restaurant_id=restaurant.id,
        outlet_id=outlet.id,
        name="All Day",
        status=MenuStatus.PUBLISHED,
        published_at=NOW,
    )
    session.add(menu)
    await session.flush()
    starters = Category(menu_id=menu.id, name="Starters", slug="starters")
    mains = Category(menu_id=menu.id, name="Mains", slug="mains")
    breads = Category(menu_id=menu.id, name="Breads", slug="breads")
    session.add_all([starters, mains, breads])
    await session.flush()
    kebab = Dish(
        menu_id=menu.id,
        category_id=starters.id,
        name="Hara Bhara Kebab",
        base_price=Decimal("240.00"),
        review_status=ReviewStatus.CONFIRMED,
        dietary_classification=DietaryClassification.VEGETARIAN,
        vegan_status=AvailabilityStatus.UNKNOWN,
        jain_status=AvailabilityStatus.UNKNOWN,
        spice_level=SpiceLevel.UNKNOWN,
        allergen_information_status=AllergenStatus.UNKNOWN,
    )
    kolhapuri = Dish(
        menu_id=menu.id,
        category_id=mains.id,
        name="Veg Kolhapuri",
        base_price=Decimal("300.00"),
        review_status=ReviewStatus.CONFIRMED,
        dietary_classification=DietaryClassification.VEGETARIAN,
        vegan_status=AvailabilityStatus.UNKNOWN,
        jain_status=AvailabilityStatus.UNKNOWN,
        spice_level=SpiceLevel.UNKNOWN,
        allergen_information_status=AllergenStatus.UNKNOWN,
    )
    roti = Dish(
        menu_id=menu.id,
        category_id=breads.id,
        name="Tandoori Roti",
        base_price=Decimal("45.00"),
        review_status=ReviewStatus.CONFIRMED,
        dietary_classification=DietaryClassification.VEGETARIAN,
        vegan_status=AvailabilityStatus.UNKNOWN,
        jain_status=AvailabilityStatus.UNKNOWN,
        spice_level=SpiceLevel.UNKNOWN,
        allergen_information_status=AllergenStatus.UNKNOWN,
    )
    session.add_all([kebab, kolhapuri, roti])
    await session.flush()
    table = RestaurantTable(
        outlet_id=outlet.id,
        label="T1",
        normalized_label="t1",
        public_qr_code=f"qr-{uuid4().hex}",
    )
    session.add(table)
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
    return {
        "outlet": outlet,
        "dining_session": dining_session,
        "kebab": kebab,
        "kolhapuri": kolhapuri,
        "roti": roti,
    }


async def _seed_cart(session: AsyncSession, data: dict[str, object]) -> None:
    """Kebab x1 + Kolhapuri x1 + Roti x2 — the live acceptance cart."""
    svc = CartService(session)
    token: str = data["dining_session"].public_session_token  # type: ignore[attr-defined]
    await svc.add_item(token, CartItemCreate(dish_id=data["kebab"].id, quantity=1))
    await svc.add_item(token, CartItemCreate(dish_id=data["kolhapuri"].id, quantity=1))
    await svc.add_item(token, CartItemCreate(dish_id=data["roti"].id, quantity=2))


async def _cart_ids(session: AsyncSession, data: dict[str, object]) -> dict[str, str]:
    svc = CartService(session)
    token: str = data["dining_session"].public_session_token  # type: ignore[attr-defined]
    cart = await svc.get_cart(token)
    return {item.dish_name: str(item.id) for item in cart.items}


class SequenceProvider:
    def __init__(self, responses: list[AIModelResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def generate(
        self,
        *,
        messages: list[AIMessage],
        tool_schemas: list[dict[str, object]],
        tool_results: list[dict[str, object]] | None = None,
    ) -> AIModelResponse:
        self.calls.append(
            {
                "messages": messages,
                "tool_schemas": tool_schemas,
                "tool_results": list(tool_results or []),
            }
        )
        return self.responses.pop(0)


async def _svc_conv(
    session: AsyncSession,
    data: dict[str, object],
    provider: SequenceProvider,
) -> tuple[CustomerAIConversationService, str]:
    svc = CustomerAIConversationService(session, provider=provider, now=lambda: NOW)
    token: str = data["dining_session"].public_session_token  # type: ignore[attr-defined]
    created = await svc.create_conversation(token)
    return svc, created.conversation_token


# ─── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_request_includes_tools_when_in_flight_has_tool_messages() -> None:
    """Regression guard: build_request must NOT strip tools on round 2+."""
    from ainza_restaurant.ai.providers.llama_cpp import LlamaCppToolCallingProvider

    p = LlamaCppToolCallingProvider(base_url="http://localhost:11434", model="dummy")
    schema = {
        "name": "cart_update_item",
        "description": "update cart",
        "input_schema": {"type": "object", "properties": {}},
    }
    msgs = [
        AIMessage(role="system", content="You are a waiter."),
        AIMessage(role="user", content="roti 3 kar do"),
        AIMessage(
            role="assistant",
            content=None,
            tool_calls=[AIToolCall(id="tc1", name="cart_get", arguments={})],
        ),
        AIMessage(role="tool", content='{"items": []}', tool_call_id="tc1"),
    ]
    req = p.build_request(msgs, [schema], [])
    assert "tools" in req, (
        "BUG REGRESSION: tools stripped from round-2 request when tool messages are in-flight"
    )
    assert any(t["function"]["name"] == "cart_update_item" for t in req["tools"])
    assert req["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_build_request_excludes_tools_when_schema_is_empty() -> None:
    """Synthesis round with tool_schemas=[] must produce no tools key."""
    from ainza_restaurant.ai.providers.llama_cpp import LlamaCppToolCallingProvider

    p = LlamaCppToolCallingProvider(base_url="http://localhost:11434", model="dummy")
    msgs = [
        AIMessage(role="system", content="Synthesise answer."),
        AIMessage(role="user", content="roti 3 kar do"),
        AIMessage(
            role="assistant",
            content=None,
            tool_calls=[AIToolCall(id="tc1", name="cart_get", arguments={})],
        ),
        AIMessage(role="tool", content='{"items": []}', tool_call_id="tc1"),
    ]
    req = p.build_request(msgs, [], [])
    assert "tools" not in req
    assert "tool_choice" not in req


@pytest.mark.asyncio
async def test_compound_mutation_roti_qty_and_remove_starter(session: AsyncSession) -> None:
    """
    Live acceptance scenario: roti 2->3 AND starter removed in one turn.
    Expected cart: Kolhapuri x1 + Roti x3 = 435.
    """
    data = await _seed(session)
    await _seed_cart(session, data)
    ids = await _cart_ids(session, data)
    roti_id = ids["Tandoori Roti"]
    kebab_id = ids["Hara Bhara Kebab"]

    provider = SequenceProvider(
        [
            AIModelResponse(tool_calls=[AIToolCall(name="cart_get")]),
            AIModelResponse(
                tool_calls=[
                    AIToolCall(
                        name="cart_update_item",
                        arguments={"cart_item_id": roti_id, "quantity": 3},
                    ),
                    AIToolCall(
                        name="cart_remove_item",
                        arguments={"cart_item_id": kebab_id},
                    ),
                ]
            ),
            AIModelResponse(
                message=AIMessage(
                    role="assistant",
                    content="Roti updated to 3, kebab removed. Subtotal: 435.",
                )
            ),
        ]
    )
    svc, conv = await _svc_conv(session, data, provider)
    result = await svc.send_message(
        conv,
        client_message_id="compound-hindi",
        message="ab roti 2 se 3 kar do aur starter hata do",
    )

    assert len(provider.calls) == 3
    assert "cart_get" in result.tools_used
    assert "cart_update_item" in result.tools_used
    assert "cart_remove_item" in result.tools_used

    cart = await CartService(session).get_cart(
        data["dining_session"].public_session_token  # type: ignore[attr-defined]
    )
    dm = {i.dish_name: i for i in cart.items}
    assert "Hara Bhara Kebab" not in dm
    assert dm["Tandoori Roti"].quantity == 3
    assert dm["Veg Kolhapuri"].quantity == 1
    assert cart.subtotal_before_offer == Decimal("435.00")


@pytest.mark.asyncio
async def test_compound_mutation_reverse_order(session: AsyncSession) -> None:
    """Same compound mutation but model issues remove-then-update order."""
    data = await _seed(session)
    await _seed_cart(session, data)
    ids = await _cart_ids(session, data)
    roti_id = ids["Tandoori Roti"]
    kebab_id = ids["Hara Bhara Kebab"]

    provider = SequenceProvider(
        [
            AIModelResponse(tool_calls=[AIToolCall(name="cart_get")]),
            AIModelResponse(
                tool_calls=[
                    AIToolCall(
                        name="cart_remove_item",
                        arguments={"cart_item_id": kebab_id},
                    ),
                    AIToolCall(
                        name="cart_update_item",
                        arguments={"cart_item_id": roti_id, "quantity": 3},
                    ),
                ]
            ),
            AIModelResponse(
                message=AIMessage(
                    role="assistant",
                    content="Kebab removed, roti updated to 3. Subtotal: 435.",
                )
            ),
        ]
    )
    svc, conv = await _svc_conv(session, data, provider)
    await svc.send_message(
        conv, client_message_id="compound-reverse", message="starter hato roti 3 karo"
    )

    cart = await CartService(session).get_cart(
        data["dining_session"].public_session_token  # type: ignore[attr-defined]
    )
    dm = {i.dish_name: i for i in cart.items}
    assert "Hara Bhara Kebab" not in dm
    assert dm["Tandoori Roti"].quantity == 3
    assert cart.subtotal_before_offer == Decimal("435.00")


@pytest.mark.asyncio
async def test_single_quantity_update_only(session: AsyncSession) -> None:
    """Only roti quantity changes; other items untouched."""
    data = await _seed(session)
    await _seed_cart(session, data)
    ids = await _cart_ids(session, data)
    roti_id = ids["Tandoori Roti"]

    provider = SequenceProvider(
        [
            AIModelResponse(tool_calls=[AIToolCall(name="cart_get")]),
            AIModelResponse(
                tool_calls=[
                    AIToolCall(
                        name="cart_update_item",
                        arguments={"cart_item_id": roti_id, "quantity": 3},
                    ),
                ]
            ),
            AIModelResponse(
                message=AIMessage(role="assistant", content="Roti updated to 3.")
            ),
        ]
    )
    svc, conv = await _svc_conv(session, data, provider)
    await svc.send_message(conv, client_message_id="single-qty", message="roti 3 kar do")

    cart = await CartService(session).get_cart(
        data["dining_session"].public_session_token  # type: ignore[attr-defined]
    )
    dm = {i.dish_name: i for i in cart.items}
    assert dm["Tandoori Roti"].quantity == 3
    assert dm["Hara Bhara Kebab"].quantity == 1
    assert dm["Veg Kolhapuri"].quantity == 1
    # 240 + 300 + 3*45 = 675
    assert cart.subtotal_before_offer == Decimal("675.00")


@pytest.mark.asyncio
async def test_single_remove_only(session: AsyncSession) -> None:
    """Only starter removed; roti and main untouched."""
    data = await _seed(session)
    await _seed_cart(session, data)
    ids = await _cart_ids(session, data)
    kebab_id = ids["Hara Bhara Kebab"]

    provider = SequenceProvider(
        [
            AIModelResponse(tool_calls=[AIToolCall(name="cart_get")]),
            AIModelResponse(
                tool_calls=[
                    AIToolCall(
                        name="cart_remove_item",
                        arguments={"cart_item_id": kebab_id},
                    ),
                ]
            ),
            AIModelResponse(
                message=AIMessage(role="assistant", content="Kebab removed.")
            ),
        ]
    )
    svc, conv = await _svc_conv(session, data, provider)
    await svc.send_message(conv, client_message_id="single-remove", message="starter hata do")

    cart = await CartService(session).get_cart(
        data["dining_session"].public_session_token  # type: ignore[attr-defined]
    )
    dm = {i.dish_name: i for i in cart.items}
    assert "Hara Bhara Kebab" not in dm
    assert dm["Veg Kolhapuri"].quantity == 1
    assert dm["Tandoori Roti"].quantity == 2
    # 300 + 2*45 = 390
    assert cart.subtotal_before_offer == Decimal("390.00")


@pytest.mark.asyncio
async def test_compound_with_explicit_no_op_clause(session: AsyncSession) -> None:
    """Model honours no-op clause — does NOT mutate Kolhapuri."""
    data = await _seed(session)
    await _seed_cart(session, data)
    ids = await _cart_ids(session, data)
    roti_id = ids["Tandoori Roti"]

    provider = SequenceProvider(
        [
            AIModelResponse(tool_calls=[AIToolCall(name="cart_get")]),
            AIModelResponse(
                tool_calls=[
                    AIToolCall(
                        name="cart_update_item",
                        arguments={"cart_item_id": roti_id, "quantity": 3},
                    ),
                ]
            ),
            AIModelResponse(
                message=AIMessage(role="assistant", content="Roti now 3. Kolhapuri unchanged.")
            ),
        ]
    )
    svc, conv = await _svc_conv(session, data, provider)
    result = await svc.send_message(
        conv, client_message_id="noop-clause", message="roti 3 karo, main same rehne do"
    )
    assert "cart_remove_item" not in result.tools_used
    assert "cart_update_item" in result.tools_used

    cart = await CartService(session).get_cart(
        data["dining_session"].public_session_token  # type: ignore[attr-defined]
    )
    dm = {i.dish_name: i for i in cart.items}
    assert dm["Veg Kolhapuri"].quantity == 1
    assert dm["Hara Bhara Kebab"].quantity == 1
    assert dm["Tandoori Roti"].quantity == 3


@pytest.mark.asyncio
async def test_midway_mutation_failure_reports_partial_state(session: AsyncSession) -> None:
    """
    update_item succeeds, remove_item with bad ID fails.
    Roti IS updated (committed). Kebab remains. Response is a real string.
    """
    data = await _seed(session)
    await _seed_cart(session, data)
    ids = await _cart_ids(session, data)
    roti_id = ids["Tandoori Roti"]
    bad_id = str(uuid4())

    provider = SequenceProvider(
        [
            AIModelResponse(tool_calls=[AIToolCall(name="cart_get")]),
            AIModelResponse(
                tool_calls=[
                    AIToolCall(
                        name="cart_update_item",
                        arguments={"cart_item_id": roti_id, "quantity": 3},
                    ),
                    AIToolCall(
                        name="cart_remove_item",
                        arguments={"cart_item_id": bad_id},
                    ),
                ]
            ),
            AIModelResponse(
                message=AIMessage(
                    role="assistant",
                    content="Roti updated to 3, but kebab removal failed: item not found.",
                )
            ),
        ]
    )
    svc, conv = await _svc_conv(session, data, provider)
    result = await svc.send_message(
        conv, client_message_id="midway-fail", message="roti 3 karo aur starter hata do"
    )

    cart = await CartService(session).get_cart(
        data["dining_session"].public_session_token  # type: ignore[attr-defined]
    )
    dm = {i.dish_name: i for i in cart.items}
    assert dm["Tandoori Roti"].quantity == 3
    assert "Hara Bhara Kebab" in dm
    assert result.assistant_message  # non-empty response


@pytest.mark.asyncio
async def test_duplicate_client_message_id_is_idempotent(session: AsyncSession) -> None:
    """Re-sending same client_message_id must NOT re-execute tools."""
    data = await _seed(session)
    await _seed_cart(session, data)
    ids = await _cart_ids(session, data)
    roti_id = ids["Tandoori Roti"]
    kebab_id = ids["Hara Bhara Kebab"]

    provider = SequenceProvider(
        [
            AIModelResponse(tool_calls=[AIToolCall(name="cart_get")]),
            AIModelResponse(
                tool_calls=[
                    AIToolCall(
                        name="cart_update_item",
                        arguments={"cart_item_id": roti_id, "quantity": 3},
                    ),
                    AIToolCall(
                        name="cart_remove_item",
                        arguments={"cart_item_id": kebab_id},
                    ),
                ]
            ),
            AIModelResponse(
                message=AIMessage(
                    role="assistant",
                    content="Done. Roti 3, kebab removed. Subtotal: 435.",
                )
            ),
        ]
    )
    svc, conv = await _svc_conv(session, data, provider)
    first = await svc.send_message(
        conv, client_message_id="idem-compound", message="roti 3 aur starter hata do"
    )
    assert len(provider.responses) == 0  # all consumed

    second = await svc.send_message(
        conv, client_message_id="idem-compound", message="roti 3 aur starter hata do"
    )
    assert second.assistant_message == first.assistant_message

    cart = await CartService(session).get_cart(
        data["dining_session"].public_session_token  # type: ignore[attr-defined]
    )
    dm = {i.dish_name: i for i in cart.items}
    assert "Hara Bhara Kebab" not in dm
    assert dm["Tandoori Roti"].quantity == 3
    assert cart.subtotal_before_offer == Decimal("435.00")
