from __future__ import annotations

import asyncio
import time
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.ai.context import AIActorType, AIToolContext
from ainza_restaurant.ai.service import CustomerAIConversationService
from ainza_restaurant.ai.tools.customer import (
    CartAddItemInput,
    CartBatchAddInput,
    CartBatchAddItem,
    MealRecommendationInput,
    MealRecommendReviseInput,
    MenuSearchInput,
    NoArgs,
    cart_add_item,
    cart_add_items,
    cart_get,
    customer_total_summary,
    meal_recommend,
    meal_recommend_revise,
    menu_get,
    menu_search,
)
from ainza_restaurant.db.base import Base
from ainza_restaurant.dining.models import DiningSession, RestaurantTable
from ainza_restaurant.domain.enums import DiningSessionStartedVia, DiningSessionStatus
from ainza_restaurant.ordering.service import CartService
from tests.test_ai_tools import NOW, urban_tadka


@pytest.fixture
async def engine_and_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        yield engine, session_factory, db
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def create_session_fixture(
    db: AsyncSession, outlet_id: UUID, label: str
) -> tuple[DiningSession, str]:
    table = RestaurantTable(
        outlet_id=outlet_id,
        label=f"T_{label}",
        normalized_label=f"t_{label.lower()}",
        public_qr_code=f"qr_{uuid4().hex}",
    )
    db.add(table)
    await db.flush()

    dining_session = DiningSession(
        table_id=table.id,
        public_session_token=f"session_{uuid4().hex}",
        status=DiningSessionStatus.OPEN,
        started_via=DiningSessionStartedVia.QR,
        opened_at=NOW,
    )
    db.add(dining_session)
    await db.flush()

    service = CustomerAIConversationService(db)
    conv_read = await service.create_conversation(dining_session.public_session_token)
    return dining_session, conv_read.conversation_token


@pytest.mark.asyncio
async def test_40_session_concurrency_stress(engine_and_session) -> None:
    engine, session_factory, db = engine_and_session
    seed = await urban_tadka(db)
    outlet_a = seed["outlet"]
    outlet_b = seed["other_outlet"]
    dish_a = seed["tikka"]
    dish_b = seed["other_dish"]

    # 1. Setup 40 simultaneous sessions (20 on Outlet A, 20 on Outlet B)
    sessions_a: list[tuple[DiningSession, str]] = []
    for i in range(20):
        ds, conv = await create_session_fixture(db, outlet_a.id, f"A_{i}")
        sessions_a.append((ds, conv))

    sessions_b: list[tuple[DiningSession, str]] = []
    for i in range(20):
        ds, conv = await create_session_fixture(db, outlet_b.id, f"B_{i}")
        sessions_b.append((ds, conv))

    await db.commit()

    all_sessions = [(s[0], s[1], outlet_a.id, dish_a.id, "A") for s in sessions_a] + [
        (s[0], s[1], outlet_b.id, dish_b.id, "B") for s in sessions_b
    ]
    assert len(all_sessions) == 40

    latencies: list[float] = []
    errors: list[str] = []

    # 2. Define concurrent worker for mixed operations
    async def run_session_worker(
        index: int, ds: DiningSession, conv_token: str, outlet_id: UUID, dish_id: UUID, group: str
    ):
        start_t = time.perf_counter()
        try:
            async with session_factory() as session:
                ctx = AIToolContext(
                    actor_type=AIActorType.CUSTOMER,
                    outlet_id=outlet_id,
                    dining_session_token=ds.public_session_token,
                )
                op_type = index % 4
                if op_type == 0:
                    # Operation 1: Menu questions
                    m_res = await menu_get(session, ctx, NoArgs())
                    assert len(m_res["categories"]) >= 1
                    s_res = await menu_search(session, ctx, MenuSearchInput(text_query="paneer"))
                    assert len(s_res) >= 1
                elif op_type == 1:
                    # Operation 2: Meal recommendation & revision
                    reco = await meal_recommend(session, ctx, MealRecommendationInput(party_size=2))
                    assert "items" in reco or "message" in reco
                    rev = await meal_recommend_revise(
                        session, ctx, MealRecommendReviseInput(make_cheaper=True)
                    )
                    assert "items" in rev or rev.get("revised") is True
                elif op_type == 2:
                    # Operation 3: Single and multi-item cart additions
                    added = await cart_add_item(
                        session, ctx, CartAddItemInput(dish_id=dish_id, quantity=1)
                    )
                    assert added.item_count >= 1
                    batch = await cart_add_items(
                        session,
                        ctx,
                        CartBatchAddInput(
                            items=[CartBatchAddItem(dish_id=dish_id, quantity=2, required=True)]
                        ),
                    )
                    assert batch["overall_status"] == "SUCCESS"
                elif op_type == 3:
                    # Operation 4: Cart inspection and current totals
                    added = await cart_add_item(
                        session, ctx, CartAddItemInput(dish_id=dish_id, quantity=1)
                    )
                    assert added.item_count >= 1
                    session.expire_all()
                    cart = await cart_get(session, ctx, NoArgs())
                    assert cart.item_count >= 1
                    totals = await customer_total_summary(session, ctx, NoArgs())
                    assert totals["cart_has_items"] is True

                elapsed = time.perf_counter() - start_t
                latencies.append(elapsed)
        except Exception as exc:
            errors.append(f"Session {index} ({group}): {type(exc).__name__} - {exc}")

    # 3. Execute all 40 simultaneous sessions concurrently
    tasks = [
        run_session_worker(i, item[0], item[1], item[2], item[3], item[4])
        for i, item in enumerate(all_sessions)
    ]
    await asyncio.gather(*tasks)

    # 4. Verify results
    assert len(errors) == 0, f"Errors occurred during 40 concurrent sessions: {errors}"
    assert len(latencies) == 40

    min_lat = min(latencies)
    max_lat = max(latencies)
    avg_lat = sum(latencies) / len(latencies)

    # 5. Verify zero cross-session contamination across all carts
    async with session_factory() as session:
        cart_service = CartService(session)
        for i, (ds, _conv_token, _outlet_id, dish_id, group) in enumerate(all_sessions):
            cart = await cart_service.get_cart(ds.public_session_token)
            op_type = i % 4
            if op_type in (2, 3):
                # Should only contain items added in its own session
                for it in cart.items:
                    assert it.dish_id == dish_id, (
                        f"Contamination: dish {it.dish_id} in {group} session"
                    )
            else:
                assert cart.item_count == 0, (
                    f"Session {i} should have empty cart but has {cart.item_count}"
                )

    print(
        f"\n[40-Session Concurrency] All 40 passed! "
        f"Min: {min_lat * 1000:.1f}ms, Avg: {avg_lat * 1000:.1f}ms, Max: {max_lat * 1000:.1f}ms"
    )

