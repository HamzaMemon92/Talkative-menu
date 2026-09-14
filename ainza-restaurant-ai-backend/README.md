# Ainza Restaurant AI Backend

Backend foundation for an India-first restaurant platform centered on “Talk to
the Menu” for customers and “Talk to the Restaurant” for owners.

## Current status

Task 002 and Task 002C are complete: restaurant onboarding and explicitly
confirmed outlet food policy are implemented. Task 003 provides a draft-first
menu catalog foundation. Task 004 adds deterministic real-time availability.
Task 005 adds Today's Special, Featured Dish, and Offers. Billing calculations,
AI inference, speech, OCR, payments, WhatsApp, auth, uploads, and frontend
features remain intentionally out of scope.
Task 006 adds the customer digital menu read model consumed by future
frontend, terminal, and AI clients. It composes published catalog, operational
availability, specials, featured dishes, offers, images, modifiers, ingredients,
dietary/allergen metadata, outlet food policy, tax-inclusion metadata, and
currency without mutating source records.
Task 007 adds physical restaurant tables, stable opaque table QR locators, and
temporary dining sessions. Task 008 adds a shared cart and immutable submitted
multi-round dining orders. Task 009 adds kitchen tickets/KOT execution for
submitted orders. Task 010 adds deterministic bill preview and finalized
invoice snapshots. Task 011 adds the internal provider-neutral AI tool layer
that future models will call. Task 012 adds customer Talk-to-Menu text AI with
the local llama.cpp runtime and pre-existing Qwen GGUF model. Speech, OCR,
WhatsApp, auth, uploads, frontend features, kitchen stations, printer
integrations, owner AI chat, or payment flows are not implemented.

## Prerequisites

- Python 3.12
- Docker and Docker Compose (for local PostgreSQL)

