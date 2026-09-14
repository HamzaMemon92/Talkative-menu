from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AIActorType(StrEnum):
    CUSTOMER = "customer"
    OWNER = "owner"
    STAFF = "staff"


class AIToolContext(BaseModel):
    """Server-injected scope for AI tool execution."""

    model_config = ConfigDict(extra="forbid")

    actor_type: AIActorType
    outlet_id: UUID
    dining_session_token: str | None = None
    restaurant_id: UUID | None = None
    request_id: str | None = Field(default=None, max_length=120)


class ToolExecutionAuthorization(BaseModel):
    """Authorization supplied by the non-model orchestrator."""

    model_config = ConfigDict(extra="forbid")

    explicit_user_confirmation: bool = False
