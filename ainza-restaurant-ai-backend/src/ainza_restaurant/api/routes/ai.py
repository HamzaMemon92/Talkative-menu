# ruff: noqa: B008
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.ai.schemas import (
    AIConfirmationRead,
    AIConfirmationRequest,
    AIConversationCreateRead,
    AIConversationMessageCreate,
    AIConversationMessageRead,
    AIConversationRead,
    VoiceMessageRead,
    VoiceTranscriptionRead,
)
from ainza_restaurant.ai.service import (
    AIConversationConflict,
    AIConversationNotFound,
    CustomerAIConversationService,
)
from ainza_restaurant.ai.speech.errors import SpeechToTextError
from ainza_restaurant.ai.speech.service import CustomerVoiceMessageService
from ainza_restaurant.core.config import get_settings
from ainza_restaurant.db.session import get_db_session

router = APIRouter(tags=["customer ai"])


def service(session: AsyncSession = Depends(get_db_session)) -> CustomerAIConversationService:
    return CustomerAIConversationService(session)


def voice_service(
    ai: CustomerAIConversationService = Depends(service),
) -> CustomerVoiceMessageService:
    return CustomerVoiceMessageService(ai)


def _not_found(exc: AIConversationNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})


def _conflict(exc: AIConversationConflict) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": exc.code, "message": str(exc), "details": exc.details},
    )


def _speech_error(exc: SpeechToTextError) -> HTTPException:
    status_code = (
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE if exc.code == "voice_audio_too_large" else 422
    )
    if exc.code in {"stt_server_unavailable", "stt_timeout"}:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)})


def _reject_oversized_voice_request(request: Request) -> None:
    content_length = request.headers.get("content-length")
    if content_length is not None and content_length.isdigit():
        if int(content_length) > get_settings().local_stt_max_audio_bytes:
            raise _speech_error(
                SpeechToTextError(
                    "voice audio exceeds the size limit", code="voice_audio_too_large"
                )
            )


@router.post(
    "/api/v1/dining-sessions/{session_token}/ai/conversations",
    response_model=AIConversationCreateRead,
)
async def create_ai_conversation(
    session_token: str,
    ai: CustomerAIConversationService = Depends(service),
) -> AIConversationCreateRead:
    try:
        return await ai.create_conversation(session_token)
    except AIConversationNotFound as exc:
        raise _not_found(exc) from exc
    except AIConversationConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/ai/conversations/{conversation_token}", response_model=AIConversationRead)
async def get_ai_conversation(
    conversation_token: str,
    ai: CustomerAIConversationService = Depends(service),
) -> AIConversationRead:
    try:
        return await ai.get_conversation(conversation_token)
    except AIConversationNotFound as exc:
        raise _not_found(exc) from exc


@router.post(
    "/api/v1/ai/conversations/{conversation_token}/messages",
    response_model=AIConversationMessageRead,
)
async def send_ai_message(
    conversation_token: str,
    payload: AIConversationMessageCreate,
    ai: CustomerAIConversationService = Depends(service),
) -> AIConversationMessageRead:
    try:
        return await ai.send_message(
            conversation_token,
            client_message_id=payload.client_message_id,
            message=payload.message,
        )
    except AIConversationNotFound as exc:
        raise _not_found(exc) from exc
    except AIConversationConflict as exc:
        raise _conflict(exc) from exc


@router.post(
    "/api/v1/ai/conversations/{conversation_token}/messages/stream",
    summary="Stream an AI message response via Server-Sent Events",
    response_class=StreamingResponse,
)
async def stream_ai_message(
    conversation_token: str,
    payload: AIConversationMessageCreate,
    ai: CustomerAIConversationService = Depends(service),
) -> StreamingResponse:
    """SSE endpoint — yields structured events as the AI processes the message.

    Each ``data:`` line is a JSON object with a ``type`` field:

    - ``tool_start`` / ``tool_done`` — real-time tool execution progress
    - ``token`` — one text chunk from the streaming LLM response
    - ``done`` — final payload (tools_used, confirmation_required, navigation, discovery)
    - ``error`` — unrecoverable error

    Clients should consume with the ``EventSource`` API or an SSE library.
    """

    async def _generate() -> AsyncIterator[str]:
        try:
            async for event in ai.stream_message(
                conversation_token,
                client_message_id=payload.client_message_id,
                message=payload.message,
            ):
                yield event
        except AIConversationNotFound:
            import json as _json

            err_payload = {
                "type": "error",
                "code": "not_found",
                "message": "Conversation not found",
            }
            yield f"data: {_json.dumps(err_payload)}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.post(
    "/api/v1/ai/conversations/{conversation_token}/voice/transcriptions",
    response_model=VoiceTranscriptionRead,
)
async def transcribe_voice_message(
    conversation_token: str,
    request: Request,
    voice: CustomerVoiceMessageService = Depends(voice_service),
) -> VoiceTranscriptionRead:
    try:
        _reject_oversized_voice_request(request)
        return await voice.transcribe_preview(
            conversation_token,
            audio_bytes=await request.body(),
            content_type=request.headers.get("content-type", ""),
        )
    except AIConversationNotFound as exc:
        raise _not_found(exc) from exc
    except SpeechToTextError as exc:
        raise _speech_error(exc) from exc


@router.post(
    "/api/v1/ai/conversations/{conversation_token}/voice/messages",
    response_model=VoiceMessageRead,
)
async def send_voice_message(
    conversation_token: str,
    request: Request,
    x_client_message_id: str,
    voice: CustomerVoiceMessageService = Depends(voice_service),
) -> VoiceMessageRead:
    client_message_id = x_client_message_id.strip()
    if not client_message_id or len(client_message_id) > 120:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "voice_client_message_id_invalid",
                "message": "invalid client message id",
            },
        )
    _reject_oversized_voice_request(request)
    try:
        return await voice.send_message(
            conversation_token,
            client_message_id=client_message_id,
            audio_bytes=await request.body(),
            content_type=request.headers.get("content-type", ""),
        )
    except AIConversationNotFound as exc:
        raise _not_found(exc) from exc
    except AIConversationConflict as exc:
        raise _conflict(exc) from exc
    except SpeechToTextError as exc:
        raise _speech_error(exc) from exc


@router.post(
    "/api/v1/ai/conversations/{conversation_token}/confirmations/{confirmation_token}",
    response_model=AIConfirmationRead,
)
async def confirm_ai_action(
    conversation_token: str,
    confirmation_token: str,
    payload: AIConfirmationRequest,
    ai: CustomerAIConversationService = Depends(service),
) -> AIConfirmationRead:
    try:
        return await ai.confirm(conversation_token, confirmation_token, confirm=payload.confirm)
    except AIConversationNotFound as exc:
        raise _not_found(exc) from exc
    except AIConversationConflict as exc:
        raise _conflict(exc) from exc
