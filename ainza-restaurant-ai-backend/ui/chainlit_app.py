"""
Ainza Restaurant AI — Chainlit Test UI
=======================================
Tests the full AI stack end-to-end via the REST API.

SETUP
-----
1. Start the backend:
       uvicorn src.ainza_restaurant.main:app --reload

2. Set env vars (or edit the defaults below):
       AINZA_API_URL=http://localhost:8000
       AINZA_SESSION_TOKEN=<your-dining-session-token>

3. Run this UI:
       .venv\\Scripts\\chainlit run ui\\chainlit_app.py --port 8001

You can get a dining session token from:
  - The Ainza POS app
  - The /api/v1/dining-sessions endpoint directly
  - Or the test fixtures in tests/test_ai_tools.py
"""

from __future__ import annotations

import os
import uuid
from typing import Any

# ── Chainlit asyncpg fix ───────────────────────────────────────────────────────
# Chainlit's built-in data layer reads DATABASE_URL and passes it directly to
# asyncpg, which rejects SQLAlchemy's "postgresql+asyncpg://" dialect prefix.
# We clear it here (before chainlit import) so Chainlit runs in stateless mode.
# Our own backend still reads DATABASE_URL fine — it's already loaded at startup.
_db_url = os.environ.pop("DATABASE_URL", None)

import httpx
import chainlit as cl
from chainlit.input_widget import TextInput

# ── Configuration ──────────────────────────────────────────────────────────────

_DEFAULT_API_URL = os.getenv("AINZA_API_URL", "http://localhost:8000")
_DEFAULT_SESSION_TOKEN = os.getenv("AINZA_SESSION_TOKEN", "")

# ── Helpers ────────────────────────────────────────────────────────────────────


def _api_url() -> str:
    return cl.user_session.get("api_url") or _DEFAULT_API_URL


def _conversation_token() -> str | None:
    return cl.user_session.get("conversation_token")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=_api_url(), timeout=90.0)


async def _create_conversation(session_token: str) -> dict[str, Any]:
    async with _client() as c:
        r = await c.post(f"/api/v1/dining-sessions/{session_token}/ai/conversations")
        r.raise_for_status()
        return r.json()


async def _send_message(conversation_token: str, message: str) -> dict[str, Any]:
    async with _client() as c:
        r = await c.post(
            f"/api/v1/ai/conversations/{conversation_token}/messages",
            json={
                "client_message_id": str(uuid.uuid4()),
                "message": message,
            },
        )
        r.raise_for_status()
        return r.json()


