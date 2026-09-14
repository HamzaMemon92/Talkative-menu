from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SpeechTranscriptionResult:
    text: str
    detected_language: str | None
    duration_seconds: float | None
    provider: str


class SpeechToTextProvider(Protocol):
    async def transcribe(
        self, audio_bytes: bytes, *, content_type: str, duration_seconds: float
    ) -> SpeechTranscriptionResult: ...
