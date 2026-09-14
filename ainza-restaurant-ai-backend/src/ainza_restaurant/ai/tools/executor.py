from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.ai.context import AIToolContext, ToolExecutionAuthorization
from ainza_restaurant.ai.errors import (
    AIToolConfirmationRequired,
    AIToolError,
    AIToolForbidden,
)
from ainza_restaurant.ai.models import AIToolErrorRead, AIToolResult, AIToolSafetyLevel
from ainza_restaurant.ai.tools.registry import AIToolRegistry

logger = logging.getLogger(__name__)


class AIToolExecutor:
    def __init__(
        self,
        registry: AIToolRegistry,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.registry = registry
        self._now = now or (lambda: datetime.now(UTC))

    def now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _is_read_only(self, tool_name: str) -> bool:
        """Return True if the named tool is READ_ONLY (safe to run concurrently)."""
        try:
            definition = self.registry.get(tool_name)
            return definition.safety_level == AIToolSafetyLevel.READ_ONLY
        except Exception:
            return False

    async def execute(
        self,
        session: AsyncSession,
        tool_name: str,
        raw_arguments: dict[str, Any],
        context: AIToolContext,
        authorization: ToolExecutionAuthorization | None = None,
    ) -> AIToolResult:
        authorization = authorization or ToolExecutionAuthorization()
        try:
            definition = self.registry.get(tool_name)
            if context.actor_type not in definition.allowed_actor_types:
                raise AIToolForbidden(tool_name)
            if definition.requires_confirmation and not authorization.explicit_user_confirmation:
                raise AIToolConfirmationRequired(tool_name)
            payload = definition.input_model.model_validate(raw_arguments)
            data = await definition.handler(session, context, payload)
            return AIToolResult(
                ok=True,
                tool=tool_name,
                data=_json_data(data),
                generated_at=self.now(),
            )
        except ValidationError as exc:
            return self._failure(
                tool_name,
                "ai_tool_validation_error",
                "AI tool arguments are invalid",
                details={"errors": exc.errors(include_url=False, include_input=False)},
            )
        except AIToolError as exc:
            return self._failure(tool_name, exc.code, str(exc), details=exc.details)
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", None)
            if isinstance(code, str):
                return self._failure(tool_name, code, str(exc), details=_safe_details(exc))
            logger.exception("AI tool execution failed", extra={"tool": tool_name})
            return self._failure(
                tool_name,
                "ai_tool_internal_error",
                "AI tool execution failed",
            )

    async def execute_parallel(
        self,
        session: AsyncSession,
        tool_calls: list[tuple[str, dict[str, Any]]],
        context: AIToolContext,
        authorization: ToolExecutionAuthorization | None = None,
    ) -> list[AIToolResult]:
        """Execute multiple tool calls with safe parallelism.

        **READ_ONLY** tools run concurrently via ``asyncio.gather`` — they can never
        corrupt shared state.

        **REVERSIBLE_MUTATION** and **CONSEQUENTIAL_MUTATION** tools run sequentially
        in the order they were declared by the LLM, preventing race conditions on the
        shared database session.

        Args:
            session: The active async SQLAlchemy session.
            tool_calls: List of ``(tool_name, raw_arguments)`` pairs.
            context: AI actor context for scope checks.
            authorization: Optional confirmation state.

        Returns:
            Results in the same order as ``tool_calls``.
        """
        if not tool_calls:
            return []

        reads: list[tuple[int, str, dict[str, Any]]] = []
        mutations: list[tuple[int, str, dict[str, Any]]] = []

        for idx, (name, args) in enumerate(tool_calls):
            if self._is_read_only(name):
                reads.append((idx, name, args))
            else:
                mutations.append((idx, name, args))

        results: list[AIToolResult | None] = [None] * len(tool_calls)

        # Run all reads in parallel
        if reads:
            read_results = await asyncio.gather(
                *[
                    self.execute(session, name, args, context, authorization)
                    for _, name, args in reads
                ],
                return_exceptions=False,
            )
            for (idx, _, _), result in zip(reads, read_results, strict=True):
                results[idx] = result


        # Run mutations sequentially
        for idx, name, args in mutations:
            results[idx] = await self.execute(session, name, args, context, authorization)

        return [r for r in results if r is not None]

    def _failure(
        self,
        tool_name: str,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> AIToolResult:
        return AIToolResult(
            ok=False,
            tool=tool_name,
            data=None,
            error=AIToolErrorRead(code=code, message=message, details=details or {}),
            generated_at=self.now(),
        )


def _json_data(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_json_data(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_data(item) for key, item in value.items()}
    return value


def _safe_details(exc: Exception) -> dict[str, Any]:
    details = getattr(exc, "details", None)
    return details if isinstance(details, dict) else {}
