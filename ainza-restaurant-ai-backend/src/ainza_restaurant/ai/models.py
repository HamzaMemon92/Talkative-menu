from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AIToolSafetyLevel(StrEnum):
    READ_ONLY = "read_only"
    REVERSIBLE_MUTATION = "reversible_mutation"
    CONSEQUENTIAL_MUTATION = "consequential_mutation"


class AIToolErrorRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class AIToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    tool: str
    data: Any | None = None
    error: AIToolErrorRead | None = None
    generated_at: datetime
    source: str = "backend"


class AIMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    content: str | None = None
    tool_calls: list[AIToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None


class AIToolCall(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    extra_content: dict[str, Any] | None = None


class AIModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: AIMessage | None = None
    tool_calls: list[AIToolCall] = Field(default_factory=list)
    raw_finish_reason: str | None = None
