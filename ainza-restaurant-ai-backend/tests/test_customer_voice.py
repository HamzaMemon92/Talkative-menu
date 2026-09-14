from __future__ import annotations

import asyncio
import io
import json
import wave

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ainza_restaurant.ai.db_models import (
    AIConversationMessage,
    AIMessageRole,
    AIPendingToolConfirmation,
)
from ainza_restaurant.ai.models import AIMessage, AIModelResponse
from ainza_restaurant.ai.service import AIConversationNotFound, CustomerAIConversationService
from ainza_restaurant.ai.speech.audio import validate_wav
from ainza_restaurant.ai.speech.errors import SpeechToTextError, VoiceAudioError
from ainza_restaurant.ai.speech.models import SpeechTranscriptionResult
from ainza_restaurant.ai.speech.service import CustomerVoiceMessageService
from ainza_restaurant.ai.speech.whisper_cpp import WhisperCppSpeechToTextProvider
from ainza_restaurant.kitchen.models import KitchenTicket
from ainza_restaurant.ordering.models import CartItem, DiningOrder
from tests.test_ai_tools import NOW, urban_tadka
from tests.test_customer_ai_conversation import SequenceProvider


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from ainza_restaurant.db.base import Base

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as database_session:
        yield database_session
    await engine.dispose()


def pcm_wav(*, seconds: int = 1, sample_rate: int = 16_000, channels: int = 1) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\x00\x00" * seconds * sample_rate * channels)
    return buffer.getvalue()


def test_wav_validation_rejects_unsafe_input_and_accepts_pcm() -> None:
    valid = validate_wav(pcm_wav(), content_type="audio/wav", max_bytes=1_000_000, max_seconds=30)
    assert valid.duration_seconds == 1
    assert valid.channels == 1
    for payload, content_type, code in (
        (b"", "audio/wav", "voice_audio_empty"),
        (b"invalid", "audio/wav", "voice_audio_invalid_format"),
        (pcm_wav(), "audio/webm", "voice_audio_invalid_format"),
        (pcm_wav(seconds=2), "audio/wav", "voice_audio_too_long"),
    ):
        with pytest.raises(VoiceAudioError) as error:
            validate_wav(payload, content_type=content_type, max_bytes=1_000_000, max_seconds=1)
        assert error.value.code == code


@pytest.mark.asyncio
async def test_whisper_provider_uses_local_multipart_and_sanitizes_errors() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers["content-type"]
        return httpx.Response(200, json={"text": "નમસ્તે", "language": "gu"})

    provider = WhisperCppSpeechToTextProvider(
        base_url="http://127.0.0.1:8082",
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await provider.transcribe(pcm_wav(), content_type="audio/wav", duration_seconds=1)
    assert result.text == "નમસ્તે"
    assert result.detected_language == "gu"
    assert captured["url"] == "http://127.0.0.1:8082/inference"
    assert "multipart/form-data" in str(captured["content_type"])

    async def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("hidden detail")

    timeout_provider = WhisperCppSpeechToTextProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(timeout))
    )
    with pytest.raises(SpeechToTextError) as timeout_error:
        await timeout_provider.transcribe(pcm_wav(), content_type="audio/wav", duration_seconds=1)
    assert timeout_error.value.code == "stt_timeout"


class FakeSpeechProvider:
    def __init__(self, text: str, *, detected_language: str = "hi") -> None:
        self.text = text
        self.detected_language = detected_language
        self.calls = 0

    async def transcribe(
        self, audio_bytes: bytes, *, content_type: str, duration_seconds: float
    ) -> SpeechTranscriptionResult:
        self.calls += 1
        assert audio_bytes
        assert content_type == "audio/wav"
        return SpeechTranscriptionResult(
            text=self.text,
            detected_language=self.detected_language,
            duration_seconds=duration_seconds,
            provider="fake",
        )


