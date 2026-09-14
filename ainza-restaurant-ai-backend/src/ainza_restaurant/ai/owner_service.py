from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ainza_restaurant.ai.context import AIActorType, AIToolContext
from ainza_restaurant.ai.errors import AIToolError
from ainza_restaurant.ai.models import (
    AIMessage,
    AIMessageRole,
)
from ainza_restaurant.ai.providers.base import ToolCallingModelProvider
from ainza_restaurant.ai.service import (
    AIConversationConflict,
    AIConversationNotFound,
    _build_provider,
    _utc,
)
from ainza_restaurant.ai.tools.executor import AIToolExecutor
from ainza_restaurant.ai.tools.registry import AIToolRegistry, build_default_registry
from ainza_restaurant.restaurants.models import RestaurantOutlet

logger = logging.getLogger(__name__)


class OwnerAIConversationService:
    """Service for owner-facing business intelligence conversations.
    
    Unlike the customer service, this does not use the hierarchical intent planner.
    It uses a raw multi-step autonomous tool-calling loop (ReAct) with parallel execution,
    suitable for complex data analysis tasks.
    """

    def __init__(
        self,
        session: AsyncSession,
        outlet: RestaurantOutlet,
        *,
        provider: ToolCallingModelProvider | None = None,
        registry: AIToolRegistry | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.outlet = outlet
        self.registry = registry or build_default_registry()
        self.provider = provider or _build_provider()
        self.executor = AIToolExecutor(self.registry, now=now)
        self._now = now or (lambda: datetime.now(UTC))
        self.max_tool_rounds = 5

    def now(self) -> datetime:
        return _utc(self._now())

    async def _system_prompt(self) -> str:
        return (
            "You are an expert Restaurant Business Analyst AI for the restaurant owner.\n"
            f"The current outlet is {self.outlet.name}.\n"
            "You have access to read-only SQL aggregation tools.\n"
            "When asked about business performance, ALWAYS call the relevant analytics tools.\n"
            "You can call multiple tools in parallel (e.g. dish performance and category mix).\n"
            "Never invent or hallucinate data. If the tools return no data, say so.\n"
            "Format your answers with clear markdown, tables, and concise insights."
        )

    async def _tool_context(self) -> AIToolContext:
        return AIToolContext(
            actor_type=AIActorType.OWNER,
            outlet_id=self.outlet.id,
            restaurant_id=self.outlet.restaurant_id,
            dining_session_id=None,
        )

    async def _stream_tool_loop(self, messages: list[AIMessage], _sse: Callable[[dict[str, Any]], str]):
        context = await self._tool_context()
        tool_schemas = self.registry.get_tool_schemas(AIActorType.OWNER)
        
        current_messages = list(messages)
        tools_used = []
        
        for _round in range(self.max_tool_rounds):
            response = await self.provider.generate(
                messages=current_messages,
                tool_schemas=tool_schemas,
                tool_results=[],
            )
            
            if response.message and response.message.content:
                current_messages.append(response.message)
                
            if not response.tool_calls:
                break
                
            tools_used.extend(tc.name for tc in response.tool_calls)
            
            # Broadcast tool starts
            for tc in response.tool_calls:
                yield _sse({"type": "tool_start", "tool": tc.name})
                
            # Execute in parallel
            tool_call_tuples = [(tc.name, tc.arguments) for tc in response.tool_calls]
            results = await self.executor.execute_parallel(
                self.session, tool_call_tuples, context
            )
            
            tool_results = []
            for tc, res in zip(response.tool_calls, results):
                yield _sse({"type": "tool_done", "tool": tc.name, "ok": res.ok})
                tool_results.append({
                    "name": tc.name,
                    "content": res.data if res.ok else {"error": res.error.message if res.error else "failed"}
                })
                
            current_messages.append(AIMessage(
                role=AIMessageRole.TOOL,
                content="",
                tool_results=tool_results,
            ))
            
        # Final synthesis streaming
        full_text = ""
        async for chunk in self.provider.stream_generate(
            messages=current_messages,
            tool_schemas=[],
        ):
            full_text += chunk
            yield _sse({"type": "token", "content": chunk})
            
        final_text = full_text or "I could not produce an analysis right now."
        yield _sse({
            "type": "done",
            "assistant_message": final_text,
            "tools_used": tools_used,
            "confirmation_required": None,
            "navigation": [],
            "discovery": None,
        })

    async def stream_message(self, message: str, message_history: list[AIMessage] | None = None):
        import json as _json

        def _sse(payload: dict) -> str:
            return f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"
            
        messages = [AIMessage(role=AIMessageRole.SYSTEM, content=await self._system_prompt())]
        if message_history:
            messages.extend(message_history)
        messages.append(AIMessage(role=AIMessageRole.USER, content=message))
        
        try:
            async for event in self._stream_tool_loop(messages, _sse):
                yield event
        except Exception as exc:
            logger.exception("Owner AI error")
            yield _sse({"type": "error", "code": "internal_error", "message": str(exc)})