async def _stream_message(conversation_token: str, message: str):
    """Async generator that yields parsed SSE event dicts from the streaming endpoint.

    Each event dict has at minimum a ``type`` field.  Known types:
    ``tool_start``, ``tool_done``, ``token``, ``done``, ``error``.
    """
    import json as _json

    payload = {
        "client_message_id": str(uuid.uuid4()),
        "message": message,
    }
    timeout = httpx.Timeout(connect=10.0, read=90.0, write=10.0, pool=10.0)
    async with httpx.AsyncClient(base_url=_api_url(), timeout=timeout) as c:
        async with c.stream(
            "POST",
            f"/api/v1/ai/conversations/{conversation_token}/messages/stream",
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                try:
                    yield _json.loads(data)
                except _json.JSONDecodeError:
                    continue


async def _confirm_action(
    conversation_token: str, confirmation_token: str, confirm: bool
) -> dict[str, Any]:
    async with _client() as c:
        r = await c.post(
            f"/api/v1/ai/conversations/{conversation_token}/confirmations/{confirmation_token}",
            json={"confirm": confirm},
        )
        r.raise_for_status()
        return r.json()


# ── Chainlit lifecycle ─────────────────────────────────────────────────────────


@cl.on_settings_update
async def on_settings_update(settings: dict[str, Any]) -> None:
    cl.user_session.set("api_url", settings.get("api_url", _DEFAULT_API_URL))
    session_token: str = (settings.get("session_token") or "").strip()
    if session_token:
        await _init_conversation(session_token)


@cl.on_chat_start
async def on_chat_start() -> None:
    # Show configurable settings panel
    await cl.ChatSettings(
        [
            TextInput(
                id="api_url",
                label="API Base URL",
                initial=_DEFAULT_API_URL,
                description="URL of the running Ainza FastAPI backend",
            ),
            TextInput(
                id="session_token",
                label="Dining Session Token",
                initial=_DEFAULT_SESSION_TOKEN,
                description="Token for the dining session you want to test with",
            ),
        ]
    ).send()

    cl.user_session.set("api_url", _DEFAULT_API_URL)

    if _DEFAULT_SESSION_TOKEN:
        await _init_conversation(_DEFAULT_SESSION_TOKEN)
    else:
        await cl.Message(
            content=(
                "👋 **Welcome to the Ainza AI Test Console**\n\n"
                "To get started:\n"
                "1. Open the **Settings ⚙️** panel (top-right)\n"
                "2. Enter your **API Base URL** (default: `http://localhost:8000`)\n"
                "3. Enter your **Dining Session Token**\n\n"
                "Then start chatting! The AI will handle menu discovery, cart management, "
                "and order placement — all via the live backend.\n\n"
                "---\n"
                "💡 **No session token?** Run the backend and create a dining session via "
                "`POST /api/v1/dining-sessions`, or check `tests/test_ai_tools.py`."
            ),
            author="System",
        ).send()


async def _init_conversation(session_token: str) -> None:
    """Create a new AI conversation for the given session token."""
    async with cl.Step(name="Connecting to backend", type="tool", show_input=False) as step:
        try:
            data = await _create_conversation(session_token)
            conversation_token: str = data["conversation_token"]
            cl.user_session.set("conversation_token", conversation_token)
            step.output = f"✅ Conversation created: `{conversation_token[:12]}…`"
        except httpx.HTTPStatusError as exc:
            step.is_error = True
            step.output = (
                f"❌ Failed to create conversation: HTTP {exc.response.status_code}\n"
                f"{exc.response.text[:300]}"
            )
            await cl.Message(
                content=(
                    f"⚠️ Could not connect to the backend.\n\n"
                    f"**Status**: `{exc.response.status_code}`\n"
                    f"**Response**: `{exc.response.text[:200]}`\n\n"
                    "Check that the FastAPI server is running and the session token is valid."
                ),
                author="System",
            ).send()
            return
        except Exception as exc:
            step.is_error = True
            step.output = str(exc)
            await cl.Message(
                content=(
                    f"⚠️ Could not reach the backend at `{_api_url()}`.\n\n"
                    f"Error: `{exc}`\n\n"
                    "Make sure the server is running:\n"
                    "```\nuvicorn src.ainza_restaurant.main:app --reload\n```"
                ),
                author="System",
            ).send()
            return

    await cl.Message(
        content=(
            "🍽️ **Restaurant AI ready!** Ask me anything:\n"
            "- *\"Show me the menu\"*\n"
            "- *\"I want something spicy and vegetarian under ₹300\"*\n"
            "- *\"Add 2 paneer tikkas to my cart\"*\n"
            "- *\"What's my bill?\"*\n"
            "- *\"Place my order\"*"
        ),
        author="Assistant",
    ).send()


@cl.on_message
async def on_message(msg: cl.Message) -> None:
    conversation_token = _conversation_token()
    if not conversation_token:
        await cl.Message(
            content="⚠️ No conversation active. Open Settings ⚙️ and enter your session token.",
            author="System",
        ).send()
        return

    # Live message bubble — tokens stream into it
    ai_msg = cl.Message(content="", author="Assistant")
    done_payload: dict[str, Any] = {}
    tools_active: list[str] = []

    async with cl.Step(name="Processing…", type="llm", show_input=False) as step:
        try:
            async for event in _stream_message(conversation_token, msg.content):
                etype = event.get("type", "")

                if etype == "tool_start":
                    tool = event.get("tool", "?")
                    tools_active.append(tool)
                    step.name = f"🔧 {', '.join(tools_active)}"
                    await step.update()

                elif etype == "tool_done":
                    ok = event.get("ok", True)
                    tool = event.get("tool", "?")
                    icon = "✅" if ok else "❌"
                    step.output = (step.output or "") + f"{icon} `{tool}`\n"

                elif etype == "token":
                    token_text = event.get("content", "")
                    if token_text:
                        # Stream into the message bubble
                        await ai_msg.stream_token(token_text)

                elif etype == "done":
                    done_payload = event
                    if not tools_active:
                        step.name = "Conversational reply"
                    else:
                        step.name = f"Used: {', '.join(tools_active)}"

                elif etype == "error":
                    step.is_error = True
                    step.output = f"❌ {event.get('code')}: {event.get('message')}"
                    await ai_msg.stream_token(
                        "\n\n⚠️ " + (event.get("message") or "An error occurred")
                    )
                    break

        except httpx.HTTPStatusError as exc:
            step.is_error = True
            step.output = f"HTTP {exc.response.status_code}"
            await cl.Message(
                content=f"❌ Backend error `{exc.response.status_code}`",
                author="System",
            ).send()
            return
        except Exception as exc:
            step.is_error = True
            step.output = str(exc)
            await cl.Message(content=f"❌ Request failed: `{exc}`", author="System").send()
            return

    # Finalize the streaming message
    await ai_msg.update()

    if not done_payload:
        return

    confirmation: dict[str, Any] | None = done_payload.get("confirmation_required")
    discovery: dict[str, Any] | None = done_payload.get("discovery")
    interaction: dict[str, Any] | None = done_payload.get("interaction")
    navigation: list[dict[str, Any]] = done_payload.get("navigation") or []
    assistant_message: str = done_payload.get("assistant_message") or ""

    elements: list[cl.Element] = []
    if discovery and not discovery.get("no_match"):
        disc = _discovery_element(discovery)
        if disc:
            elements.append(disc)

    msg_actions: list[cl.Action] = []

    if confirmation:
        token = confirmation["confirmation_token"]
        currency = confirmation.get("currency_code", "")
        amount = confirmation.get("subtotal_after_discount", "")
        count = confirmation.get("item_count", "")
        msg_actions = [
            cl.Action(
                name="confirm_order",
                payload={"token": token, "confirm": True},
                label=f"✅ Yes — place order ({count} items · {currency} {amount})",
            ),
            cl.Action(
                name="confirm_order",
                payload={"token": token, "confirm": False},
                label="❌ Cancel — go back",
            ),
        ]

    if interaction:
        question = interaction.get("question", "")
        options: list[dict[str, Any]] = interaction.get("options") or []
        msg_actions = [
            cl.Action(
                name="quick_reply",
                payload={"text": opt["label"]},
                label=opt["label"],
            )
            for opt in options
        ]

    nav_text = _fmt_navigation(navigation)
    if nav_text or elements or msg_actions:
        # Send a follow-up message for the interactive bits
        follow_up = nav_text or ""
        await cl.Message(
            content=follow_up,
            author="Assistant",
            actions=msg_actions,
            elements=elements,
        ).send()


@cl.action_callback("confirm_order")
async def on_confirm_order(action: cl.Action) -> None:
    conversation_token = _conversation_token()
    if not conversation_token:
        return

    token: str = action.payload["token"]
    confirm: bool = action.payload["confirm"]
    label = "Placing order…" if confirm else "Cancelling…"

    result: dict[str, Any] = {}
    async with cl.Step(name=label, type="tool", show_input=False) as step:
        try:
            result = await _confirm_action(conversation_token, token, confirm)
            step.output = f"✅ Status: `{result.get('status')}`"
        except Exception as exc:
            step.is_error = True
            step.output = f"❌ {exc}"
            await cl.Message(content=f"❌ Confirmation failed: `{exc}`", author="System").send()
            return

    await cl.Message(
        content=(
            result.get("assistant_message")
            or ("🎉 Order placed successfully!" if confirm else "Order cancelled.")
        ),
        author="Assistant",
    ).send()


@cl.action_callback("quick_reply")
async def on_quick_reply(action: cl.Action) -> None:
    """Relay quick-reply button clicks as new user messages."""
    text: str = action.payload.get("text", "")
    if text:
        await on_message(cl.Message(content=text, author="User"))


# ── Formatters ─────────────────────────────────────────────────────────────────


def _fmt_tools(tools: list[str]) -> str:
    return "\n".join(f"- `{t}`" for t in tools)


def _fmt_navigation(nav: list[dict[str, Any]]) -> str:
    labels = {
        "browse_categories": "📂 Browse categories",
        "browse_category": "📁 Browse this category",
        "add_more_current_category": "➕ Add more",
        "view_cart": "🛒 View cart",
        "review_checkout": "💳 Review checkout",
    }
    hints = [labels.get(n.get("action", ""), n.get("action", "")) for n in nav]
    return "💡 " + " · ".join(hints) if hints else ""


def _discovery_element(discovery: dict[str, Any]) -> cl.Text | None:
    lines: list[str] = []

    query = discovery.get("requested_query")
    if query:
        lines.append(f'_Search results for: "{query}"_\n')

    categories = discovery.get("categories") or []
    if categories:
        lines.append("**Menu Categories**")
        for cat in categories:
            lines.append(f"- {cat['name']}")

    category = discovery.get("category")
    if category:
        lines.append(f"\n**{category['name']}**")
        desc = category.get("description")
        if desc:
            lines.append(f"_{desc}_\n")
        for item in category.get("dishes") or []:
            dish = item.get("dish") or {}
            addable = item.get("addable", True)
            pricing = dish.get("pricing") or {}
            price = pricing.get("effective_price") or pricing.get("starting_price")
            price_str = f"  ₹{price}" if price else ""
            unavail = "  _(unavailable)_" if not addable else ""
            lines.append(f"- **{dish.get('name', '?')}**{price_str}{unavail}")

    if not lines:
        return None

    return cl.Text(name="discovery", content="\n".join(lines), display="inline")