## Local setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
Copy-Item .env.example .env
docker compose up -d db
```

## Run the API

```powershell
uvicorn ainza_restaurant.main:app --reload
```

The API includes `GET /health` plus versioned Task 002 endpoints under
`/api/v1/restaurants`: restaurant and outlet CRUD, atomic weekly-hours
replacement, tax-profile read/write, deterministic onboarding status, and
finalization with an explicit `{"confirm": true}` body. Slugs are normalized
and unique, one primary outlet is enforced, time zones are validated with
`zoneinfo`, and tax rates are never inferred or auto-populated.

Task 002C adds `PUT`/`GET /api/v1/outlets/{outlet_id}/food-policy`. Food and
dietary values use explicit `unknown`-first enums and the write requires
`confirmation: true`; the policy is optional for onboarding readiness.

Task 003 adds draft-first menu, category, cuisine, dish, variant, ingredient,
allergen/dietary, image metadata, modifier, and controlled-badge endpoints.
Cuisine and ingredient replacements validate ownership before changing any
rows. Publishing is explicit and validates reviewed dishes, categories,
non-negative Decimal prices, and approved images. There are deliberately no
import/OCR/AI/upload-byte, ordering, billing, Today's Special, Featured,
Bestseller, or Offers endpoints.

Task 004 adds real-time availability endpoints. Catalog membership
`Dish.is_active` remains separate from operational availability. Availability is
derived from active blocking causes: direct dish overrides and required
confirmed ingredient overrides. Proposal creation stores an affected-dish
snapshot and does not mutate availability; explicit confirmation applies the
change transactionally after stale-proposal checks. Overrides expire at read
time without a scheduler, and restores revoke active overrides while preserving
history.

Availability endpoints:

- `POST /api/v1/outlets/{outlet_id}/availability/proposals`
- `GET /api/v1/availability-proposals/{proposal_id}`
- `POST /api/v1/availability-proposals/{proposal_id}/confirm`
- `POST /api/v1/availability-proposals/{proposal_id}/cancel`
- `GET /api/v1/dishes/{dish_id}/availability`
- `GET /api/v1/ingredients/{ingredient_id}/availability`
- `GET /api/v1/outlets/{outlet_id}/availability`

Future order placement must recheck authoritative current availability before
accepting an order; stale clients must not bypass sold-out state.

Task 005 adds dynamic merchandising without shadow products. Today's Special
references an existing confirmed published dish and may overlay a temporary
Decimal price without mutating catalog or variant prices. Featured Dish is a
separate owner promotion with display order and no discount. Offers support
percentage, flat, and combo fixed-price rules with dish/category scope and combo
items. Offer preview resolves authoritative prices, applies effective special
price first, then evaluates one specified offer. There is no tax/GST, invoice,
order, stacking, automatic best-offer selection, or manual Bestseller behavior.

Task 006 adds read-only customer menu endpoints:

- `GET /api/v1/outlets/{outlet_id}/customer-menu`
- `GET /api/v1/outlets/{outlet_id}/customer-menu/dishes/{dish_id}`
- `GET /api/v1/outlets/{outlet_id}/customer-menu/search?q=...`

Only active restaurants/outlets and published menus are visible. Sold-out items
remain visible with customer-safe availability such as `sold_out`; internal
availability notes are not exposed. Pricing returns Decimal catalog/effective
values plus `currency_code`; presentation symbols are left to clients. Offers
are exposed as effective customer-safe summaries and are not automatically
stacked or selected as "best offer."

Task 007 adds table and dining-session endpoints:

- `POST`/`GET /api/v1/outlets/{outlet_id}/tables`
- `GET`/`PATCH /api/v1/tables/{table_id}`
- `POST /api/v1/tables/{table_id}/rotate-qr`
- `GET /api/v1/qr/{public_qr_code}`
- `POST /api/v1/qr/{public_qr_code}/sessions`
- `POST /api/v1/tables/{table_id}/sessions`
- `GET /api/v1/dining-sessions/{public_session_token}`
- `GET /api/v1/tables/{table_id}/active-session`
- `POST /api/v1/dining-sessions/{public_session_token}/close`

A table is a permanent physical resource. A dining session is one temporary
party/use of that table. Occupancy is derived from an open session; there is no
stored `is_occupied` flag. Table QR codes are stable opaque locators, not user
authentication. Explicit QR rotation exists for administrative reset cases.
Future frontend templates remain presentation-only and must consume the same
backend table/session/customer-menu data.

Task 008 adds shared-cart and order endpoints:

- `GET /api/v1/dining-sessions/{session_token}/cart`
- `POST`/`PATCH`/`DELETE /api/v1/dining-sessions/{session_token}/cart/items/...`
- `PUT /api/v1/dining-sessions/{session_token}/cart/offer`
- `POST /api/v1/dining-sessions/{session_token}/cart/submit`
- `GET /api/v1/dining-sessions/{session_token}/orders`

A cart is live operational/commercial draft state for an open dining session.
Submitting a cart creates an immutable `DiningOrder` round with item, modifier,
price, discount, and tax-category snapshots. A submitted order is not edited;
additional items are placed through a later cart submission as a new round.

Task 009 adds kitchen/KOT endpoints:

- `GET /api/v1/outlets/{outlet_id}/kitchen/tickets`
- `GET /api/v1/kitchen/tickets/{ticket_id}`
- `POST /api/v1/kitchen/tickets/{ticket_id}/start`
- `POST /api/v1/kitchen/tickets/{ticket_id}/ready`
- `POST /api/v1/kitchen/tickets/{ticket_id}/serve`
- `POST /api/v1/kitchen/items/{ticket_item_id}/start`
- `POST /api/v1/kitchen/items/{ticket_item_id}/ready`
- `POST /api/v1/kitchen/items/{ticket_item_id}/serve`

Every new successful cart submission automatically creates exactly one
`KitchenTicket` and one `KitchenTicketItem` per submitted order item in the
same transaction. If KOT creation fails, the order is not committed and the cart
remains intact. Kitchen reads use the submitted order snapshots for dish names,
variant names, quantities, customer notes, and modifier names; current menu,
offer, special, price, or availability changes do not rewrite accepted KOTs.

Kitchen item transitions are monotonic: queued to preparing, queued to ready,
preparing to ready, and ready to served. Repeating the same state is safe and
does not rewrite the first transition timestamp. Ticket and order aggregate
status is derived from item states: all queued means queued/submitted, mixed
work means in progress/in preparation, all ready-or-served with at least one
ready means ready, and all served means served. Serving the final item does not
automatically close the dining session. A session can close only when the cart
is empty and all submitted order rounds are served; future billing may tighten
this further.

Kitchen mutation endpoints are development-stage APIs and must require staff
authorization before production use. Task 009 does not implement order
cancellation, kitchen station routing, thermal/KOT printer integration,
partial-quantity readiness within one order line, inventory deduction, tax/final
billing, payment, realtime push, AI, voice, frontend, or React templates.

Task 010 adds billing endpoints:

- `GET /api/v1/dining-sessions/{session_token}/bill-preview`
- `POST /api/v1/dining-sessions/{session_token}/invoice/finalize`
- `GET /api/v1/dining-sessions/{session_token}/invoice`
- `GET /api/v1/invoices/{invoice_id}`

Bill preview reads submitted order snapshots and explicit outlet tax profile
data. Finalization creates immutable invoice snapshots. It does not implement
payments, refunds, split billing, service-charge automation, credit notes, or
tax-law inference.

Task 011 adds an internal AI tool layer under `src/ainza_restaurant/ai`.
The AI architecture is provider-neutral: future models interpret language, but
registered tools execute deterministic backend services and the database remains
authoritative. Tool arguments are Pydantic models with unsafe extra fields
forbidden. Server-injected `AIToolContext` binds actor, outlet, and dining
session scope, so a model cannot choose another tenant/session through tool
arguments. Consequential tools require external
`ToolExecutionAuthorization.explicit_user_confirmation`; model-generated
`confirm=true` cannot authorize cart submission or owner availability
confirmation.

Task 012 adds customer Talk-to-Menu text AI endpoints:

- `POST /api/v1/dining-sessions/{session_token}/ai/conversations`
- `GET /api/v1/ai/conversations/{conversation_token}`
- `POST /api/v1/ai/conversations/{conversation_token}/messages`
- `POST /api/v1/ai/conversations/{conversation_token}/confirmations/{confirmation_token}`

The local model adapter calls llama.cpp's OpenAI-compatible
`/v1/chat/completions` endpoint at `LOCAL_LLM_BASE_URL`. The repository does
not download models or install LLM runtimes. The expected local files are the
pre-provisioned `D:\talkative menu\models\llm\Qwen3-8B-Q4_K_M.gguf` model and
`D:\talkative menu\runtimes\llama.cpp\llama-server.exe` runtime. Convenience
startup/check scripts live under `scripts/`.

Conversation persistence stores only visible user and assistant messages,
pending confirmation metadata, and safe error codes. It does not store hidden
reasoning or chain-of-thought. Customer AI receives only customer-allowed
tools. Order submission is paused as a pending confirmation and is executed
only after an external confirmation endpoint call; the server injects the live
cart quote token and idempotency key.

Task 013 extends the same customer conversation endpoints to English, Hindi
(Devanagari), Hinglish, Gujarati, and Gujlish, including normal code-switching.
The existing local Qwen model interprets language and returns natural responses
in the customer's current style; no translation service, cloud fallback, or
language-specific backend is used. Tool identifiers and enums remain canonical
English backend contracts. Exact menu names and backend IDs are preserved,
UNKNOWN dietary/allergen facts remain UNKNOWN in every language, and budget
claims require a deterministic `menu_quote_selection` result. Cart changes
still require explicit mutation intent, while order submission remains an
external confirmation only.

## Run tests and checks

## Customer Voice Input

Task 014 adds push-to-talk speech-to-text through a separately started local
whisper.cpp server. `POST /api/v1/ai/conversations/{conversation_token}/voice/messages`
accepts raw `audio/wav` bytes with `X-Client-Message-ID`. V1 accepts only
16-bit PCM mono/stereo WAV at 8-48 kHz, capped at 30 seconds and 8 MB. Audio is
validated then forwarded to localhost only; it is never persisted. Whisper
transcribes without translation and the resulting visible transcript is sent
to the existing customer conversation service, tools, cart rules, and external
order confirmation flow. There is no TTS, streaming, cloud fallback, or
frontend recording support yet.

Task 014A adds the preferred human-safe path:
`POST /api/v1/ai/conversations/{conversation_token}/voice/transcriptions`.
It validates an existing conversation and returns only a transcript preview;
it does not call Qwen, tools, cart/order/KOT services, or persistence. The
voice CLI shows `YOU SAID` and requires send, edit, or discard before it sends
the accepted text through the normal `/messages` endpoint. A human microphone
check used local `whisper-stream.exe`, `Microphone Array (Intel Smart Sound
Technology for Digital Microphones)`, 16 kHz mono, and the pre-provisioned
`ggml-large-v3-turbo-q5_0.bin` model. The spoken English phrase "Show me
vegetarian dishes." was transcribed once exactly and once with a harmless
inserted "the". Hindi and Gujarati microphone input were not claimed.

```powershell
pytest
ruff check .
ruff format --check .
mypy src
```

## PostgreSQL

`docker compose up -d db` starts a local development database using the
placeholders in `docker-compose.yml`. These values are not production
credentials. Run `docker compose down` when finished.

The production database remains PostgreSQL. Tests use an in-memory SQLite
database through `aiosqlite`; this is test-only and does not alter production
configuration.