@pytest.mark.asyncio
async def test_voice_reuses_text_conversation_and_replays_without_retranscription(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    model = SequenceProvider(
        [
            AIModelResponse(
                message=AIMessage(role="assistant", content="Paneer Tikka available hai.")
            )
        ]
    )
    conversation = CustomerAIConversationService(session, provider=model, now=lambda: NOW)
    created = await conversation.create_conversation(data["dining_session"].public_session_token)
    stt = FakeSpeechProvider("Paneer me kya available hai?")
    voice = CustomerVoiceMessageService(conversation, provider=stt)

    first = await voice.send_message(
        created.conversation_token,
        client_message_id="voice-1",
        audio_bytes=pcm_wav(),
        content_type="audio/wav",
    )
    replay = await voice.send_message(
        created.conversation_token,
        client_message_id="voice-1",
        audio_bytes=pcm_wav(),
        content_type="audio/wav",
    )
    messages = list((await session.execute(select(AIConversationMessage))).scalars())

    assert first.transcript.text == "Paneer me kya available hai?"
    assert replay.assistant_message == first.assistant_message
    assert stt.calls == 1
    assert len(model.calls) == 1
    assert [message.role for message in messages] == [AIMessageRole.USER, AIMessageRole.ASSISTANT]
    assert all("audio" not in column.name for column in AIConversationMessage.__table__.columns)


@pytest.mark.asyncio
async def test_voice_preview_is_unicode_safe_and_has_no_conversation_side_effects(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    model = SequenceProvider(
        [
            AIModelResponse(
                message=AIMessage(role="assistant", content="Paneer Tikka is available.")
            ),
            AIModelResponse(message=AIMessage(role="assistant", content="Edited text received.")),
        ]
    )
    conversation = CustomerAIConversationService(session, provider=model, now=lambda: NOW)
    created = await conversation.create_conversation(data["dining_session"].public_session_token)
    stt = FakeSpeechProvider(
        "\u092a\u0928\u0940\u0930 \u092e\u0947\u0902 \u0915\u094d\u092f\u093e available hai?",
        detected_language="hi",
    )
    voice = CustomerVoiceMessageService(conversation, provider=stt)

    preview = await voice.transcribe_preview(
        created.conversation_token, audio_bytes=pcm_wav(), content_type="audio/wav"
    )

    assert (
        preview.transcript.text
        == "\u092a\u0928\u0940\u0930 \u092e\u0947\u0902 \u0915\u094d\u092f\u093e available hai?"
    )
    assert preview.transcript.detected_language == "hi"
    serialized_preview = json.dumps(preview.model_dump(mode="json"))
    assert "audio" not in serialized_preview
    assert "ggml" not in serialized_preview
    assert "models" not in serialized_preview
    assert stt.calls == 1
    assert model.calls == []
    assert await session.scalar(select(func.count()).select_from(AIConversationMessage)) == 0
    assert await session.scalar(select(func.count()).select_from(CartItem)) == 0
    assert await session.scalar(select(func.count()).select_from(DiningOrder)) == 0
    assert await session.scalar(select(func.count()).select_from(KitchenTicket)) == 0

    sent = await conversation.send_message(
        created.conversation_token,
        client_message_id="accepted-transcript",
        message=preview.transcript.text,
    )

    assert sent.assistant_message == "Paneer Tikka is available."
    edited = await conversation.send_message(
        created.conversation_token,
        client_message_id="edited-transcript",
        message="Show vegetarian paneer dishes.",
    )

    transcript = await conversation.get_conversation(created.conversation_token)
    assert edited.assistant_message == "Edited text received."
    assert len(model.calls) == 2
    assert [
        message.content for message in transcript.messages if message.role == AIMessageRole.USER
    ] == [
        preview.transcript.text,
        "Show vegetarian paneer dishes.",
    ]
    assert await session.scalar(select(func.count()).select_from(AIConversationMessage)) == 4


@pytest.mark.asyncio
async def test_spoken_mutation_preview_cannot_create_cart_or_order_work(
    session: AsyncSession,
) -> None:
    data = await urban_tadka(session)
    model = SequenceProvider([])
    conversation = CustomerAIConversationService(session, provider=model, now=lambda: NOW)
    created = await conversation.create_conversation(data["dining_session"].public_session_token)
    voice = CustomerVoiceMessageService(
        conversation,
        provider=FakeSpeechProvider("Add two Paneer Tikka. Place the order."),
    )

    preview = await voice.transcribe_preview(
        created.conversation_token, audio_bytes=pcm_wav(), content_type="audio/wav"
    )

    assert preview.transcript.text == "Add two Paneer Tikka. Place the order."
    assert model.calls == []
    assert await session.scalar(select(func.count()).select_from(AIConversationMessage)) == 0
    assert await session.scalar(select(func.count()).select_from(CartItem)) == 0
    assert await session.scalar(select(func.count()).select_from(AIPendingToolConfirmation)) == 0
    assert await session.scalar(select(func.count()).select_from(DiningOrder)) == 0
    assert await session.scalar(select(func.count()).select_from(KitchenTicket)) == 0


@pytest.mark.asyncio
async def test_voice_preview_requires_an_existing_conversation(session: AsyncSession) -> None:
    conversation = CustomerAIConversationService(
        session,
        provider=SequenceProvider([]),
        now=lambda: NOW,
    )
    stt = FakeSpeechProvider("hello")
    voice = CustomerVoiceMessageService(conversation, provider=stt)

    with pytest.raises(AIConversationNotFound) as error:
        await voice.transcribe_preview("missing", audio_bytes=pcm_wav(), content_type="audio/wav")

    assert error.value.code == "ai_conversation_not_found"
    assert stt.calls == 0


@pytest.mark.asyncio
async def test_voice_gate_serializes_transcription() -> None:
    active = 0
    maximum = 0

    class SlowProvider(FakeSpeechProvider):
        async def transcribe(
            self, audio_bytes: bytes, *, content_type: str, duration_seconds: float
        ) -> SpeechTranscriptionResult:
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            active -= 1
            return await super().transcribe(
                audio_bytes, content_type=content_type, duration_seconds=duration_seconds
            )

    from ainza_restaurant.ai.speech.whisper_cpp import SpeechToTextConcurrencyGate

    provider = SlowProvider("hello")
    gate = SpeechToTextConcurrencyGate()
    await asyncio.gather(
        gate.transcribe(provider, pcm_wav(), content_type="audio/wav", duration_seconds=1),
        gate.transcribe(provider, pcm_wav(), content_type="audio/wav", duration_seconds=1),
    )
    assert maximum == 1
