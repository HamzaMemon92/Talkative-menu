from __future__ import annotations

from ainza_restaurant.ai.schemas import (
    AIConversationMessageRead,
    VoiceMessageRead,
    VoiceTranscriptionRead,
    VoiceTranscriptRead,
)
from ainza_restaurant.ai.service import CustomerAIConversationService
from ainza_restaurant.ai.speech.audio import validate_wav
from ainza_restaurant.ai.speech.models import SpeechToTextProvider, SpeechTranscriptionResult
from ainza_restaurant.ai.speech.whisper_cpp import (
    SpeechToTextConcurrencyGate,
    WhisperCppSpeechToTextProvider,
)
from ainza_restaurant.core.config import get_settings

_STT_GATE = SpeechToTextConcurrencyGate()


class CustomerVoiceMessageService:
    def __init__(
        self,
        conversation_service: CustomerAIConversationService,
        *,
        provider: SpeechToTextProvider | None = None,
        gate: SpeechToTextConcurrencyGate | None = None,
    ) -> None:
        self.conversation_service = conversation_service
        self.provider = provider or WhisperCppSpeechToTextProvider()
        self.gate = gate or _STT_GATE

    async def send_message(
        self,
        conversation_token: str,
        *,
        client_message_id: str,
        audio_bytes: bytes,
        content_type: str,
    ) -> VoiceMessageRead:
        replay = await self.conversation_service.replay_completed_message(
            conversation_token, client_message_id
        )
        if replay is not None:
            transcript, response = replay
            return _voice_response(transcript, None, response)
        transcription = await self._transcribe(audio_bytes, content_type)
        response = await self.conversation_service.send_message(
            conversation_token,
            client_message_id=client_message_id,
            message=transcription.text,
        )
        return _voice_response(transcription.text, transcription.detected_language, response)

    async def transcribe_preview(
        self, conversation_token: str, *, audio_bytes: bytes, content_type: str
    ) -> VoiceTranscriptionRead:
        await self.conversation_service.get_conversation(conversation_token)
        transcription = await self._transcribe(audio_bytes, content_type)
        return VoiceTranscriptionRead(
            transcript=VoiceTranscriptRead(
                text=transcription.text,
                detected_language=transcription.detected_language,
            )
        )

    async def _transcribe(self, audio_bytes: bytes, content_type: str) -> SpeechTranscriptionResult:
        settings = get_settings()
        wav = validate_wav(
            audio_bytes,
            content_type=content_type,
            max_bytes=settings.local_stt_max_audio_bytes,
            max_seconds=settings.local_stt_max_audio_seconds,
        )
        return await self.gate.transcribe(
            self.provider,
            audio_bytes,
            content_type=content_type,
            duration_seconds=wav.duration_seconds,
        )


def _voice_response(
    text: str, detected_language: str | None, response: AIConversationMessageRead
) -> VoiceMessageRead:
    return VoiceMessageRead(
        transcript=VoiceTranscriptRead(text=text, detected_language=detected_language),
        assistant_message=response.assistant_message,
        confirmation_required=response.confirmation_required,
        tools_used=response.tools_used,
    )
