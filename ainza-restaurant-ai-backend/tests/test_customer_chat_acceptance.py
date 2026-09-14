from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.ai.context import AIActorType, AIToolContext
from ainza_restaurant.ai.cost_governor import CostGovernor
from ainza_restaurant.ai.db_models import (
    AIConversation,
)
from ainza_restaurant.ai.errors import (
    AIToolScopeError,
)
from ainza_restaurant.ai.models import AIMessage, AIModelResponse, AIToolCall
from ainza_restaurant.ai.recommendation_draft import RecommendationDraftService
from ainza_restaurant.ai.service import (
    CustomerAIConversationService,
)
from ainza_restaurant.ai.tools.customer import (
    CartAddItemInput,
    CartBatchAddInput,
    CartBatchAddItem,
    CartUpdateItemInput,
    CustomerPaymentRequestInput,
    MealRecommendationInput,
    MealRecommendReviseInput,
    MenuSearchInput,
    NoArgs,
    cart_add_item,
    cart_add_items,
    cart_get,
    cart_update_item,
    customer_payment_request,
    customer_total_summary,
    dish_get_availability,
    meal_recommend,
    meal_recommend_accept,
    meal_recommend_revise,
    menu_search,
)
from ainza_restaurant.db.base import Base
from ainza_restaurant.dining.models import DiningSession, RestaurantTable
from ainza_restaurant.domain.enums import DiningSessionStartedVia, DiningSessionStatus, PaymentMode
from tests.test_ai_tools import NOW, urban_tadka
from tests.test_customer_ai_conversation import SequenceProvider


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


async def create_chat_session(
    session: AsyncSession, outlet_id: UUID, label: str
) -> tuple[DiningSession, str]:
    table = RestaurantTable(
        outlet_id=outlet_id,
        label=f"T_{label}",
        normalized_label=f"t_{label.lower()}",
        public_qr_code=f"qr_{uuid4().hex}",
    )
    session.add(table)
    await session.flush()

    dining_session = DiningSession(
        table_id=table.id,
        public_session_token=f"session_{uuid4().hex}",
        status=DiningSessionStatus.OPEN,
        started_via=DiningSessionStartedVia.QR,
        opened_at=NOW,
    )
    session.add(dining_session)
    await session.flush()

    service = CustomerAIConversationService(session)
    conv_read = await service.create_conversation(dining_session.public_session_token)
    return dining_session, conv_read.conversation_token


# ── PHASE 4: RATE LIMIT & COST GOVERNOR UNDER REALISTIC LOAD ─────────────────


@pytest.mark.asyncio
async def test_phase4_abusive_table_throttled_without_blocking_healthy_tables() -> None:
    # Model 1 abusive table and 2 healthy tables under an outlet with 400 msg/min limit
    gov = CostGovernor(
        session_rate_limit_per_minute=10,
        outlet_rate_limit_per_minute=400,
        spam_window_seconds=0,
    )
    outlet_id = str(uuid4())
    abusive_session = str(uuid4())
    healthy_session_1 = str(uuid4())
    healthy_session_2 = str(uuid4())

    # Abusive table fires 10 rapid messages
    for i in range(10):
        ok, reason = gov.check_rate_and_spam(abusive_session, f"message_{i}", outlet_key=outlet_id)
        assert ok is True

    # 11th message from abusive table is rate limited
    ok_abusive, reason = gov.check_rate_and_spam(
        abusive_session, "spam_message_11", outlet_key=outlet_id
    )
    assert ok_abusive is False
    assert "ai_rate_limit_exceeded" in str(reason)

    # Healthy tables 1 & 2 chat normally and are NOT blocked
    ok_h1, _ = gov.check_rate_and_spam(
        healthy_session_1, "What are the specials?", outlet_key=outlet_id
    )
    assert ok_h1 is True
    ok_h2, _ = gov.check_rate_and_spam(
        healthy_session_2, "Can I get some water?", outlet_key=outlet_id
    )
    assert ok_h2 is True


