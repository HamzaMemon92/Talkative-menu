from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from ainza_restaurant.ai.models import AIMessage
from ainza_restaurant.ai.providers.llama_cpp import (
    AIModelProviderError,
    LlamaCppToolCallingProvider,
)
from ainza_restaurant.core.config import get_settings


def test_settings_accept_local_and_remote_openai_compatible_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_LLM_RUNTIME_MODE", "remote")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "https://remote-endpoint.example/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "ainza-qwen3-8b")
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.local_llm_runtime_mode == "remote"
        assert settings.local_llm_base_url == "https://remote-endpoint.example/v1"
        assert settings.local_llm_api_key is None
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_provider_sends_optional_bearer_header_without_exposing_secret() -> None:
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.headers)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = LlamaCppToolCallingProvider(
        base_url="https://remote-endpoint.example/v1",
        model="ainza-qwen3-8b",
        api_key="secret-value",
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    response = await provider.generate(
        messages=[AIMessage(role="user", content="hello")], tool_schemas=[]
    )

    assert response.message is not None
    assert captured["authorization"] == "Bearer secret-value"
    assert "secret-value" not in repr(provider)


@pytest.mark.asyncio
async def test_provider_omits_auth_and_classifies_auth_failures() -> None:
    captured: dict[str, str] = {}

    async def unauthenticated(request: httpx.Request) -> httpx.Response:
        captured.update(request.headers)
        return httpx.Response(401, json={"error": "unauthorized"})

    provider = LlamaCppToolCallingProvider(
        api_key=None,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(unauthenticated)),
    )
    with pytest.raises(AIModelProviderError) as error:
        await provider.generate(messages=[], tool_schemas=[])

    assert "authorization" not in captured
    assert error.value.code == "ai_model_authentication_failed"


def test_remote_launcher_path_does_not_require_or_start_local_runtime() -> None:
    script = Path("scripts/start_human_typed_test.ps1").read_text(encoding="utf-8")
    local_launcher = Path("scripts/start_local_llm.ps1").read_text(encoding="utf-8")

    assert '$runtimeMode -eq "local"' in script
    assert "LOCAL_LLM_MODEL_PATH is required when LOCAL_LLM_RUNTIME_MODE=local" in script
    assert "remote; local llama-server startup is disabled" in local_launcher
