from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ainza_restaurant.ai.db_models import AIConversation, AIConversationMessage
from ainza_restaurant.ai.service import CustomerAIConversationService
from ainza_restaurant.core.config import get_settings
from ainza_restaurant.dining.schemas import ManualSessionStartRequest, TableCreate
from ainza_restaurant.dining.service import DiningService
from ainza_restaurant.ordering.models import DiningOrder
from ainza_restaurant.ordering.service import CartService
from ainza_restaurant.restaurants.models import Restaurant, RestaurantOutlet

STATE_FILE = Path("tmp/v1_acceptance_state.json")
RESTAURANT_SLUG = "urban-tadka-e2e"


async def main() -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            if await session.scalar(text("SELECT 1")) != 1:
                raise RuntimeError("PostgreSQL is not reachable")
            restaurant = await session.scalar(
                select(Restaurant).where(Restaurant.slug == RESTAURANT_SLUG)
            )
            if restaurant is None:
                raise RuntimeError("Urban Tadka E2E restaurant is missing")
            outlet = await session.scalar(
                select(RestaurantOutlet).where(RestaurantOutlet.restaurant_id == restaurant.id)
            )
            if outlet is None:
                raise RuntimeError("Urban Tadka E2E outlet is missing")
            dining = DiningService(session)
            table = await dining.create_table(
                outlet.id,
                TableCreate(label=f"V1-{uuid4().hex[:8]}", capacity=20),
            )
            started = await dining.start_manual_session(
                table.id, ManualSessionStartRequest(party_size=1)
            )
            conversation = await CustomerAIConversationService(session).create_conversation(
                started.session.public_session_token
            )
            cart = await CartService(session).get_cart(started.session.public_session_token)
            order_count = await session.scalar(
                select(func.count())
                .select_from(DiningOrder)
                .where(DiningOrder.dining_session_id == started.session.id)
            )
            if cart.items or order_count != 0:
                raise RuntimeError("fresh acceptance state could not be verified")
            stored = await session.scalar(
                select(AIConversation).where(
                    AIConversation.public_token == conversation.conversation_token
                )
            )
            if stored is None or stored.pending_recommendation_interaction_json is not None:
                raise RuntimeError("fresh AI conversation state could not be verified")
            message_count = await session.scalar(
                select(func.count())
                .select_from(AIConversationMessage)
                .where(AIConversationMessage.conversation_id == stored.id)
            )
            if message_count != 0:
                raise RuntimeError("fresh AI conversation contains messages")
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(
                json.dumps(
                    {
                        "session_token": started.session.public_session_token,
                        "conversation_token": conversation.conversation_token,
                        "table_id": str(table.id),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            print("[PASS] PostgreSQL reachable")
            print(f"[PASS] restaurant = {restaurant.name}")
            print("[PASS] fresh acceptance dining session created")
            print("[PASS] cart empty")
            print("[PASS] submitted orders = 0")
            print("[PASS] fresh AI conversation created")
            print("[PASS] pending recommendation state = none")
            print(f"STATE_FILE={STATE_FILE}")
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