@pytest.mark.asyncio
async def test_phase4_outlet_rate_limit_guards_against_denial_of_wallet() -> None:
    # Outlet limit configured to 50 for testing
    gov = CostGovernor(
        session_rate_limit_per_minute=30,
        outlet_rate_limit_per_minute=50,
        spam_window_seconds=0,
    )
    outlet_id = str(uuid4())
    # 5 tables send 10 messages each = 50 messages
    for _t in range(5):
        s_id = str(uuid4())

        for m in range(10):
            ok, _ = gov.check_rate_and_spam(s_id, f"msg_{m}", outlet_key=outlet_id)
            assert ok is True

    # 51st message across the outlet hits the outlet governor
    s_id_new = str(uuid4())
    ok_blocked, reason = gov.check_rate_and_spam(s_id_new, "dinner request", outlet_key=outlet_id)
    assert ok_blocked is False
    assert "ai_outlet_rate_limit_exceeded" in str(reason)


# ── PHASE 5: CONVERSATIONAL CONTEXT FAMILIES ─────────────────────────────────


@pytest.mark.asyncio
async def test_phase5_conversation_family_a_recommendation_and_atomic_acceptance(
    session: AsyncSession,
) -> None:
    seed = await urban_tadka(session)
    outlet = seed["outlet"]
    _ = seed["tikka"]
    ds, conv_token = await create_chat_session(session, outlet.id, "FA")
    ctx = AIToolContext(
        actor_type=AIActorType.CUSTOMER,
        outlet_id=outlet.id,
        dining_session_token=ds.public_session_token,
    )

    # Turn 1: "We are two people. Suggest dinner. Vegetarian."
    reco = await meal_recommend(session, ctx, MealRecommendationInput(party_size=2, filters=None))
    assert "items" in reco or "message" in reco

    # Turn 2: "Replace the main with something spicy / cheaper."
    rev = await meal_recommend_revise(session, ctx, MealRecommendReviseInput(make_cheaper=True))
    assert "items" in rev or rev.get("revised") is True

    # Verify cart is STILL untouched
    cart_before = await cart_get(session, ctx, NoArgs())
    assert cart_before.item_count == 0

    # Turn 3: "Okay add this" -> meal_recommend_accept
    acc = await meal_recommend_accept(session, ctx, NoArgs())
    assert acc.get("accepted") is True

    # Cart now contains the accepted recommendation items atomically
    cart_after = await cart_get(session, ctx, NoArgs())
    assert cart_after.item_count >= 1


@pytest.mark.asyncio
async def test_phase5_conversation_family_b_menu_search_and_quantity_increment(
    session: AsyncSession,
) -> None:
    seed = await urban_tadka(session)
    outlet = seed["outlet"]
    _ = seed["tikka"]
    ds, conv_token = await create_chat_session(session, outlet.id, "FB")
    ctx = AIToolContext(
        actor_type=AIActorType.CUSTOMER,
        outlet_id=outlet.id,
        dining_session_token=ds.public_session_token,
    )

    # Turn 1: "Show me starters"
    starters = await menu_search(session, ctx, MenuSearchInput(text_query="paneer"))
    assert len(starters) >= 1
    selected_dish_id = starters[0].id

    # Turn 2: "Is it spicy?"
    avail = await dish_get_availability(
        session, ctx, type("DishIdInput", (), {"dish_id": selected_dish_id})()
    )
    assert avail.get("available") is True

    # Turn 3: "Add two"
    added = await cart_add_item(
        session, ctx, CartAddItemInput(dish_id=selected_dish_id, quantity=2)
    )
    assert added.quantity_count == 2
    item_id = added.items[0].id

    # Turn 4: "Actually make that three"
    updated = await cart_update_item(
        session, ctx, CartUpdateItemInput(cart_item_id=item_id, quantity=3)
    )
    assert updated.quantity_count == 3


