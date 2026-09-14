from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.ai.context import AIActorType, AIToolContext
from ainza_restaurant.ai.models import AIToolSafetyLevel

ToolHandler = Callable[[AsyncSession, AIToolContext, BaseModel], Awaitable[Any]]


@dataclass(frozen=True)
class AIToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    allowed_actor_types: frozenset[AIActorType]
    safety_level: AIToolSafetyLevel
    requires_confirmation: bool
    handler: ToolHandler

    def schema(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
            "allowed_actor_types": sorted(actor.value for actor in self.allowed_actor_types),
            "safety_level": self.safety_level.value,
            "requires_confirmation": self.requires_confirmation,
        }
