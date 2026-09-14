from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ainza_restaurant.ai.context import AIActorType
from ainza_restaurant.ai.models import AIMessage
from ainza_restaurant.ai.providers.base import ToolCallingModelProvider
from ainza_restaurant.ai.providers.llama_cpp import LlamaCppToolCallingProvider
from ainza_restaurant.ai.tools.registry import AIToolRegistry

MAX_ROUTED_TOOLS = 3


class CustomerRouteKind(StrEnum):
    NO_TOOL_CONVERSATION = "no_tool_conversation"
    GROUNDED_TOOL_REQUIRED = "grounded_tool_required"


CUSTOMER_TOOL_CAPABILITIES: dict[str, str] = {
    "menu_get": "read full customer menu",
    "menu_search": "search menu by dish, diet, spice, cuisine, or availability",
    "meal_recommend": "build a budget-bounded meal suggestion from current menu data",
    "menu_get_dish": "inspect one known dish in detail",
    "dish_get_availability": "check one dish availability",
    "offers_get_effective": "read current offers",
    "cart_get": "read cart",
    "cart_add_item": "add requested item to cart",
    "cart_add_items": (
        "atomically add multiple requested items to cart with required or conditional semantics"
    ),
    "cart_update_item": "update cart item quantity or options",
    "cart_remove_item": "remove cart item",
    "cart_select_offer": "select or clear offer",
    "cart_submit": "submit cart or place order after confirmation",
    "orders_get_session": "read submitted session orders",
    "bill_get_preview": "read bill preview",
    "customer_total_summary": "read the current cart and submitted-order money state",
    "menu_quote_selection": "price a proposed selection without changing cart",
}


class ToolRouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    needs_tools: bool
    tools: list[str] = Field(default_factory=list)
    route_kind: CustomerRouteKind | None = None


@dataclass(frozen=True)
class ToolRoute:
    needs_tools: bool
    tools: list[str]
    fallback_used: bool = False
    route_kind: CustomerRouteKind | None = None

    @property
    def requires_authoritative_evidence(self) -> bool:
        return self.route_kind == CustomerRouteKind.GROUNDED_TOOL_REQUIRED


class CustomerToolCandidateRouter:
    def __init__(
        self,
        registry: AIToolRegistry,
        *,
        provider: ToolCallingModelProvider | None = None,
        max_tools: int = MAX_ROUTED_TOOLS,
    ) -> None:
        self.registry = registry
        self.provider = provider or LlamaCppToolCallingProvider(
            max_tokens=96,
            temperature=0,
            top_p=1,
            top_k=1,
        )
        self.max_tools = max_tools

    async def route(self, messages: list[AIMessage]) -> ToolRoute:
        allowed = self._allowed_names()
        response = await self.provider.generate(
            messages=[AIMessage(role="system", content=self._router_prompt(allowed)), *messages],
            tool_schemas=[],
            tool_results=[],
        )
        content = response.message.content if response.message else ""
        decision = self._parse_decision(content)
        if decision is None:
            return ToolRoute(
                needs_tools=True,
                tools=self._fallback_tools(allowed),
                fallback_used=True,
                route_kind=CustomerRouteKind.GROUNDED_TOOL_REQUIRED,
            )
        route_kind = decision.route_kind or (
            CustomerRouteKind.GROUNDED_TOOL_REQUIRED
            if decision.needs_tools
            else CustomerRouteKind.NO_TOOL_CONVERSATION
        )
        if not decision.needs_tools:
            if route_kind == CustomerRouteKind.GROUNDED_TOOL_REQUIRED:
                return ToolRoute(
                    needs_tools=True,
                    tools=self._fallback_tools(allowed),
                    fallback_used=True,
                    route_kind=route_kind,
                )
            return ToolRoute(needs_tools=False, tools=[], route_kind=route_kind)
        validated = [name for name in decision.tools if name in allowed]
        if not validated:
            return ToolRoute(
                needs_tools=True,
                tools=self._fallback_tools(allowed),
                fallback_used=True,
                route_kind=CustomerRouteKind.GROUNDED_TOOL_REQUIRED,
            )
        return ToolRoute(
            needs_tools=True,
            tools=validated[: self.max_tools],
            route_kind=CustomerRouteKind.GROUNDED_TOOL_REQUIRED,
        )

    def _allowed_names(self) -> set[str]:
        return {
            tool.name
            for tool in self.registry.list_tools_for_actor(AIActorType.CUSTOMER)
            if tool.name in CUSTOMER_TOOL_CAPABILITIES
        }

    def _router_prompt(self, allowed: set[str]) -> str:
        catalog = "\n".join(
            f"- {name}: {CUSTOMER_TOOL_CAPABILITIES[name]}" for name in sorted(allowed)
        )
        return f"""/no_think
You route restaurant customer messages to existing backend capabilities.
Understand English, Hindi, Hinglish, Gujarati, Gujlish, typos, and code-switching.
Use recent context only to resolve references like "that one", "make it two", or "remove it".
Return ONLY compact JSON with this exact shape:
{{"needs_tools": true, "tools": ["menu_get"], "route_kind": "grounded_tool_required"}}
or
{{"needs_tools": false, "tools": [], "route_kind": "no_tool_conversation"}}
Choose 1-3 tools. If uncertain but restaurant facts/actions may be needed, choose the
smallest safe set.
Do not invent tools. Do not answer the customer.

Allowed tools:
{catalog}
"""

    def _parse_decision(self, content: str) -> ToolRouteDecision | None:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
            return ToolRouteDecision.model_validate(payload)
        except (json.JSONDecodeError, ValidationError):
            return None

    def _fallback_tools(self, allowed: set[str]) -> list[str]:
        # A malformed model route cannot safely narrow the customer capability set.
        return sorted(allowed)