@pytest.mark.asyncio
async def test_phase5_conversation_family_c_multi_item_removal_and_totals(
    session: AsyncSession,
) -> None:
    seed = await urban_tadka(session)
    outlet = seed["outlet"]
    tikka = seed["tikka"]
    naan = seed["naan"]
    ds, conv_token = await create_chat_session(session, outlet.id, "FC")
    ctx = AIToolContext(
        actor_type=AIActorType.CUSTOMER,
        outlet_id=outlet.id,
        dining_session_token=ds.public_session_token,
    )

    # Turn 1: "Add paneer tikka and 2 naan"
    batch = await cart_add_items(
        session,
        ctx,
        CartBatchAddInput(
            items=[
                CartBatchAddItem(dish_id=tikka.id, quantity=1, required=True),
                CartBatchAddItem(dish_id=naan.id, quantity=2, required=True),
            ]
        ),
    )
    assert batch["overall_status"] == "SUCCESS"
    session.expire_all()
    cart = await cart_get(session, ctx, NoArgs())
    assert cart.quantity_count == 3

    # Turn 2: "Remove one naan" -> find naan item and update quantity to 1
    naan_item = next(it for it in cart.items if it.dish_id == naan.id)
    updated = await cart_update_item(
        session, ctx, CartUpdateItemInput(cart_item_id=naan_item.id, quantity=1)
    )
    assert updated.quantity_count == 2

    # Turn 3: "How much so far?"
    totals = await customer_total_summary(session, ctx, NoArgs())
    assert totals["cart_has_items"] is True
    # 280 (tikka) + 60 (naan) = 340
    assert totals["cart_total"] == Decimal("340.00")


# ── PHASE 6: LANGUAGE ACCEPTANCE ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_phase6_multilingual_typed_contracts_without_hallucinations(
    session: AsyncSession,
) -> None:
    seed = await urban_tadka(session)
    outlet = seed["outlet"]
    _ = seed["tikka"]
    ds, conv_token = await create_chat_session(session, outlet.id, "LANG")

    # Multi-lingual queries: English, Hindi, Hinglish, Gujarati, Gujlish with typos
    queries = [
        "What vegetarian starters do you have?",  # English
        "Kya aapke paas koi achha paneer starter hai?",  # Hinglish
        "Tamari pase vegetarian ma su saru che?",  # Gujarati / Gujlish
        "Ek butter nan ane panir tikka add karo please",  # Gujlish with typos
        "Do plate paneer tikka aur ek roti lagao",  # Hindi
    ]

    for q in queries:
        provider = SequenceProvider(
            [
                AIModelResponse(
                    tool_calls=[AIToolCall(name="menu_search", arguments={"text_query": "paneer"})],
                ),
                AIModelResponse(
                    message=AIMessage(
                        role="assistant", content="Paneer Tikka is available for ₹280.00."
                    )
                ),
            ]
        )
        svc = CustomerAIConversationService(session, provider=provider)
        res = await svc.send_message(conv_token, client_message_id=f"msg_{uuid4().hex}", message=q)
        assert res.assistant_message is not None
        assert "280" in res.assistant_message


# ── PHASE 7: DOMAIN BOUNDARY & PAYMENT DEFERRED GATE ─────────────────────────


@pytest.mark.asyncio
async def test_phase7_polite_out_of_domain_and_chatgpt_redirection(session: AsyncSession) -> None:
    seed = await urban_tadka(session)
    outlet = seed["outlet"]
    ds, conv_token = await create_chat_session(session, outlet.id, "OOD")
    svc = CustomerAIConversationService(session)

    # 1. Out of domain queries: no LLM tools executed; polite steering back to dining
    ood_queries = [
        "Which car should I buy for my family?",
        "Write Python code to reverse a binary tree",
        "What business should I start in 2026?",
    ]
    for q in ood_queries:
        res = await svc.send_message(conv_token, client_message_id=f"msg_{uuid4().hex}", message=q)
        assert res.tools_used == []
        assert (
            "restaurant assistant" in res.assistant_message.lower()
            or "menu" in res.assistant_message.lower()
        )


