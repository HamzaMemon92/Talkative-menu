from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx

from ainza_restaurant.ai.speech.errors import SpeechToTextError
from ainza_restaurant.ai.speech.models import SpeechToTextProvider, SpeechTranscriptionResult
from ainza_restaurant.core.config import get_settings


class WhisperCppSpeechToTextProvider:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
        language: str | None = None,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.local_stt_base_url).rstrip("/")
        self.timeout_seconds = timeout_seconds or settings.local_stt_timeout_seconds
        self.language = language or settings.local_stt_language
        self._client_factory = client_factory

    async def transcribe(
        self, audio_bytes: bytes, *, content_type: str, duration_seconds: float
    ) -> SpeechTranscriptionResult:
        files = {"file": ("voice.wav", audio_bytes, content_type)}
        data = {"language": self.language, "response_format": "json"}
        try:
            if self._client_factory is None:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(
                        f"{self.base_url}/inference", files=files, data=data
                    )
            else:
                client = self._client_factory()
                response = await client.post(f"{self.base_url}/inference", files=files, data=data)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise SpeechToTextError("local speech server timed out", code="stt_timeout") from exc
        except httpx.HTTPError as exc:
            raise SpeechToTextError(
                "local speech server is unavailable", code="stt_server_unavailable"
            ) from exc
        return _parse_response(response, duration_seconds)


class SpeechToTextConcurrencyGate:
    def __init__(self, capacity: int = 1) -> None:
        self._semaphore = asyncio.Semaphore(capacity)

    async def transcribe(
        self,
        provider: SpeechToTextProvider,
        audio_bytes: bytes,
        *,
        content_type: str,
        duration_seconds: float,
    ) -> SpeechTranscriptionResult:
        async with self._semaphore:
            return await provider.transcribe(
                audio_bytes, content_type=content_type, duration_seconds=duration_seconds
            )


def _parse_response(response: httpx.Response, duration_seconds: float) -> SpeechTranscriptionResult:
    try:
        payload: dict[str, Any] = response.json()
    except ValueError as exc:
        raise SpeechToTextError(
            "local speech server returned an invalid response", code="stt_invalid_response"
        ) from exc
    text = payload.get("text") or payload.get("transcription")
    if not isinstance(text, str):
        raise SpeechToTextError(
            "local speech server returned an invalid response", code="stt_invalid_response"
        )
    text = text.strip()
    if not text:
        raise SpeechToTextError(
            "local speech server returned an empty transcript", code="stt_empty_transcript"
        )
    language = payload.get("language") or payload.get("detected_language")
    return SpeechTranscriptionResult(
        text=text,
        detected_language=language if isinstance(language, str) and language else None,
        duration_seconds=duration_seconds,
        provider="whisper.cpp",
    )
