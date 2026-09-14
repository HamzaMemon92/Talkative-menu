from __future__ import annotations

import logging
from typing import Protocol

from ainza_restaurant.ai.models import AIMessage, AIModelResponse

logger = logging.getLogger(__name__)

# Error codes that indicate a transient / capacity issue and should trigger
# failover to the next provider in the chain.
_TRANSIENT_CODES = frozenset(
    {
        "ai_model_timeout",
        "ai_model_unavailable",
        "ai_quota_exceeded",
        "ai_all_providers_failed",
    }
)


class ToolCallingModelProvider(Protocol):
    """Minimal provider-neutral future LLM interface."""

    async def generate(
        self,
        *,
        messages: list[AIMessage],
        tool_schemas: list[dict[str, object]],
        tool_results: list[dict[str, object]] | None = None,
    ) -> AIModelResponse:
        """Generate a response or provider-neutral tool calls."""


class FallbackToolCallingProvider:
    """Tries providers in order, falling back on transient errors.

    Usage::

        provider = FallbackToolCallingProvider(
            GeminiProvider(),          # primary
            CloudflareProvider(),      # first fallback
            LlamaCppProvider(),        # last-resort local fallback
        )

    Any provider may be a ``ToolCallingModelProvider`` or another
    ``FallbackToolCallingProvider`` for nested fallback chains.

    Only codes in ``_TRANSIENT_CODES`` trigger failover.  Auth failures,
    bad-request errors, and parse errors propagate immediately so they are
    not silently swallowed.
    """

    def __init__(self, primary: ToolCallingModelProvider, *fallbacks: ToolCallingModelProvider) -> None:
        self._chain: tuple[ToolCallingModelProvider, ...] = (primary, *fallbacks)

    async def generate(
        self,
        *,
        messages: list[AIMessage],
        tool_schemas: list[dict[str, object]],
        tool_results: list[dict[str, object]] | None = None,
    ) -> AIModelResponse:
        from ainza_restaurant.ai.errors import AIToolError

        last_exc: AIToolError | None = None
        for index, provider in enumerate(self._chain):
            try:
                return await provider.generate(
                    messages=messages,
                    tool_schemas=tool_schemas,
                    tool_results=tool_results,
                )
            except AIToolError as exc:
                code = getattr(exc, "code", "")
                if code not in _TRANSIENT_CODES:
                    # Hard failure — do not mask it behind a fallback.
                    raise
                last_exc = exc
                provider_name = type(provider).__name__
                next_name = (
                    type(self._chain[index + 1]).__name__
                    if index + 1 < len(self._chain)
                    else "none"
                )
                logger.warning(
                    "AI provider %s failed with %s; trying %s",
                    provider_name,
                    code,
                    next_name,
                )

        # All providers exhausted.
        from ainza_restaurant.ai.errors import AIToolError as _E

        raise _E(
            "All AI providers failed",
            code="ai_all_providers_failed",
        ) from last_exc

    async def generate_json(
        self,
        *,
        messages: list[AIMessage],
        json_schema: dict[str, object],
    ) -> AIModelResponse:
        """Delegate generate_json to the first provider that supports it."""
        from ainza_restaurant.ai.errors import AIToolError

        last_exc: AIToolError | None = None
        for index, provider in enumerate(self._chain):
            if not hasattr(provider, "generate_json"):
                continue
            try:
                return await provider.generate_json(  # type: ignore[union-attr]
                    messages=messages, json_schema=json_schema
                )
            except AIToolError as exc:
                code = getattr(exc, "code", "")
                if code not in _TRANSIENT_CODES:
                    raise
                last_exc = exc
                logger.warning(
                    "AI provider %s generate_json failed with %s; trying next",
                    type(provider).__name__,
                    code,
                )

        # No provider with generate_json succeeded — fall back to plain generate.
        return await self.generate(
            messages=messages,
            tool_schemas=[],
            tool_results=[],
        )

    async def stream_generate(
        self,
        *,
        messages: list[AIMessage],
        tool_schemas: list[dict[str, object]],
        tool_results: list[dict[str, object]] | None = None,
    ):
        """Yield text token chunks, delegating to the first provider that supports streaming.

        Falls back to a single non-streaming generate() call if no provider in the
        chain supports ``stream_generate``, yielding the entire response as one chunk.
        """
        from ainza_restaurant.ai.errors import AIToolError

        for provider in self._chain:
            if not hasattr(provider, "stream_generate"):
                continue
            try:
                async for chunk in provider.stream_generate(  # type: ignore[union-attr]
                    messages=messages,
                    tool_schemas=tool_schemas,
                    tool_results=tool_results,
                ):
                    yield chunk
                return
            except AIToolError as exc:
                code = getattr(exc, "code", "")
                if code not in _TRANSIENT_CODES:
                    raise
                logger.warning(
                    "AI provider %s stream_generate failed with %s; trying next",
                    type(provider).__name__,
                    code,
                )

        # Last resort: non-streaming fallback — yields the whole response as one chunk
        response = await self.generate(
            messages=messages,
            tool_schemas=tool_schemas,
            tool_results=tool_results,
        )
        if response.message and response.message.content:
            yield response.message.content

