from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ainza_restaurant.ai.context import AIActorType, AIToolContext, ToolExecutionAuthorization
from ainza_restaurant.ai.db_models import (
    AIConversation,
    AIConversationMessage,
    AIMessageRole,
    AIMessageStatus,
    AIPendingConfirmationStatus,
    AIPendingToolConfirmation,
)
from ainza_restaurant.ai.errors import AIToolError
from ainza_restaurant.ai.language import (
    CustomerResponseLanguageMode,
    resolve_customer_response_mode,
    response_mode_instruction,
)
from ainza_restaurant.ai.models import AIMessage, AIModelResponse, AIToolCall, AIToolResult
from ainza_restaurant.ai.prompts import CUSTOMER_SYSTEM_PROMPT
from ainza_restaurant.ai.providers.base import FallbackToolCallingProvider, ToolCallingModelProvider
from ainza_restaurant.ai.providers.cloudflare import CloudflareToolCallingProvider
from ainza_restaurant.ai.providers.llama_cpp import LlamaCppToolCallingProvider
from ainza_restaurant.ai.schemas import (
    AICategoryBrowseDishRead,
    AICategoryBrowseRead,
    AIConfirmationRead,
    AIConfirmationRequiredRead,
    AIConversationCreateRead,
    AIConversationMessageRead,
    AIConversationRead,
    AIDiscoveryRead,
    AIMessageRead,
    AINavigationAction,
    AINavigationRead,
)
from ainza_restaurant.ai.tools.executor import AIToolExecutor
from ainza_restaurant.ai.tools.registry import AIToolRegistry, build_default_registry
from ainza_restaurant.core.config import get_settings
from ainza_restaurant.customer_menu.service import CustomerMenuService
from ainza_restaurant.dining.models import DiningSession, RestaurantTable
from ainza_restaurant.domain.enums import DiningSessionStatus
from ainza_restaurant.ordering.service import CartService
from ainza_restaurant.restaurants.models import Restaurant, RestaurantOutlet


