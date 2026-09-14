from __future__ import annotations

from ainza_restaurant.ai.context import AIActorType
from ainza_restaurant.ai.errors import AIToolNotFound
from ainza_restaurant.ai.tools.definitions import AIToolDefinition


class AIToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AIToolDefinition] = {}

    def register(self, definition: AIToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"duplicate AI tool name: {definition.name}")
        self._tools[definition.name] = definition

    def get(self, name: str) -> AIToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise AIToolNotFound(name) from exc

    def list_tools_for_actor(self, actor_type: AIActorType) -> list[AIToolDefinition]:
        return [tool for tool in self._tools.values() if actor_type in tool.allowed_actor_types]

    def get_tool_schemas(self, actor_type: AIActorType) -> list[dict[str, object]]:
        return [tool.schema() for tool in self.list_tools_for_actor(actor_type)]


def build_default_registry() -> AIToolRegistry:
    from ainza_restaurant.ai.tools.customer import CUSTOMER_TOOLS
    from ainza_restaurant.ai.tools.owner import OWNER_TOOLS
    from ainza_restaurant.ai.tools.owner_analytics import OWNER_ANALYTICS_TOOLS

    registry = AIToolRegistry()
    for tool in [*CUSTOMER_TOOLS, *OWNER_TOOLS, *OWNER_ANALYTICS_TOOLS]:
        registry.register(tool)
    return registry
