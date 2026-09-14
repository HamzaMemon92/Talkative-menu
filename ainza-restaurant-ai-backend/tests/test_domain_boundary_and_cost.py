from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.ai.cost_governor import CostGovernor, get_cost_governor
from ainza_restaurant.ai.domain_classifier import (
    CustomerDomainCategory,
    get_customer_domain_classifier,
)
from ainza_restaurant.ai.models import AIMessage
from ainza_restaurant.ai.service import (
    CustomerAIConversationService,
)
from ainza_restaurant.db.base import Base
from tests.test_ai_tools import customer_context, urban_tadka
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


@pytest.mark.asyncio
async def test_01_normal_food_conversation_allowed():
    classifier = get_customer_domain_classifier()
    phrases = [
        "What would be nice for dinner?",
        "I'm starving",
        "We want something light",
        "Surprise me",
        "Can you suggest something less spicy?",
    ]
    for phrase in phrases:
        result = classifier.classify(phrase)
        assert result.category in {
            CustomerDomainCategory.RESTAURANT_CONVERSATION,
            CustomerDomainCategory.RESTAURANT_OPERATION,
        }
        assert result.category != CustomerDomainCategory.OUT_OF_DOMAIN


@pytest.mark.asyncio
async def test_02_menu_order_bill_requests_allowed():
    classifier = get_customer_domain_classifier()
    phrases = [
        "Show me the menu",
        "Add 2 Butter Naan to my cart",
        "What's my current bill?",
        "Do you have vegan options?",
        "Can I pay with UPI?",
    ]
    for phrase in phrases:
        result = classifier.classify(phrase)
        assert result.category == CustomerDomainCategory.RESTAURANT_OPERATION
        assert result.category != CustomerDomainCategory.OUT_OF_DOMAIN


@pytest.mark.asyncio
async def test_03_car_buying_question_redirected():
    classifier = get_customer_domain_classifier()
    result = classifier.classify("which car should I buy?")
    assert result.category == CustomerDomainCategory.OUT_OF_DOMAIN
    assert "restaurant assistant" in result.redirect_message.lower()


@pytest.mark.asyncio
async def test_04_coding_question_redirected():
    classifier = get_customer_domain_classifier()
    queries = [
        "write Python code to sort a list",
        "generate a javascript function for calculating primes",
        "can you debug my SQL query?",
    ]
    for query in queries:
        result = classifier.classify(query)
        assert result.category == CustomerDomainCategory.OUT_OF_DOMAIN
        assert "restaurant assistant" in result.redirect_message.lower()


@pytest.mark.asyncio
async def test_05_unrelated_business_advice_redirected():
    classifier = get_customer_domain_classifier()
    queries = [
        "which startup should I start?",
        "how to invest in bitcoin and crypto?",
        "explain quantum physics to me",
    ]
    for query in queries:
        result = classifier.classify(query)
        assert result.category == CustomerDomainCategory.OUT_OF_DOMAIN
        assert "restaurant assistant" in result.redirect_message.lower()


@pytest.mark.asyncio
async def test_06_restaurant_small_talk_still_conversational():
    classifier = get_customer_domain_classifier()
    result = classifier.classify("I'm starving, what's good here?")
    assert result.category == CustomerDomainCategory.RESTAURANT_CONVERSATION


@pytest.mark.asyncio
async def test_07_no_restaurant_tool_called_for_out_of_domain(session: AsyncSession):
    data = await urban_tadka(session)
    context = customer_context(data)
    provider = SequenceProvider([])
    service = CustomerAIConversationService(session, provider=provider)

    conversation = await service.create_conversation(context.dining_session_token)
    reply = await service.send_message(
        conversation.conversation_token,
        client_message_id="msg_car_1",
        message="Which car should I buy?",
    )

    # Must return redirect without calling provider or any tools
    assert len(provider.calls) == 0
    assert reply.tools_used == []
    assert "restaurant assistant" in reply.assistant_message.lower()


@pytest.mark.asyncio
async def test_08_repeated_spam_and_rate_limiting(session: AsyncSession):
    governor = CostGovernor(
        session_rate_limit_per_minute=2,
        spam_window_seconds=30.0,
    )
    session_id = "test_session_spam"

    # First message: allowed
    ok1, reason1 = governor.check_rate_and_spam(session_id, "hello waiter")
    assert ok1 is True

    # Immediate duplicate message: rejected as spam
    ok2, reason2 = governor.check_rate_and_spam(session_id, "hello waiter")
    assert ok2 is False
    assert "repeated" in reason2.lower()

    # Different message but rate limit reached (2 allowed per minute)
    ok3, reason3 = governor.check_rate_and_spam(session_id, "different message")
    assert ok3 is True

    # Exceeds rate limit
    ok4, reason4 = governor.check_rate_and_spam(session_id, "third message")
    assert ok4 is False
    assert "rate" in reason4.lower() and "limit" in reason4.lower()


@pytest.mark.asyncio
async def test_09_bounded_message_context():
    governor = get_cost_governor()
    messages = [AIMessage(role="user", content=f"Message {i}") for i in range(20)]
    bounded = governor.bound_transcript_context(messages, max_messages=6)
    assert len(bounded) == 6
    assert bounded[-1].content == "Message 19"
    assert bounded[0].content == "Message 14"


@pytest.mark.asyncio
async def test_10_cost_governor_configuration_and_accounting():
    governor = CostGovernor(
        session_call_budget=2,
        input_token_cost_per_million=1.5,
        output_token_cost_per_million=2.0,
    )
    session_id = "budget_session_1"
    outlet_id = "outlet_1"

    # Check budget before
    allowed, _ = governor.check_call_budget(session_id=session_id, outlet_id=outlet_id)
    assert allowed is True

    # Record 1 call
    usage1 = governor.record_usage(
        session_id=session_id,
        outlet_id=outlet_id,
        model_calls=1,
        input_tokens=1_000,
        output_tokens=500,
    )
    assert usage1.model_calls == 1
    assert usage1.estimated_cost_usd > 0

    # Record 2nd call
    governor.record_usage(
        session_id=session_id,
        outlet_id=outlet_id,
        model_calls=1,
        input_tokens=1_000,
        output_tokens=500,
    )

    # 3rd call check should exceed budget
    allowed3, reason3 = governor.check_call_budget(session_id=session_id, outlet_id=outlet_id)
    assert allowed3 is False
    assert "budget" in reason3.lower()
