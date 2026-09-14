from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ainza_restaurant.core.config import get_settings
from ainza_restaurant.dining.models import RestaurantTable
from ainza_restaurant.restaurants.models import Restaurant, RestaurantOutlet

E2E_DATABASE = "ainza_restaurant_e2e"
FIXTURE_SLUG = "urban-tadka-e2e"


def request_json(
    method: str, url: str, payload: dict[str, object] | None = None
) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API {method} {url} returned {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"API {method} {url} failed: {exc.reason}") from exc


async def fixture_context() -> tuple[str, str, str]:
    database_url = make_url(get_settings().database_url).set(database=E2E_DATABASE)
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            database_name = await session.scalar(text("SELECT current_database()"))
            if database_name != E2E_DATABASE:
                raise RuntimeError("refusing to prepare a non-E2E database")
            version = await session.scalar(text("SHOW server_version"))
            restaurant = await session.scalar(
                select(Restaurant).where(Restaurant.slug == FIXTURE_SLUG)
            )
            if restaurant is None:
                raise RuntimeError("Urban Tadka E2E fixture is missing")
            outlet = await session.scalar(
                select(RestaurantOutlet).where(RestaurantOutlet.restaurant_id == restaurant.id)
            )
            if outlet is None:
                raise RuntimeError("Urban Tadka outlet is missing")
            table = await session.scalar(
                select(RestaurantTable).where(
                    RestaurantTable.outlet_id == outlet.id, RestaurantTable.label == "T3"
                )
            )
            if table is None:
                raise RuntimeError("Urban Tadka table T3 is missing")
            return str(table.id), restaurant.name, str(version)
    finally:
        await engine.dispose()


def valid_saved_state(path: Path, api_base: str, session_id: str) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        token = str(state["conversation_token"])
        conversation = request_json("GET", f"{api_base}/api/v1/ai/conversations/{token}")
    except (KeyError, OSError, ValueError, RuntimeError):
        return None
    if str(conversation.get("dining_session_id")) != session_id:
        return None
    return state


async def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the real T3 typed-chat handoff.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--state-file", default="tmp/human_typed_test.json")
    args = parser.parse_args()
    api_base = args.api_base.rstrip("/")
    state_path = Path(args.state_file)

    table_id, restaurant_name, postgres_version = await fixture_context()
    active = request_json("GET", f"{api_base}/api/v1/tables/{table_id}/active-session")
    session = active.get("session")
    if session is None:
        started = request_json(
            "POST", f"{api_base}/api/v1/tables/{table_id}/sessions", {"party_size": 1}
        )
        session = started["session"]
    session_token = str(session["public_session_token"])
    session_id = str(session["id"])

    state = valid_saved_state(state_path, api_base, session_id)
    if state is None:
        created = request_json(
            "POST", f"{api_base}/api/v1/dining-sessions/{session_token}/ai/conversations", {}
        )
        state = {
            "conversation_token": created["conversation_token"],
            "session_token": session_token,
            "table": "T3",
            "restaurant": restaurant_name,
            "outlet": "Urban Tadka - Vesu",
        }
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    print("[PASS] PostgreSQL reachable")
    print(f"[PASS] database = {E2E_DATABASE} ({postgres_version})")
    print(f"[PASS] restaurant = {restaurant_name}")
    print("[PASS] T3 session exists")
    print("[PASS] real AIConversation exists")
    print(f"STATE_FILE={state_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
