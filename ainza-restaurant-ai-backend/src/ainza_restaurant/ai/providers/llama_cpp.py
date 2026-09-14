from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
from pydantic import SecretStr

from ainza_restaurant.ai.errors import AIToolError
from ainza_restaurant.ai.models import AIMessage, AIModelResponse, AIToolCall
from ainza_restaurant.core.config import get_settings

_CONFIGURED_API_KEY = object()


class AIModelProviderError(AIToolError):
    pass


class LlamaCppToolCallingProvider:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        top_p: float = 0.8,
        top_k: int = 20,
        min_p: float = 0,
        api_key: SecretStr | str | None | object = _CONFIGURED_API_KEY,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.local_llm_base_url).rstrip("/")
        self.model = model or settings.local_llm_model
        self.timeout_seconds = timeout_seconds or settings.local_llm_timeout_seconds
        self.connect_timeout_seconds = settings.local_llm_connect_timeout_seconds
        self.max_tokens = max_tokens or settings.local_llm_max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.min_p = min_p
        configured_key = settings.local_llm_api_key if api_key is _CONFIGURED_API_KEY else api_key
        if isinstance(configured_key, str):
            self._api_key: SecretStr | None = SecretStr(configured_key)
        elif isinstance(configured_key, SecretStr):
            self._api_key = configured_key
        else:
            self._api_key = None
        self._client_factory = client_factory

    async def generate(
        self,
        *,
        messages: list[AIMessage],
        tool_schemas: list[dict[str, object]],
        tool_results: list[dict[str, object]] | None = None,
    ) -> AIModelResponse:
        request = self.build_request(messages, tool_schemas, tool_results or [])
        try:
            if self._client_factory is None:
                timeout = httpx.Timeout(
                    connect=self.connect_timeout_seconds,
                    read=self.timeout_seconds,
                    write=self.connect_timeout_seconds,
                    pool=self.connect_timeout_seconds,
                )
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions", json=request, headers=self._headers()
                    )
            else:
                client = self._client_factory()
                response = await client.post(
                    f"{self.base_url}/chat/completions", json=request, headers=self._headers()
                )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AIModelProviderError("AI model timed out", code="ai_model_timeout") from exc
        except httpx.HTTPStatusError as exc:
            print("GEMINI HTTP STATUS ERROR:", exc.response.status_code, exc.response.text)
            if exc.response.status_code in {401, 403}:
                raise AIModelProviderError(
                    "AI model authentication failed", code="ai_model_authentication_failed"
                ) from exc
            if 400 <= exc.response.status_code < 500:
                raise AIModelProviderError(
                    f"AI model rejected the request: {exc.response.text}",
                    code="ai_model_invalid_request",
                ) from exc
            raise AIModelProviderError(
                "AI model is unavailable", code="ai_model_unavailable"
            ) from exc
        except httpx.HTTPError as exc:
            raise AIModelProviderError(
                "AI model is unavailable", code="ai_model_unavailable"
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
        except AIModelProviderError:
            raise
        except Exception as exc:
            raise AIModelProviderError(
                "AI model returned an invalid response",
                code="ai_model_invalid_response",
            ) from exc

    async def stream_generate(
        self,
        *,
        messages: list[AIMessage],
        tool_schemas: list[dict[str, object]],
        tool_results: list[dict[str, object]] | None = None,
    ) -> AsyncIterator[str]:
        """Yield text token chunks as they arrive from the model (streaming mode).

        Uses the same OpenAI-compat ``/chat/completions`` endpoint with ``stream=True``.
        Yields ``str`` chunks. Strips ``<think>`` blocks on-the-fly so internal reasoning
        is never exposed in the stream.

        Usage::

            async for token in provider.stream_generate(messages=..., tool_schemas=[]):
                print(token, end="", flush=True)
        """
        request = self.build_request(messages, tool_schemas, tool_results or [])
        request["stream"] = True
        # stream=True is incompatible with parallel_tool_calls and tool_choice
        # (streaming is only used for the final text synthesis call, never for tool selection).
        request.pop("parallel_tool_calls", None)

        timeout = httpx.Timeout(
            connect=self.connect_timeout_seconds,
            read=self.timeout_seconds,
            write=self.connect_timeout_seconds,
            pool=self.connect_timeout_seconds,
        )
        _in_think = False
        _think_buf = ""

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json=request,
                    headers=self._headers(),
                ) as response:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        code = (
                            "ai_model_authentication_failed"
                            if exc.response.status_code in {401, 403}
                            else "ai_model_invalid_request"
                            if 400 <= exc.response.status_code < 500
                            else "ai_model_unavailable"
                        )
                        raise AIModelProviderError("AI model streaming failed", code=code) from exc

                    async for raw_line in response.aiter_lines():
                        if not raw_line.startswith("data:"):
                            continue
                        data = raw_line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        token: str = delta.get("content") or ""
                        if not token:
                            continue

                        # Strip <think>…</think> blocks on-the-fly
                        combined = _think_buf + token
                        _think_buf = ""
                        output = ""
                        while combined:
                            if _in_think:
                                end = combined.find("</think>")
                                if end == -1:
                                    _think_buf = combined
                                    combined = ""
                                else:
                                    _in_think = False
                                    combined = combined[end + len("</think>") :]
                            else:
                                start = combined.find("<think>")
                                if start == -1:
                                    output += combined
                                    combined = ""
                                else:
                                    output += combined[:start]
                                    _in_think = True
                                    combined = combined[start + len("<think>") :]
                        if output:
                            yield output
        except httpx.TimeoutException as exc:
            raise AIModelProviderError("AI model timed out", code="ai_model_timeout") from exc
        except httpx.HTTPError as exc:
            raise AIModelProviderError(
                "AI model is unavailable", code="ai_model_unavailable"
            ) from exc

    async def generate_json(
        self, *, messages: list[AIMessage], json_schema: dict[str, object]
    ) -> AIModelResponse:
        request = self.build_request(messages, [], [])
        request["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "structured_response",
                "schema": _compact_schema(json_schema),
                "strict": True,
            },
        }
        try:
            timeout = httpx.Timeout(
                connect=self.connect_timeout_seconds,
                read=self.timeout_seconds,
                write=self.connect_timeout_seconds,
                pool=self.connect_timeout_seconds,
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions", json=request, headers=self._headers()
                )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AIModelProviderError("AI model timed out", code="ai_model_timeout") from exc
        except httpx.HTTPStatusError as exc:
            code = (
                "ai_model_authentication_failed"
                if exc.response.status_code in {401, 403}
                else "ai_model_invalid_request"
                if 400 <= exc.response.status_code < 500
                else "ai_model_unavailable"
            )
            raise AIModelProviderError("AI model request failed", code=code) from exc
        except httpx.HTTPError as exc:
            raise AIModelProviderError(
                "AI model is unavailable", code="ai_model_unavailable"
            ) from exc
        try:
            message = response.json()["choices"][0].get("message") or {}
            content = _strip_reasoning(message.get("content") or "")
            return AIModelResponse(
                message=AIMessage(role="assistant", content=content) if content else None
            )
        except Exception as exc:
            raise AIModelProviderError(
                "AI model returned an invalid response",
                code="ai_model_invalid_response",
            ) from exc

    async def probe(self) -> bool:
        """Safely check endpoint reachability and configured model exposure on demand."""
        try:
            timeout = httpx.Timeout(
                connect=self.connect_timeout_seconds,
                read=self.timeout_seconds,
                write=self.connect_timeout_seconds,
                pool=self.connect_timeout_seconds,
            )
            if self._client_factory is None:
                client = httpx.AsyncClient(timeout=timeout)
            else:
                client = self._client_factory()
            async with client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
            response.raise_for_status()
            payload = response.json()
            models = payload.get("data") if isinstance(payload, dict) else None
            return any(
                isinstance(item, dict)
                and isinstance(item.get("id"), str)
                and (item["id"] == self.model or item["id"].removeprefix("models/") == self.model)
                for item in models or []
            )
        except (httpx.HTTPError, ValueError, TypeError):
            return False

    def _headers(self) -> dict[str, str]:
        if self._api_key is None:
            return {}
        return {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}

    def build_request(
        self,
        messages: list[AIMessage],
        tool_schemas: list[dict[str, object]],
        tool_results: list[dict[str, object]],
    ) -> dict[str, Any]:
        request_messages: list[dict[str, Any]] = []
        for message in messages:
            msg_dict: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.role == "tool":
                msg_dict["tool_call_id"] = message.tool_call_id or "tool_call"
            if message.role == "assistant" and message.tool_calls:
                tc_list: list[dict[str, Any]] = []
                for tc in message.tool_calls:
                    tc_dict: dict[str, Any] = {
                        "id": str(tc.id or "tool_call"),
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                            if isinstance(tc.arguments, dict)
                            else str(tc.arguments),
                        },
                    }
                    if tc.extra_content:
                        tc_dict["extra_content"] = tc.extra_content
                    tc_list.append(tc_dict)
                msg_dict["tool_calls"] = tc_list
            request_messages.append(msg_dict)

        if tool_results:
            request_messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": str(result.get("tool_call_id") or "tool_call"),
                            "type": "function",
                            "function": {
                                "name": str(result.get("name") or result.get("tool") or "tool"),
                                "arguments": json.dumps(result.get("arguments") or {}),
                            },
                        }
                        for result in tool_results
                    ],
                }
            )
            for result in tool_results:
                request_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(result.get("tool_call_id") or "tool_call"),
                        "name": str(result.get("name") or result.get("tool") or "tool"),
                        "content": json.dumps(result.get("content") or result, ensure_ascii=False),
                    }
                )

        request = {
            "model": self.model,
            "messages": request_messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }
        if tool_schemas:
            request.update(
                {
                    "tools": [_to_openai_tool(tool) for tool in tool_schemas],
                    "tool_choice": "auto",
                    "parallel_tool_calls": False,
                }
            )
        return request


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
    """Remove JSON Schema annotations llama.cpp does not need for tool validation."""
    if isinstance(value, dict):
        return {
            key: _compact_schema(item)
            for key, item in value.items()
            if key not in {"title", "default"}
        }
    if isinstance(value, list):
        return [_compact_schema(item) for item in value]
    return value


def _parse_tool_call(value: dict[str, Any]) -> AIToolCall:
    function = value.get("function") or {}
    name = function.get("name")
    raw_arguments = function.get("arguments") or "{}"
    if not isinstance(name, str) or not name:
        raise AIModelProviderError("model tool call is invalid", code="ai_model_invalid_response")
    try:
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
    except json.JSONDecodeError as exc:
        raise AIModelProviderError(
            "model emitted malformed tool arguments",
            code="ai_model_tool_parse_error",
        ) from exc
    if not isinstance(arguments, dict):
        raise AIModelProviderError(
            "model tool arguments must be a JSON object",
            code="ai_model_tool_parse_error",
        )
    return AIToolCall(
        id=value.get("id"),
        name=name,
        arguments=arguments,
        extra_content=value.get("extra_content"),
    )


def _strip_reasoning(content: str) -> str:
    while "<think>" in content and "</think>" in content:
        before, rest = content.split("<think>", 1)
        _hidden, after = rest.split("</think>", 1)
        content = before + after
    return content.strip()