class AIConversationNotFound(LookupError):
    code = "ai_conversation_not_found"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class AIConversationConflict(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "ai_conversation_conflict",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class CustomerAIConversationService:

    def __init__(
        self,
        session: AsyncSession,
        *,
        provider: ToolCallingModelProvider | None = None,
        registry: AIToolRegistry | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.registry = registry or build_default_registry()
        self.provider = provider or _build_provider()
        self.executor = AIToolExecutor(self.registry, now=now)
        self._now = now or (lambda: datetime.now(UTC))
        settings = get_settings()
        self.max_tool_rounds = settings.local_llm_max_tool_rounds
        self.context_turns = settings.local_llm_context_turns
        self.confirmation_ttl_minutes = settings.ai_confirmation_ttl_minutes

    def now(self) -> datetime:
        return _utc(self._now())

    async def create_conversation(self, session_token: str) -> AIConversationCreateRead:
        dining_session, outlet, _restaurant = await self._session_context(session_token)
        await CustomerMenuService(self.session).get_menu(outlet.id)
        conversation = AIConversation(
            dining_session_id=dining_session.id,
            outlet_id=outlet.id,
            public_token=await self._unique_conversation_token(),
        )
        self.session.add(conversation)
        await self.session.commit()
        await self.session.refresh(conversation)
        return AIConversationCreateRead(
            conversation_token=conversation.public_token,
            dining_session_id=conversation.dining_session_id,
            outlet_id=conversation.outlet_id,
            created_at=conversation.created_at,
        )

    async def get_conversation(self, conversation_token: str) -> AIConversationRead:
        conversation = await self._conversation(conversation_token)
        messages = await self._messages(conversation.id)
        return AIConversationRead(
            conversation_token=conversation.public_token,
            dining_session_id=conversation.dining_session_id,
            outlet_id=conversation.outlet_id,
            messages=[
                AIMessageRead(
                    role=message.role,
                    status=message.status,
                    content=message.content,
                    created_at=message.created_at,
                )
                for message in messages
            ],
        )

    async def send_message(
        self, conversation_token: str, *, client_message_id: str, message: str
    ) -> AIConversationMessageRead:
        conversation = await self._conversation(conversation_token)
        duplicate = await self._message_by_client_id(conversation.id, client_message_id)
        if duplicate is not None and duplicate.status in {
            AIMessageStatus.COMPLETED,
            AIMessageStatus.PENDING_CONFIRMATION,
        }:
            return await self._stored_response_for_duplicate(conversation, duplicate)
        if duplicate is not None:
            raise AIConversationConflict(
                "message with this client_message_id is not completed",
                code="ai_message_not_replayable",
            )
        user_message = AIConversationMessage(
            conversation_id=conversation.id,
            client_message_id=client_message_id,
            sequence_number=await self._next_sequence(conversation.id),
            role=AIMessageRole.USER,
            status=AIMessageStatus.PROCESSING,
            content=message,
        )
        self.session.add(user_message)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            existing = await self._message_by_client_id(conversation.id, client_message_id)
            if existing is not None:
                return await self._stored_response_for_duplicate(conversation, existing)
            raise AIConversationConflict("duplicate message", code="ai_message_duplicate") from exc
        try:
            return await self._run_agentic_loop(conversation, user_message)
        except AIToolError as exc:
            user_message.status = AIMessageStatus.FAILED
            user_message.error_code = exc.code
            await self.session.commit()
            raise AIConversationConflict(str(exc), code=exc.code) from exc

    async def stream_message(
        self,
        conversation_token: str,
        *,
        client_message_id: str,
        message: str,
    ):
        """Async generator that yields SSE-formatted event strings.

        Event types emitted (each line is ``data: <json>\\n\\n``):

        ``tool_start``   – a backend tool is about to execute
        ``tool_done``    – a backend tool finished (ok/error)
        ``token``        – one text chunk from the streaming LLM response
        ``done``         – final event carrying tools_used, confirmation_required, etc.
        ``error``        – unrecoverable error; stream ends

        The caller (FastAPI route) must wrap these in proper SSE framing.
        """
        import json as _json

        def _sse(payload: dict) -> str:
            return f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"

        conversation = await self._conversation(conversation_token)
        duplicate = await self._message_by_client_id(conversation.id, client_message_id)
        if duplicate is not None and duplicate.status in {
            AIMessageStatus.COMPLETED,
            AIMessageStatus.PENDING_CONFIRMATION,
        }:
            # Re-stream the stored response as a single token + done event.
            stored = await self._stored_response_for_duplicate(conversation, duplicate)
            yield _sse({"type": "token", "content": stored.assistant_message})
            yield _sse({
                "type": "done",
                "assistant_message": stored.assistant_message,
                "tools_used": stored.tools_used,
                "confirmation_required": stored.confirmation_required.model_dump() if stored.confirmation_required else None,
                "navigation": [n.model_dump() for n in stored.navigation],
                "discovery": stored.discovery.model_dump() if stored.discovery else None,
            })
            return

        if duplicate is not None:
            yield _sse({"type": "error", "code": "ai_message_not_replayable",
                        "message": "message with this client_message_id is not completed"})
            return

        user_message = AIConversationMessage(
            conversation_id=conversation.id,
            client_message_id=client_message_id,
            sequence_number=await self._next_sequence(conversation.id),
            role=AIMessageRole.USER,
            status=AIMessageStatus.PROCESSING,
            content=message,
        )
        self.session.add(user_message)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            existing = await self._message_by_client_id(conversation.id, client_message_id)
            if existing is not None:
                stored = await self._stored_response_for_duplicate(conversation, existing)
                yield _sse({"type": "token", "content": stored.assistant_message})
                yield _sse({"type": "done", "assistant_message": stored.assistant_message,
                            "tools_used": stored.tools_used})
                return
            yield _sse({"type": "error", "code": "ai_message_duplicate",
                        "message": "duplicate message"})
            return

        try:
            async for event in self._stream_agentic_loop(conversation, user_message, _sse):
                yield event
        except AIToolError as exc:
            user_message.status = AIMessageStatus.FAILED
            user_message.error_code = exc.code
            await self.session.commit()
            yield _sse({"type": "error", "code": exc.code, "message": str(exc)})

    async def replay_completed_message(
        self, conversation_token: str, client_message_id: str
    ) -> tuple[str, AIConversationMessageRead] | None:
        conversation = await self._conversation(conversation_token)
        duplicate = await self._message_by_client_id(conversation.id, client_message_id)
        if duplicate is None:
            return None
        if duplicate.status in {
            AIMessageStatus.COMPLETED,
            AIMessageStatus.PENDING_CONFIRMATION,
        }:
            return duplicate.content, await self._stored_response_for_duplicate(
                conversation, duplicate
            )
        raise AIConversationConflict(
            "message with this client_message_id is not completed",
            code="ai_message_not_replayable",
        )

    async def confirm(
        self, conversation_token: str, confirmation_token: str, *, confirm: bool
    ) -> AIConfirmationRead:
        conversation = await self._conversation(conversation_token)
        pending = await self._pending_confirmation(conversation.id, confirmation_token)
        now = self.now()
        if pending.status == AIPendingConfirmationStatus.CONFIRMED:
            return AIConfirmationRead(
                assistant_message="This action was already confirmed.",
                status=pending.status,
                data=pending.confirmation_summary_json,
            )
        if pending.status != AIPendingConfirmationStatus.PENDING:
            return AIConfirmationRead(
                assistant_message="This confirmation is no longer pending.",
                status=pending.status,
                data=pending.confirmation_summary_json,
            )
        if _utc(pending.expires_at) <= now:
            pending.status = AIPendingConfirmationStatus.EXPIRED
            await self.session.commit()
            raise AIConversationConflict("confirmation expired", code="ai_confirmation_expired")
        if not confirm:
            pending.status = AIPendingConfirmationStatus.CANCELLED
            pending.cancelled_at = now
            await self._append_assistant_message(
                conversation.id,
                "Okay, I did not place the order.",
                AIMessageStatus.COMPLETED,
            )
            await self.session.commit()
            return AIConfirmationRead(
                assistant_message="Okay, I did not place the order.",
                status=pending.status,
                data=pending.confirmation_summary_json,
            )
        context = await self._tool_context(conversation)
        result = await self.executor.execute(
            self.session,
            pending.tool_name,
            pending.validated_arguments_json,
            context,
            ToolExecutionAuthorization(explicit_user_confirmation=True),
        )
        if not result.ok:
            raise AIConversationConflict(
                result.error.message if result.error else "confirmation failed",
                code=result.error.code if result.error else "ai_confirmation_failed",
            )
        pending.status = AIPendingConfirmationStatus.CONFIRMED
        pending.confirmed_at = now
        order = result.data if isinstance(result.data, dict) else {}
        round_number = order.get("round_number")
        assistant = (
            f"Your order was placed successfully as Round {round_number}."
            if round_number
            else "Your order was placed successfully."
        )
        await self._append_assistant_message(conversation.id, assistant, AIMessageStatus.COMPLETED)
        await self.session.commit()
        return AIConfirmationRead(assistant_message=assistant, status=pending.status, data=order)

    # ── Agentic ReAct loop (non-streaming) ─────────────────────────────────────

    async def _run_agentic_loop(
        self, conversation: AIConversation, user_message: AIConversationMessage
    ) -> AIConversationMessageRead:
        """Non-streaming agentic loop used by send_message().

        Executes up to max_tool_rounds of tool calls before synthesising a final reply.
        """
        context = await self._tool_context(conversation)
        response_mode = await self._response_mode(conversation.id, user_message)
        tool_schemas = self.registry.get_tool_schemas(AIActorType.CUSTOMER)
        tools_used: list[str] = []

        # Build the initial message list (system + recent history)
        provider_messages = await self._provider_messages(conversation.id, response_mode)
        # in-flight messages accumulate tool call/result pairs for the current request
        in_flight: list[AIMessage] = []

        for _round in range(self.max_tool_rounds):
            response: AIModelResponse = await self.provider.generate(
                messages=provider_messages + in_flight,
                tool_schemas=tool_schemas,
                tool_results=[],
            )

            if not response.tool_calls:
                # Model produced a text response — we're done
                text = (response.message.content if response.message else "") or (
                    "I could not produce a response right now."
                )
                return await self._complete_response(
                    conversation.id, user_message, text, tools_used
                )

            # Check for cart_submit — it interrupts the loop
            for tc in response.tool_calls:
                if tc.name == "cart_submit":
                    return await self._create_pending_submit(
                        conversation, user_message, tc.arguments, tools_used
                    )

            # Execute all other tool calls
            tool_call_tuples = [(tc.name, tc.arguments) for tc in response.tool_calls]
            results: list[AIToolResult] = await self.executor.execute_parallel(
                self.session, tool_call_tuples, context
            )
            for tc in response.tool_calls:
                tools_used.append(tc.name)

            # Append tool call + results to in-flight context for next round
            call_id = response.tool_calls[0].id if (response.tool_calls and response.tool_calls[0].id) else "call_1"
            in_flight.append(AIMessage(role="assistant", content=None, tool_calls=response.tool_calls))
            in_flight.append(AIMessage(role="tool", content=_format_tool_results(results), tool_call_id=call_id))

        # Safety guard: max rounds exhausted — ask the model for a final text answer
        fallback_response = await self.provider.generate(
            messages=provider_messages + in_flight + [
                AIMessage(
                    role="system",
                    content=(
                        "You have now gathered enough restaurant data. "
                        "Synthesise a final answer for the customer. "
                        "Do not call any more tools."
                    ),
                )
            ],
            tool_schemas=[],
            tool_results=[],
        )
        text = (fallback_response.message.content if fallback_response.message else "") or (
            "I could not produce a complete response right now. Please try again."
        )
        return await self._complete_response(conversation.id, user_message, text, tools_used)

    # ── Agentic ReAct loop (streaming) ─────────────────────────────────────────

    async def _stream_agentic_loop(
        self,
        conversation: AIConversation,
        user_message: AIConversationMessage,
        _sse,
    ):
        """Streaming agentic loop used by stream_message().

        Emits tool_start / tool_done SSE events immediately; streams the final
        LLM text reply token-by-token.
        """
        context = await self._tool_context(conversation)
        response_mode = await self._response_mode(conversation.id, user_message)
        tool_schemas = self.registry.get_tool_schemas(AIActorType.CUSTOMER)
        tools_used: list[str] = []

        provider_messages = await self._provider_messages(conversation.id, response_mode)
        in_flight: list[AIMessage] = []

        for _round in range(self.max_tool_rounds):
            response: AIModelResponse = await self.provider.generate(
                messages=provider_messages + in_flight,
                tool_schemas=tool_schemas,
                tool_results=[],
            )

            if not response.tool_calls:
                # Model produced text — stream it
                full_text = response.message.content if response.message else ""
                if not full_text:
                    # Try streaming fallback
                    full_text = ""
                    async for chunk in self.provider.stream_generate(
                        messages=provider_messages + in_flight,
                        tool_schemas=[],
                    ):
                        full_text += chunk
                        yield _sse({"type": "token", "content": chunk})
                else:
                    yield _sse({"type": "token", "content": full_text})

                final_text = full_text or "I could not produce a response right now."
                result = await self._complete_response(
                    conversation.id, user_message, final_text, tools_used
                )

                # Build navigation + discovery from the last tool call if available
                last_tool = tools_used[-1] if tools_used else None
                last_args = _last_args(in_flight)
                navigation: list[AINavigationRead] = []
                discovery: AIDiscoveryRead | None = None
                if last_tool:
                    navigation = await self._navigation_for_result(
                        context.outlet_id, last_tool, last_args, tool_ok=True
                    )
                    discovery = await self._category_discovery(
                        context.outlet_id, last_tool, last_args, tool_ok=True
                    )

                yield _sse({
                    "type": "done",
                    "assistant_message": result.assistant_message,
                    "tools_used": result.tools_used,
                    "confirmation_required": None,
                    "navigation": [n.model_dump() for n in navigation],
                    "discovery": discovery.model_dump() if discovery else None,
                })
                return

            # Check for cart_submit — interrupt loop, create pending confirmation
            for tc in response.tool_calls:
                if tc.name == "cart_submit":
                    yield _sse({"type": "tool_start", "tool": "cart_submit"})
                    submit_result = await self._create_pending_submit(
                        conversation, user_message, tc.arguments, tools_used
                    )
                    yield _sse({"type": "tool_done", "tool": "cart_submit", "ok": True})
                    conf = submit_result.confirmation_required
                    yield _sse({"type": "token", "content": submit_result.assistant_message})
                    yield _sse({
                        "type": "done",
                        "assistant_message": submit_result.assistant_message,
                        "tools_used": submit_result.tools_used,
                        "confirmation_required": conf.model_dump() if conf else None,
                        "navigation": [n.model_dump() for n in submit_result.navigation],
                        "discovery": submit_result.discovery.model_dump() if submit_result.discovery else None,
                    })
                    return

            # Execute all tools; emit SSE events
            for tc in response.tool_calls:
                yield _sse({"type": "tool_start", "tool": tc.name})

            tool_call_tuples = [(tc.name, tc.arguments) for tc in response.tool_calls]
            results: list[AIToolResult] = await self.executor.execute_parallel(
                self.session, tool_call_tuples, context
            )
            for tc, tool_result in zip(response.tool_calls, results):
                tools_used.append(tc.name)
                yield _sse({"type": "tool_done", "tool": tc.name, "ok": tool_result.ok})

            # Accumulate in-flight context for next round
            call_id = response.tool_calls[0].id if (response.tool_calls and response.tool_calls[0].id) else "call_1"
            in_flight.append(AIMessage(role="assistant", content=None, tool_calls=response.tool_calls))
            in_flight.append(AIMessage(role="tool", content=_format_tool_results(results), tool_call_id=call_id))

        # Safety guard: max rounds exhausted — stream a final synthesis
        full_text = ""
        async for chunk in self.provider.stream_generate(
            messages=provider_messages + in_flight + [
                AIMessage(
                    role="system",
                    content=(
                        "You have now gathered enough restaurant data. "
                        "Synthesise a final answer for the customer. "
                        "Do not call any more tools."
                    ),
                )
            ],
            tool_schemas=[],
        ):
            full_text += chunk
            yield _sse({"type": "token", "content": chunk})

        final_text = full_text or "I could not produce a complete response right now."
        result = await self._complete_response(
            conversation.id, user_message, final_text, tools_used
        )
        yield _sse({
            "type": "done",
            "assistant_message": result.assistant_message,
            "tools_used": result.tools_used,
            "confirmation_required": None,
            "navigation": [],
            "discovery": None,
        })

    # ── DB persistence helpers ──────────────────────────────────────────────────

    async def _complete_response(
        self,
        conversation_id: object,
        user_message: AIConversationMessage,
        text: str,
        tools_used: list[str],
        navigation: list[AINavigationRead] | None = None,
        discovery: AIDiscoveryRead | None = None,
    ) -> AIConversationMessageRead:
        user_message.status = AIMessageStatus.COMPLETED
        await self._append_assistant_message(conversation_id, text, AIMessageStatus.COMPLETED)
        await self.session.commit()
        return AIConversationMessageRead(
            assistant_message=text,
            tools_used=tools_used,
            navigation=navigation or [],
            discovery=discovery,
        )

    async def _create_pending_submit(
        self,
        conversation: AIConversation,
        user_message: AIConversationMessage,
        arguments: dict[str, Any],
        tools_used: list[str],
    ) -> AIConversationMessageRead:
        context = await self._tool_context(conversation)
        cart = await CartService(self.session).get_cart(context.dining_session_token or "")
        if cart.item_count == 0:
            raise AIConversationConflict("cart is empty", code="cart_empty")
        if not cart.can_submit:
            raise AIConversationConflict(
                "cart cannot be submitted", code="cart_contains_unavailable_items"
            )
        safe_arguments = dict(arguments)
        safe_arguments["quote_token"] = cart.quote_token
        safe_arguments["idempotency_key"] = f"ai-{secrets.token_urlsafe(18)}"
        validated = self.registry.get("cart_submit").input_model.model_validate(safe_arguments)
        expires_at = self.now() + timedelta(minutes=self.confirmation_ttl_minutes)
        pending = AIPendingToolConfirmation(
            public_confirmation_token=await self._unique_confirmation_token(),
            conversation_id=conversation.id,
            source_message_id=user_message.id,
            tool_name="cart_submit",
            validated_arguments_json=validated.model_dump(mode="json"),
            confirmation_summary_json={
                "action": "place_order",
                "currency_code": cart.currency_code,
                "subtotal_after_discount": str(cart.subtotal_after_discount),
                "item_count": cart.item_count,
            },
            expires_at=expires_at,
        )
        self.session.add(pending)
        user_message.status = AIMessageStatus.PENDING_CONFIRMATION
        assistant = "Your cart is ready to place. Please confirm."
        await self._append_assistant_message(
            conversation.id, assistant, AIMessageStatus.PENDING_CONFIRMATION
        )
        await self.session.commit()
        return AIConversationMessageRead(
            assistant_message=assistant,
            confirmation_required=AIConfirmationRequiredRead(
                confirmation_token=pending.public_confirmation_token,
                action="place_order",
                currency_code=cart.currency_code,
                subtotal_after_discount=str(cart.subtotal_after_discount),
                item_count=cart.item_count,
                expires_at=expires_at,
            ),
            tools_used=tools_used,
        )

    # ── Navigation & discovery hints for frontend ───────────────────────────────

    async def _category_discovery(
        self,
        outlet_id: UUID,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        tool_ok: bool,
    ) -> AIDiscoveryRead | None:
        if not tool_ok or tool_name not in {"menu_get", "menu_search"}:
            return None
        filters = arguments.get("filters")
        menu = await CustomerMenuService(self.session).get_menu(outlet_id)
        categories = [
            {
                "id": category.id,
                "name": category.name,
                "display_order": category.display_order,
            }
            for category in menu.categories
        ]
        category_id: UUID | None = None
        if isinstance(filters, dict) and isinstance(filters.get("category_id"), str):
            try:
                category_id = UUID(filters["category_id"])
            except ValueError:
                category_id = None
        category = next((item for item in menu.categories if item.id == category_id), None)
        if category is None:
            return AIDiscoveryRead(categories=categories)
        return AIDiscoveryRead(
            categories=categories,
            category=AICategoryBrowseRead(
                id=category.id,
                name=category.name,
                description=category.description,
                display_order=category.display_order,
                dishes=[
                    AICategoryBrowseDishRead(dish=dish, addable=dish.available)
                    for dish in category.dishes
                ],
            ),
        )

    async def _navigation_for_result(
        self,
        outlet_id: UUID,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        tool_ok: bool,
    ) -> list[AINavigationRead]:
        if not tool_ok:
            return []
        if tool_name in {"menu_get", "menu_search"}:
            filters = arguments.get("filters")
            if isinstance(filters, dict) and isinstance(filters.get("category_id"), str):
                try:
                    return [
                        AINavigationRead(action=AINavigationAction.BROWSE_CATEGORIES),
                        AINavigationRead(
                            action=AINavigationAction.BROWSE_CATEGORY,
                            category_id=UUID(filters["category_id"]),
                        ),
                    ]
                except ValueError:
                    pass
            return [AINavigationRead(action=AINavigationAction.BROWSE_CATEGORIES)]
        if tool_name != "cart_add_item":
            return []
        dish_id = arguments.get("dish_id")
        if not isinstance(dish_id, str):
            return [
                AINavigationRead(action=AINavigationAction.BROWSE_CATEGORIES),
                AINavigationRead(action=AINavigationAction.VIEW_CART),
            ]
        try:
            parsed_dish_id = UUID(dish_id)
        except ValueError:
            return [
                AINavigationRead(action=AINavigationAction.BROWSE_CATEGORIES),
                AINavigationRead(action=AINavigationAction.VIEW_CART),
            ]
        menu = await CustomerMenuService(self.session).get_menu(outlet_id)
        category_id = next(
            (
                dish.category_id
                for category in menu.categories
                for dish in category.dishes
                if dish.id == parsed_dish_id
            ),
            None,
        )
        navigation = [
            AINavigationRead(action=AINavigationAction.BROWSE_CATEGORIES),
            AINavigationRead(action=AINavigationAction.VIEW_CART),
        ]
        if category_id is not None:
            navigation.insert(
                1,
                AINavigationRead(
                    action=AINavigationAction.ADD_MORE_CURRENT_CATEGORY,
                    category_id=category_id,
                ),
            )
        return navigation

    # ── Session / DB helpers ───────────────────────────────────────────────────

    async def _session_context(
        self, session_token: str
    ) -> tuple[DiningSession, RestaurantOutlet, Restaurant]:
        result = await self.session.execute(
            select(DiningSession, RestaurantOutlet, Restaurant)
            .join(RestaurantTable, RestaurantTable.id == DiningSession.table_id)
            .join(RestaurantOutlet, RestaurantOutlet.id == RestaurantTable.outlet_id)
            .join(Restaurant, Restaurant.id == RestaurantOutlet.restaurant_id)
            .where(DiningSession.public_session_token == session_token)
        )
        row = result.one_or_none()
        if row is None:
            raise AIConversationNotFound(
                "dining session not found", code="dining_session_not_found"
            )
        dining_session, outlet, restaurant = row
        if dining_session.status != DiningSessionStatus.OPEN:
            raise AIConversationConflict("dining session is closed", code="ai_session_closed")
        return dining_session, outlet, restaurant

    async def _conversation(self, token: str) -> AIConversation:
        conversation = (
            await self.session.execute(
                select(AIConversation)
                .options(selectinload(AIConversation.messages))
                .where(AIConversation.public_token == token)
            )
        ).scalar_one_or_none()
        if conversation is None:
            raise AIConversationNotFound("AI conversation not found")
        return conversation

    async def _tool_context(self, conversation: AIConversation) -> AIToolContext:
        session_token = await self.session.scalar(
            select(DiningSession.public_session_token).where(
                DiningSession.id == conversation.dining_session_id
            )
        )
        if session_token is None:
            raise AIConversationNotFound("dining session not found")
        return AIToolContext(
            actor_type=AIActorType.CUSTOMER,
            outlet_id=conversation.outlet_id,
            dining_session_token=session_token,
        )

    async def _messages(self, conversation_id: object) -> list[AIConversationMessage]:
        result = await self.session.execute(
            select(AIConversationMessage)
            .where(AIConversationMessage.conversation_id == conversation_id)
            .order_by(AIConversationMessage.sequence_number)
        )
        return list(result.scalars())

    async def _provider_messages(
        self, conversation_id: object, response_mode: CustomerResponseLanguageMode
    ) -> list[AIMessage]:
        all_messages = [
            message
            for message in await self._messages(conversation_id)
            if message.role in {AIMessageRole.USER, AIMessageRole.ASSISTANT}
        ]
        bounded = all_messages[-self.context_turns :]
        system_prompt = f"{CUSTOMER_SYSTEM_PROMPT}\n{response_mode_instruction(response_mode)}"
        return [AIMessage(role="system", content=system_prompt)] + [
            AIMessage(role=message.role.value, content=message.content) for message in bounded
        ]

    async def _response_mode(
        self, conversation_id: object, user_message: AIConversationMessage
    ) -> CustomerResponseLanguageMode:
        prior_user_messages = [
            message.content
            for message in await self._messages(conversation_id)
            if message.role == AIMessageRole.USER and message.id != user_message.id
        ]
        return resolve_customer_response_mode(
            user_message.content, prior_user_messages=prior_user_messages
        )

    async def _next_sequence(self, conversation_id: object) -> int:
        current = await self.session.scalar(
            select(func.max(AIConversationMessage.sequence_number)).where(
                AIConversationMessage.conversation_id == conversation_id
            )
        )
        return int(current or 0) + 1

    async def _message_by_client_id(
        self, conversation_id: object, client_message_id: str
    ) -> AIConversationMessage | None:
        return (
            await self.session.execute(
                select(AIConversationMessage).where(
                    AIConversationMessage.conversation_id == conversation_id,
                    AIConversationMessage.client_message_id == client_message_id,
                )
            )
        ).scalar_one_or_none()

    async def _stored_response_for_duplicate(
        self, conversation: AIConversation, message: AIConversationMessage
    ) -> AIConversationMessageRead:
        result = await self.session.execute(
            select(AIConversationMessage)
            .where(
                AIConversationMessage.conversation_id == conversation.id,
                AIConversationMessage.role == AIMessageRole.ASSISTANT,
                AIConversationMessage.sequence_number > message.sequence_number,
            )
            .order_by(AIConversationMessage.sequence_number)
        )
        assistant = result.scalars().first()
        pending = (
            await self.session.execute(
                select(AIPendingToolConfirmation).where(
                    AIPendingToolConfirmation.source_message_id == message.id,
                    AIPendingToolConfirmation.status == AIPendingConfirmationStatus.PENDING,
                )
            )
        ).scalar_one_or_none()
        confirmation = None
        if pending is not None:
            summary = pending.confirmation_summary_json
            confirmation = AIConfirmationRequiredRead(
                confirmation_token=pending.public_confirmation_token,
                action=str(summary["action"]),
                currency_code=str(summary["currency_code"]),
                subtotal_after_discount=str(summary["subtotal_after_discount"]),
                item_count=int(summary["item_count"]),
                expires_at=_utc(pending.expires_at),
            )
        return AIConversationMessageRead(
            assistant_message=assistant.content if assistant else "",
            confirmation_required=confirmation,
            tools_used=[],
        )

    async def _append_assistant_message(
        self, conversation_id: object, content: str, status: AIMessageStatus
    ) -> AIConversationMessage:
        message = AIConversationMessage(
            conversation_id=conversation_id,
            client_message_id=None,
            sequence_number=await self._next_sequence(conversation_id),
            role=AIMessageRole.ASSISTANT,
            status=status,
            content=content,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def _pending_confirmation(
        self, conversation_id: object, confirmation_token: str
    ) -> AIPendingToolConfirmation:
        pending = (
            await self.session.execute(
                select(AIPendingToolConfirmation).where(
                    AIPendingToolConfirmation.conversation_id == conversation_id,
                    AIPendingToolConfirmation.public_confirmation_token == confirmation_token,
                )
            )
        ).scalar_one_or_none()
        if pending is None:
            raise AIConversationNotFound(
                "pending confirmation not found", code="ai_confirmation_not_found"
            )
        return pending

    async def _unique_conversation_token(self) -> str:
        for _ in range(10):
            token = secrets.token_urlsafe(32)
            exists = await self.session.scalar(
                select(AIConversation.id).where(AIConversation.public_token == token)
            )
            if exists is None:
                return token
        raise AIConversationConflict(
            "could not generate conversation token", code="ai_token_failed"
        )

    async def _unique_confirmation_token(self) -> str:
        for _ in range(10):
            token = secrets.token_urlsafe(32)
            exists = await self.session.scalar(
                select(AIPendingToolConfirmation.id).where(
                    AIPendingToolConfirmation.public_confirmation_token == token
                )
            )
            if exists is None:
                return token
        raise AIConversationConflict(
            "could not generate confirmation token", code="ai_token_failed"
        )


# ── Module-level helpers ────────────────────────────────────────────────────────

def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _format_tool_calls(tool_calls: list[AIToolCall]) -> str:
    """Serialise a list of tool calls as a compact JSON-like assistant message."""
    import json
    return json.dumps(
        [{"name": tc.name, "arguments": tc.arguments} for tc in tool_calls],
        ensure_ascii=False,
    )


def _format_tool_results(results: list[AIToolResult]) -> str:
    """Serialise tool results as a compact JSON-like tool message."""
    import json
    return json.dumps(
        [{"tool": r.tool, "ok": r.ok, "data": r.data, "error": r.error.model_dump() if r.error else None} for r in results],
        ensure_ascii=False,
        default=str,
    )


def _last_args(in_flight: list[AIMessage]) -> dict[str, Any]:
    """Extract arguments from the last tool-call message in the in-flight list."""
    import json
    for msg in reversed(in_flight):
        if msg.role == "assistant":
            if msg.tool_calls:
                return msg.tool_calls[-1].arguments or {}
            try:
                if msg.content:
                    calls = json.loads(msg.content)
                    if isinstance(calls, list) and calls:
                        return calls[-1].get("arguments") or {}
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass
    return {}


def _normalize_choice_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _build_provider() -> ToolCallingModelProvider:
    """Build the active provider chain from application settings.

    Provider resolution logic:

    ``ai_primary_provider = "auto"`` (default)
        * Primary:  ``LlamaCppToolCallingProvider`` — honours the current
          ``LOCAL_LLM_BASE_URL`` / ``LOCAL_LLM_MODEL`` / ``LOCAL_LLM_API_KEY``
          settings, which already point at the Gemini OpenAI-compat endpoint
          when ``LOCAL_LLM_RUNTIME_MODE=remote``.
        * Fallback: ``CloudflareToolCallingProvider`` — added automatically when
          ``CLOUDFLARE_ACCOUNT_ID`` **and** ``CLOUDFLARE_API_TOKEN`` are set.

    ``ai_primary_provider = "cloudflare"``
        * Primary:  ``CloudflareToolCallingProvider``
        * Fallback: ``LlamaCppToolCallingProvider``

    If only one provider is available, it is returned directly (no wrapper).
    """
    settings = get_settings()
    llama = LlamaCppToolCallingProvider()

    if settings.ai_primary_provider == "cloudflare":
        if not settings.cloudflare_enabled:
            # Misconfiguration — fall back to llama without crashing at import time.
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "AI_PRIMARY_PROVIDER=cloudflare but Cloudflare credentials are not set; "
                "falling back to local/remote LLM provider."
            )
            return llama
        cf: ToolCallingModelProvider = CloudflareToolCallingProvider()
        return FallbackToolCallingProvider(cf, llama)

    # "auto" — primary is the configured llama/remote endpoint; CF is optional fallback.
    if settings.cloudflare_enabled:
        cf = CloudflareToolCallingProvider()
        return FallbackToolCallingProvider(llama, cf)

    return llama
