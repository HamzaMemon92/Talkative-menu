from __future__ import annotations

import wave
from dataclasses import dataclass
from io import BytesIO

from ainza_restaurant.ai.speech.errors import VoiceAudioError


@dataclass(frozen=True)
class ValidatedWav:
    duration_seconds: float
    sample_rate: int
    channels: int


def validate_wav(
    audio_bytes: bytes, *, content_type: str, max_bytes: int, max_seconds: int
) -> ValidatedWav:
    if content_type.split(";", 1)[0].strip().casefold() != "audio/wav":
        raise VoiceAudioError(
            "voice audio must use Content-Type audio/wav",
            code="voice_audio_invalid_format",
        )
    if not audio_bytes:
        raise VoiceAudioError("voice audio is empty", code="voice_audio_empty")
    if len(audio_bytes) > max_bytes:
        raise VoiceAudioError("voice audio exceeds the size limit", code="voice_audio_too_large")
    try:
        with wave.open(BytesIO(audio_bytes), "rb") as wav:
            if wav.getcomptype() != "NONE":
                raise VoiceAudioError(
                    "voice audio must be uncompressed PCM WAV",
                    code="voice_audio_unsupported_encoding",
                )
            if wav.getsampwidth() != 2:
                raise VoiceAudioError(
                    "voice audio must be 16-bit PCM WAV",
                    code="voice_audio_unsupported_encoding",
                )
            channels = wav.getnchannels()
            if channels not in {1, 2}:
                raise VoiceAudioError(
                    "voice audio must be mono or stereo",
                    code="voice_audio_unsupported_encoding",
                )
            sample_rate = wav.getframerate()
            if not 8_000 <= sample_rate <= 48_000:
                raise VoiceAudioError(
                    "voice audio sample rate is unsupported",
                    code="voice_audio_unsupported_encoding",
                )
            duration_seconds = wav.getnframes() / sample_rate
    except VoiceAudioError:
        raise
    except (EOFError, wave.Error) as exc:
        raise VoiceAudioError(
            "voice audio is not a valid WAV file", code="voice_audio_invalid_format"
        ) from exc
    if duration_seconds > max_seconds:
        raise VoiceAudioError("voice audio exceeds the duration limit", code="voice_audio_too_long")
    return ValidatedWav(
        duration_seconds=duration_seconds,
        sample_rate=sample_rate,
        channels=channels,
    )
