from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.ai.context import AIActorType, AIToolContext
from ainza_restaurant.ai.db_models import (
    AIConversation,
    AIPendingConfirmationStatus,
    AIPendingToolConfirmation,
)
from ainza_restaurant.ai.models import (
    AIMessage,
    AIModelResponse,
)
from ainza_restaurant.ai.recommendation_draft import (
    RecommendationDraftService,
)
from ainza_restaurant.ai.service import (
    AIConversationNotFound,
    CustomerAIConversationService,
)
from ainza_restaurant.ai.tools.customer import (
    cart_get,
    meal_recommend_accept,
    menu_get_dish,
    orders_get_session,
)
from ainza_restaurant.db.base import Base
from ainza_restaurant.dining.models import DiningSession, RestaurantTable
from ainza_restaurant.domain.enums import DiningSessionStartedVia, DiningSessionStatus
from ainza_restaurant.ordering.schemas import CartItemCreate, CartSubmitRequest
from ainza_restaurant.ordering.service import CartService
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


async def create_table_and_session(
    session: AsyncSession, outlet_id: UUID, table_number: str
) -> tuple[RestaurantTable, DiningSession, str]:
    table = RestaurantTable(
        outlet_id=outlet_id,
        label=f"T{table_number}",
        normalized_label=f"t{table_number.lower()}",
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
    await session.flush()

    service = CustomerAIConversationService(session)
    conv_read = await service.create_conversation(dining_session.public_session_token)
    return table, dining_session, conv_read.conversation_token


@pytest.mark.asyncio
async def test_multi_table_isolation_outlet_a_tables_a1_to_a20_and_outlet_b(
    session: AsyncSession,
) -> None:
    seed = await urban_tadka(session)
    outlet_a = seed["outlet"]
    outlet_b = seed["other_outlet"]
    dish_a = seed["tikka"]
    dish_b = seed["other_dish"]

    # 1. Setup Outlet A with 20 Tables (A1 to A20)
    tables_a: list[tuple[RestaurantTable, DiningSession, str]] = []
    for i in range(1, 21):
        tbl, ds, conv_token = await create_table_and_session(session, outlet_a.id, f"A{i}")
        tables_a.append((tbl, ds, conv_token))

    # 2. Setup Outlet B with 3 Tables (B1, B2, B3)
    tables_b: list[tuple[RestaurantTable, DiningSession, str]] = []
    for i in range(1, 4):
        tbl, ds, conv_token = await create_table_and_session(session, outlet_b.id, f"B{i}")
        tables_b.append((tbl, ds, conv_token))

    # PROVE 1: Table A1 cannot see A2 cart
    cart_svc = CartService(session)
    await cart_svc.add_item(
        tables_a[0][1].public_session_token, CartItemCreate(dish_id=dish_a.id, quantity=2)
    )
    cart_a2 = await cart_svc.get_cart(tables_a[1][1].public_session_token)
    assert cart_a2.item_count == 0
    ctx_a2 = AIToolContext(
        actor_type=AIActorType.CUSTOMER,
        outlet_id=outlet_a.id,
        dining_session_token=tables_a[1][1].public_session_token,
    )
    read_a2 = await cart_get(session, ctx_a2, None)
    assert read_a2.item_count == 0

    # PROVE 2 & 6: Table A1 cannot consume A2 pending recommendation; drafts cannot cross sessions
    draft_a2 = RecommendationDraftService.create_draft(
        outlet_id=outlet_a.id,
        dining_session_id=tables_a[1][1].id,
        recommended_dishes=[dish_a],
        currency_code="INR",
        party_size=2,
    )
    # Attach draft to A2's conversation
    conv_a2 = await session.scalar(
        select(AIConversation).where(AIConversation.public_token == tables_a[1][2])
    )
    conv_a2.pending_recommendation_interaction_json = draft_a2.model_dump(mode="json")
    await session.commit()

    # Table A1 attempting to accept recommendation draft must get no_active_recommendation
    ctx_a1 = AIToolContext(
        actor_type=AIActorType.CUSTOMER,
        outlet_id=outlet_a.id,
        dining_session_token=tables_a[0][1].public_session_token,
    )
    res_a1 = await meal_recommend_accept(session, ctx_a1, None)
    assert res_a1.get("error") == "no_active_recommendation"

    # PROVE 3: Table A1 cannot see A2 orders
    cart_a1 = await cart_svc.get_cart(tables_a[0][1].public_session_token)
    _ = await cart_svc.submit_cart(
        tables_a[0][1].public_session_token,
        CartSubmitRequest(confirm=True, quote_token=cart_a1.quote_token, idempotency_key="r1"),
    )
    orders_a2 = await orders_get_session(session, ctx_a2, None)
    assert len(orders_a2) == 0

    # PROVE 4: Outlet A cannot read Outlet B menu through customer context
    from ainza_restaurant.customer_menu.service import CustomerMenuNotFound

    with pytest.raises(CustomerMenuNotFound):
        await menu_get_dish(session, ctx_a1, type("DishInput", (), {"dish_id": dish_b.id})())

    # PROVE 5: Outlet A cart cannot contain Outlet B dish IDs
    from ainza_restaurant.ordering.service import CartConflict

    with pytest.raises(CartConflict):
        await cart_svc.add_item(
            tables_a[0][1].public_session_token, CartItemCreate(dish_id=dish_b.id, quantity=1)
        )


    # PROVE 7: One customer's confirmation cannot confirm another customer's action
    ai_svc = CustomerAIConversationService(session)
    pending_a1 = AIPendingToolConfirmation(
        conversation_id=(
            await session.scalar(
                select(AIConversation.id).where(AIConversation.public_token == tables_a[0][2])
            )
        ),
        public_confirmation_token="conf_token_a1_unique",
        tool_name="cart_submit",
        validated_arguments_json={},
        confirmation_summary_json={"action": "place_order"},
        status=AIPendingConfirmationStatus.PENDING,
        expires_at=NOW.replace(year=2030),
    )
    session.add(pending_a1)
    await session.commit()

    with pytest.raises(AIConversationNotFound) as exc_conf:
        await ai_svc.confirm(tables_a[1][2], "conf_token_a1_unique", confirm=True)
    assert exc_conf.value.code == "ai_confirmation_not_found"

    # PROVE 8: Duplicate client message retries remain idempotent across conversations
    provider = SequenceProvider(
        [AIModelResponse(message=AIMessage(role="assistant", content="Hello Table A1!"))]
    )
    ai_svc_mock = CustomerAIConversationService(session, provider=provider)
    resp1 = await ai_svc_mock.send_message(
        tables_a[0][2], client_message_id="msg_a1_001", message="Hello"
    )
    assert resp1.assistant_message == "Hello Table A1!"

    resp2 = await ai_svc_mock.send_message(
        tables_a[0][2], client_message_id="msg_a1_001", message="Hello"
    )
    assert resp2.assistant_message == "Hello Table A1!"
    assert len(provider.calls) == 1
