# AI tool layer

Task 011 introduces the provider-neutral AI tool boundary. Task 012 connects
that boundary to customer text conversations through the local llama.cpp
OpenAI-compatible server. It does not download weights, install runtimes, add
owner chat, or expose model control to clients.

Core rule:

```text
human language -> future LLM -> AI tool layer -> deterministic services -> database
```

The model must never receive raw SQL, SQLAlchemy sessions, filesystem access,
or authority to calculate menu prices, offers, taxes, bill totals, availability,
or order history.

## Context

`AIToolContext` is injected by server code. It binds actor type, outlet, and
optional dining-session token. Tool argument models intentionally omit
authoritative `outlet_id`, `restaurant_id`, and `session_token` fields when
that scope already exists in context.

`AIActorType.CUSTOMER` and `AIActorType.OWNER` are separated by the registry.
`OWNER` context is internal infrastructure only; it is not authentication.

## Confirmation

Consequential tools require `ToolExecutionAuthorization` with
`explicit_user_confirmation=True`. This object is supplied outside
model-generated tool arguments. A model-generated `confirm=true` field is either
rejected by `extra="forbid"` input validation or ignored by tools that do not
accept it.

## Registered tools

Customer tools:

- `menu_get`
- `menu_search`
- `menu_get_dish`
- `dish_get_availability`
- `offers_get_effective`
- `menu_quote_selection`
- `cart_get`
- `cart_add_item`
- `cart_update_item`
- `cart_remove_item`
- `cart_select_offer`
- `cart_submit`
- `orders_get_session`
- `bill_get_preview`

Owner tools:

- `owner_get_availability`
- `owner_create_availability_proposal`
- `owner_get_availability_proposal`
- `owner_confirm_availability_proposal`

## Provider abstraction

`ToolCallingModelProvider` is a small protocol for future text-model adapters.
Tool schemas are exported as provider-neutral JSON-schema-compatible data from
Pydantic models. `LlamaCppToolCallingProvider` calls
`LOCAL_LLM_BASE_URL/v1/chat/completions` and parses OpenAI-compatible
tool-calling responses from the local llama.cpp server. There are no OpenAI,
Anthropic, LangChain, LlamaIndex, transformers, torch, vLLM,
`llama-cpp-python`, or Ollama dependencies in this package.

Expected local runtime files are provisioned outside package dependencies:

- `D:\talkative menu\models\llm\Qwen3-8B-Q4_K_M.gguf`
- `D:\talkative menu\runtimes\llama.cpp\llama-server.exe`

Use `scripts/start_local_llm.ps1` or `scripts/start_local_llm.cmd` to launch
the local server, and `scripts/check_local_llm.py` to confirm `/v1/models`.

## Customer conversations

Task 012 persists customer conversation state in:

- `ai_conversations`
- `ai_conversation_messages`
- `ai_pending_tool_confirmations`

Only visible user and assistant text, confirmation metadata, and safe error
codes are stored. Hidden reasoning, chain-of-thought, or model scratchpad text
must not be persisted or returned. The system prompt starts with `/no_think`,
and the provider adapter strips `<think>...</think>` blocks from visible model
content as an additional guard.

Customer text endpoints are scoped to an existing dining session and outlet.
The model receives only customer-allowed tool schemas. If it asks for an owner
tool, the executor returns a safe forbidden tool result rather than running the
handler.

## Multilingual customer text

Task 013 uses the same pre-provisioned Qwen model for English, Hindi
(Devanagari), Hinglish, Gujarati, Gujlish, and normal code-switching. It adds
no translator, cloud fallback, language-specific routes, schemas, or business
services. The model maps customer wording to the existing canonical English
tool names and enum values; deterministic services remain authoritative.

Responses normally follow the customer's latest language/style. Exact backend
menu names stay identifiable, and cart operations use backend IDs only.
UNKNOWN remains UNKNOWN in every language, including dietary, Jain, vegan,
spice, allergen, and halal-related data. Allergy uncertainty must be stated
with a staff-verification recommendation. Budget-fit language requires a
`menu_quote_selection` tool result. Explicit cart mutations are required;
natural-language confirmation is not implemented and order submission remains
the external confirmation endpoint.

`cart_submit` is treated specially. A model request creates a pending
confirmation using the live server cart quote token and a server-generated
idempotency key. The order is submitted only when the confirmation endpoint is
called with `confirm=true`.

## Safety

## Customer voice input

Task 014 adds `SpeechToTextProvider` and the local
`WhisperCppSpeechToTextProvider`. FastAPI accepts raw `audio/wav` bytes only,
validates uncompressed 16-bit PCM WAV (mono/stereo, 8-48 kHz, 30 seconds, 8 MB),
then forwards it to an externally managed localhost whisper.cpp `/inference`
endpoint. It requests transcription, not translation, with automatic spoken
language detection.

The transcript enters the existing `CustomerAIConversationService`; customer
tool scope, idempotency, cart mutations, and pending order confirmation remain
unchanged. Audio is never stored or logged. There is no TTS, streaming voice,
cloud fallback, owner voice AI, or frontend audio conversion. Start the server
explicitly with `scripts/start_local_stt.cmd`; FastAPI never starts it.

Task 014A provides `POST /voice/transcriptions` under a valid customer
conversation as the preferred preview path. It returns a non-persistent
transcript and detected language after STT only. It does not call the model or
tools. Clients must explicitly accept or edit the transcript before posting it
to the ordinary customer `/messages` endpoint.

Tools wrap existing services. They do not duplicate pricing, availability,
offer, ordering, kitchen, or billing logic. UNKNOWN dietary/allergen/religious
metadata is preserved exactly as backend data and is not converted into safe or
negative claims.