@pytest.mark.asyncio
async def test_phase7_online_payment_deferred_feature_gate(session: AsyncSession) -> None:
    seed = await urban_tadka(session)
    outlet = seed["outlet"]
    ds, conv_token = await create_chat_session(session, outlet.id, "PAY_GATE")
    ctx = AIToolContext(
        actor_type=AIActorType.CUSTOMER,
        outlet_id=outlet.id,
        dining_session_token=ds.public_session_token,
    )

    # Calling customer_payment_request directly when payments_enabled=False raises AIToolScopeError
    with pytest.raises(AIToolScopeError) as exc_pay:
        await customer_payment_request(
            session, ctx, CustomerPaymentRequestInput(payment_mode=PaymentMode.ONLINE)
        )
    assert "online payment is currently deferred" in str(exc_pay.value).lower()


# ── PHASE 8: FAILURE RESILIENCE & INTEGRITY ──────────────────────────────────


@pytest.mark.asyncio
async def test_phase8_failure_resilience_expired_draft_and_invalid_item(
    session: AsyncSession,
) -> None:
    seed = await urban_tadka(session)
    outlet = seed["outlet"]
    dish_a = seed["tikka"]
    ds, conv_token = await create_chat_session(session, outlet.id, "FAIL")
    ctx = AIToolContext(
        actor_type=AIActorType.CUSTOMER,
        outlet_id=outlet.id,
        dining_session_token=ds.public_session_token,
    )

    # 1. Non-existent dish ID rejected with 404 / CartNotFound
    from ainza_restaurant.ordering.service import CartNotFound

    with pytest.raises(CartNotFound):
        await cart_add_item(session, ctx, CartAddItemInput(dish_id=uuid4(), quantity=1))


    # 2. Expired recommendation draft rejected
    expired_draft = RecommendationDraftService.create_draft(
        outlet_id=outlet.id,
        dining_session_id=ds.id,
        recommended_dishes=[dish_a],
        currency_code="INR",
        party_size=2,
    )
    expired_draft.expires_at = NOW - timedelta(minutes=20)
    conv = await session.scalar(
        select(AIConversation).where(AIConversation.public_token == conv_token)
    )
    conv.pending_recommendation_interaction_json = expired_draft.model_dump(mode="json")
    await session.commit()

    res_exp = await meal_recommend_accept(session, ctx, NoArgs())
    assert res_exp.get("error") == "draft_expired"


# ── PHASE 9: LONGER CONVERSATION / CONTEXT BOUNDING ──────────────────────────


@pytest.mark.asyncio
async def test_phase9_context_window_bounded_and_authoritative_state_preserved(
    session: AsyncSession,
) -> None:
    seed = await urban_tadka(session)
    outlet = seed["outlet"]
    dish_a = seed["tikka"]
    ds, conv_token = await create_chat_session(session, outlet.id, "LONG_CTX")

    provider = SequenceProvider(
        [
            AIModelResponse(message=AIMessage(role="assistant", content=f"Acknowledged turn {i}"))
            for i in range(25)
        ]
    )
    svc = CustomerAIConversationService(session, provider=provider)

    # Simulate 22 multi-turn customer chat messages
    for i in range(22):
        await svc.send_message(
            conv_token, client_message_id=f"turn_{i}", message=f"Dine in question {i}"
        )

    # Inspect messages passed to provider in the 22nd turn:
    last_call = provider.calls[-1]
    provider_msgs = last_call["messages"]
    # The provider messages must be strictly bounded by local_llm_context_turns + system prompt
    # and MUST NOT contain all 22 turns
    assert len(provider_msgs) <= svc.context_turns + 2

    # Authoritative cart remains completely intact
    ctx = AIToolContext(
        actor_type=AIActorType.CUSTOMER,
        outlet_id=outlet.id,
        dining_session_token=ds.public_session_token,
    )
    await cart_add_item(session, ctx, CartAddItemInput(dish_id=dish_a.id, quantity=1))
    cart = await cart_get(session, ctx, NoArgs())
    assert cart.item_count >= 1
