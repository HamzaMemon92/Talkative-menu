from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import SecretStr

from ainza_restaurant.ai.errors import AIToolError
from ainza_restaurant.ai.models import AIMessage, AIModelResponse, AIToolCall
from ainza_restaurant.core.config import get_settings


class CloudflareProviderError(AIToolError):
    pass


class CloudflareToolCallingProvider:
    """Cloudflare Workers AI via its OpenAI-compatible gateway.

    Endpoint: https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1
    Auth:     Bearer {api_token}

    Configure via .env:
        CLOUDFLARE_ACCOUNT_ID=...
        CLOUDFLARE_API_TOKEN=...
        CLOUDFLARE_MODEL=@cf/meta/llama-3.3-70b-instruct-fp8-fast
    """

    def __init__(
        self,
        *,
        account_id: str | None = None,
        api_token: SecretStr | str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        top_p: float = 0.95,
    ) -> None:
        settings = get_settings()
        _account_id = account_id or settings.cloudflare_account_id
        if not _account_id:
            raise CloudflareProviderError(
                "Cloudflare account_id is required",
                code="cloudflare_misconfigured",
            )
        raw_token = api_token or settings.cloudflare_api_token
        if raw_token is None:
            raise CloudflareProviderError(
                "Cloudflare api_token is required",
                code="cloudflare_misconfigured",
            )
        self._api_token: SecretStr = (
            raw_token if isinstance(raw_token, SecretStr) else SecretStr(raw_token)
        )
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{_account_id}/ai/v1"
        self.model = model or settings.cloudflare_model
        self.timeout_seconds = timeout_seconds or settings.cloudflare_timeout_seconds
        self.max_tokens = max_tokens or settings.cloudflare_max_tokens
        self.temperature = temperature
        self.top_p = top_p

    async def generate(
        self,
        *,
        messages: list[AIMessage],
        tool_schemas: list[dict[str, object]],
        tool_results: list[dict[str, object]] | None = None,
    ) -> AIModelResponse:
        request = self._build_request(messages, tool_schemas, tool_results or [])
        try:
            timeout = httpx.Timeout(connect=10.0, read=self.timeout_seconds, write=10.0, pool=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=request,
                    headers=self._headers(),
                )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise CloudflareProviderError(
                "Cloudflare AI timed out", code="ai_model_timeout"
            ) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                raise CloudflareProviderError(
                    "Cloudflare AI authentication failed",
                    code="ai_model_authentication_failed",
                ) from exc
            if 400 <= exc.response.status_code < 500:
                raise CloudflareProviderError(
                    "Cloudflare AI rejected the request",
                    code="ai_model_invalid_request",
                ) from exc
            raise CloudflareProviderError(
                "Cloudflare AI is unavailable", code="ai_model_unavailable"
            ) from exc
        except httpx.HTTPError as exc:
            raise CloudflareProviderError(
                "Cloudflare AI is unavailable", code="ai_model_unavailable"
            ) from exc
        try:
            payload = response.json()
            choice = payload["choices"][0]
            message = choice.get("message") or {}
            content = _strip_reasoning(message.get("content") or "")
            calls = [_parse_tool_call(item) for item in message.get("tool_calls") or []]
            return AIModelResponse(
                message=AIMessage(role="assistant", content=content) if content else None,
                tool_calls=calls,
                raw_finish_reason=choice.get("finish_reason"),
            )
        except CloudflareProviderError:
            raise
        except Exception as exc:
            raise CloudflareProviderError(
                "Cloudflare AI returned an invalid response",
                code="ai_model_invalid_response",
            ) from exc

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_token.get_secret_value()}"}

    def _build_request(
        self,
        messages: list[AIMessage],
        tool_schemas: list[dict[str, object]],
        tool_results: list[dict[str, object]],
    ) -> dict[str, Any]:
        request_messages: list[dict[str, Any]] = [
            {"role": m.role, "content": m.content} for m in messages
        ]
        if tool_results:
            request_messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": str(r.get("tool_call_id") or "tool_call"),
                            "type": "function",
                            "function": {
                                "name": str(r.get("name") or r.get("tool") or "tool"),
                                "arguments": json.dumps(r.get("arguments") or {}),
                            },
                        }
                        for r in tool_results
                    ],
                }
            )
        for r in tool_results:
            request_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(r.get("tool_call_id") or "tool_call"),
                    "name": str(r.get("name") or r.get("tool") or "tool"),
                    "content": json.dumps(r.get("content") or r, ensure_ascii=False),
                }
            )
        request: dict[str, Any] = {
            "model": self.model,
            "messages": request_messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }
        if not tool_results and tool_schemas:
            request.update(
                {
                    "tools": [_to_openai_tool(t) for t in tool_schemas],
                    "tool_choice": "auto",
                }
            )
        return request


# ── Shared helpers ──────────────────────────────────────────────────────────────


def _to_openai_tool(tool: dict[str, object]) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description") or "",
            "parameters": _compact_schema(tool["input_schema"]),
        },
    }


def _compact_schema(value: object) -> object:
    if isinstance(value, dict):
        return {k: _compact_schema(v) for k, v in value.items() if k not in {"title", "default"}}
    if isinstance(value, list):
        return [_compact_schema(item) for item in value]
    return value


def _parse_tool_call(value: dict[str, Any]) -> AIToolCall:
    function = value.get("function") or {}
    name = function.get("name")
    raw_arguments = function.get("arguments") or "{}"
    if not isinstance(name, str) or not name:
        raise CloudflareProviderError(
            "Cloudflare tool call is invalid", code="ai_model_invalid_response"
        )
    try:
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
    except json.JSONDecodeError as exc:
        raise CloudflareProviderError(
            "Cloudflare emitted malformed tool arguments",
            code="ai_model_tool_parse_error",
        ) from exc
    if not isinstance(arguments, dict):
        raise CloudflareProviderError(
            "Cloudflare tool arguments must be a JSON object",
            code="ai_model_tool_parse_error",
        )
    return AIToolCall(id=value.get("id"), name=name, arguments=arguments)


def _strip_reasoning(content: str) -> str:
    while "<think>" in content and "</think>" in content:
        before, rest = content.split("<think>", 1)
        _hidden, after = rest.split("</think>", 1)
        content = before + after
    return content.strip()
