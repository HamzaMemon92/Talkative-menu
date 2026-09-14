# Architecture

This project is a modular monolith: one deployable FastAPI application with
clear internal boundaries and one authoritative PostgreSQL database.

```text
Customer Web / Future QR
          |
          v
      FastAPI API
          |
   ----------------
   |      |       |
 Onboarding Menu  Orders / AI tools
   |      |       |
   ------Services--
          |
      PostgreSQL
          |
       Audit Log
```

Future Customer Web, Owner Web, WhatsApp, Voice, and terminal testing channels
must call the same services and database. AI should call deterministic tools,
not act as a database or authoritative business-state store.

Restaurant onboarding is the first business module. Its service validates
weekly hours on a circular seven-day clock (including split and overnight
intervals), requires an explicit tax-profile confirmation, and exposes
deterministic readiness/finalization state. Restaurant lifecycle and onboarding
state are separate enums. Slugs are normalized and unique, outlets have one
database-enforced primary outlet per restaurant, and all public routes are
versioned under `/api/v1`. GSTIN validation is format-only; the backend does
not calculate or infer tax rates.

Outlet food policy is a separate optional, one-to-one owner-confirmed record;
unknown food and certification states are preserved rather than inferred. The
menu catalog is draft-first and keeps reviewed dishes, exact Decimal prices,
metadata-only images, controlled badges, and modifiers in the same database.
Publishing performs explicit validation and does not introduce availability,
ordering, billing, import, OCR, AI, or upload-byte behavior.

Real-time availability is its own module. It reads catalog and outlet-hours
state but does not mutate `Dish.is_active`, menu publication, or ingredient
catalog records. Effective dish availability is derived by checking active,
non-revoked direct dish overrides and active, non-revoked overrides on required
confirmed ingredients. Multiple blockers are returned as causes.

Availability mutations are proposal-first. `AvailabilityProposal` records the
target, action, reason, duration, computed expiry, TTL, and status.
`AvailabilityProposalAffectedDish` stores the preview snapshot. Confirmation is
transactional and either confirms the proposal plus creates or revokes
overrides, or leaves no availability mutation. Repeated confirmation of an
already confirmed proposal is safe and does not create duplicate overrides.

Next-opening expiry is calculated with `zoneinfo` from the outlet IANA timezone
and weekly intervals. Overrides stop blocking when `expires_at <= now`, so no
scheduler is required for correctness. AI, voice, WhatsApp, OCR/import,
ordering, billing, realtime transport, authentication, and frontend behavior
remain outside the availability module.

The merchandising module adds dynamic commercial state while preserving the
menu catalog as the only product truth. `TodaysSpecial`, `FeaturedDish`, and
`Offer` reference existing catalog records. Effective activity is derived from
lifecycle status plus aware schedule timestamps; no scheduler is required.

Offer preview is a deterministic evaluator, not a cart or order system. It
resolves current catalog/variant price, applies an effective Today's Special
price for the exact dish/variant when present, then evaluates a single requested
offer. It reports eligibility, discount, amount-to-threshold, and line
availability. It does not calculate tax, create invoices, select best offers, or
stack multiple offers.

The customer menu module is a read-only service-layer composition over
restaurants, menus, availability, and merchandising. Future frontend, terminal,
and AI clients should consume this same read model instead of reimplementing
menu visibility, pricing, availability, UNKNOWN handling, image approval, or
offer presentation rules.

Customer-menu reads capture one logical `now` per request and batch-load menu
relations, active availability blockers, active specials, featured dishes, and
offers. This avoids obvious one-query-per-dish behavior for menus around a few
hundred dishes while deliberately avoiding Redis, WebSockets, or denormalized
customer-menu tables at this stage.

The dining module adds physical tables, QR locator resolution, and dining
sessions. `RestaurantTable` is a permanent outlet resource with a stable opaque
`public_qr_code`. `DiningSession` is temporary and references the table. A
partial unique index enforces one open session per table, while closed sessions
remain as history.

Table QR resolution returns backend JSON context only: restaurant, outlet,
table, current session state, and the Task 006 customer-menu route. It does not
redirect to a frontend URL and does not store React template, theme, color, or
component information. Future Template 01 through Template 10 frontends can
render the same backend context differently without changing table IDs, session
IDs, QR codes, or menu data.

The ordering module adds shared cart state and immutable submitted
`DiningOrder` rounds. Cart reads are live and re-evaluate current availability,
Today's Special pricing, modifier pricing, and one selected offer. Cart submit
requires an explicit confirmation and current quote token, then snapshots the
commercial facts into order rows. Submitted order lines are not mutated for
additional items; another cart submission creates another round.

The kitchen module is the operational execution layer for submitted orders.
Every new successful cart submission creates exactly one `KitchenTicket` and
one `KitchenTicketItem` for each `DiningOrderItem` in the same database
transaction. The operation order is: create `DiningOrder`, create
`DiningOrderItem` rows, create KOT rows, clear the cart, and commit. If KOT
creation fails, the transaction rolls back and the cart remains intact.

Kitchen tickets deliberately do not copy unnecessary money fields or recalculate
menu facts. They display from `DiningOrderItem` snapshots: dish name, variant
name, quantity, customer note, and modifier snapshot names. Availability,
special, offer, and price changes after submission do not retroactively change
accepted kitchen work.

Ticket and order aggregate status is synchronized by one kitchen service
function after every item or bulk transition. Item states are monotonic:
queued, preparing, ready, and served. Ticket states are queued, in progress,
ready, and served. `DiningOrder.status` summarizes the same execution progress
as submitted, in preparation, ready, and served. Reads do not mutate status or
timestamps.

Dining-session close safety now depends on ordering and kitchen execution. A
session cannot close while its shared cart is nonempty or any submitted
`DiningOrder` is not served. Serving the last item never automatically closes
the session; customers may submit later rounds until a close action is
explicitly requested.

Kitchen queue reads are outlet-scoped, eager-load ticket items and order item
snapshots, and order tickets by creation time with a deterministic ID
tie-breaker. V1 has one outlet-wide execution queue only. Staff authorization,
kitchen stations, printers, inventory deduction, order cancellation, realtime
push, billing, payments, AI, voice, and frontend template concerns remain
outside the kitchen module.

The billing module creates deterministic bill previews and finalized invoice
snapshots from submitted order snapshots and explicit outlet tax profile data.
Billing does not recalculate historical menu prices, offers, discounts, or
kitchen state. One finalized invoice locks further cart mutations and becomes a
close-session prerequisite when served orders exist.

The AI module is internal provider-neutral infrastructure. It has no public
HTTP chat route and no model runtime. `AIToolRegistry` is an explicit allowlist
of tool definitions with actor permissions, safety levels, Pydantic input
models, and handlers. `AIToolExecutor` validates actor permissions, rejects
unsafe input, enforces external confirmation for consequential tools, calls the
handler, and returns a serializable success/error envelope without stack traces,
SQL, secrets, or filesystem paths.

Future providers implement the `ToolCallingModelProvider` protocol and adapt
provider-neutral schemas exported from the registry. The model never receives a
SQLAlchemy session or raw SQL capability. Tool handlers wrap existing services:
customer menu, availability, ordering, billing, and owner availability
proposal/confirmation. React templates remain presentation clients of the same
backend data and are unrelated to the AI core.

Task 012 adds the first concrete model adapter and customer conversation
orchestrator. `LlamaCppToolCallingProvider` sends OpenAI-compatible chat
completion requests to the local llama.cpp server and converts model tool calls
back into project-owned `AIToolCall` values. It strips visible `<think>` blocks
before persistence.

`CustomerAIConversationService` owns conversation creation, bounded transcript
history, customer-only tool schema exposure, tool-result feedback, and pending
confirmation creation. Conversation rows are outlet/session scoped. Message
rows store only visible text and safe status/error metadata. Pending
confirmation rows store the validated consequential tool payload so confirmed
actions can be executed exactly once without trusting later model output.

Tool-backed customer turns have a grounded route contract. The model may
interpret language and choose allowlisted candidate tools, but a route requiring
restaurant state must produce tool evidence. One controlled retry is permitted
when the model declines a supplied tool; otherwise the customer receives a safe
verification failure rather than model prose. `GroundedResponseRenderer`
presents typed executor results directly, so a second free-form model call
cannot contradict menu, availability, cart, order, offer, or bill facts.
Casual no-tool conversation remains model-generated.

Task 015F-7 makes typed customer intent planning the production control path:
natural language flows through `CustomerIntentPlan`, then
`CustomerIntentPlanCompiler`, existing allowlisted tools, PostgreSQL, and
`GroundedResponseRenderer`. Plans contain customer-level references and
constraints, never database identifiers, prices, or confirmation authority.
The compiler resolves real dishes, variants, modifiers, and cart items through
the customer-visible services before invoking the same executor. The legacy
candidate-router/direct-tool-call path remains a temporary compatibility path
for injected providers only and has a documented removal condition.

Planner JSON is untrusted even when constrained by a provider schema. The
planner first projects raw objects through the declared `CustomerIntentPlan`
field allowlist, records only discarded field names for local diagnostics, then
applies strict intent-specific Pydantic validation. Internal identifiers,
prices, confirmation flags, SQL-like fields, and arbitrary keys cannot reach
the compiler or executor.

Task 015F-9 uses hierarchical semantic planning: a constrained Stage A
classifier returns only an intent, then the backend selects a Stage B schema
with slots relevant solely to that intent. No-slot intents compile immediately.
For entity-targeting intents, normalized matching may resolve exactly one
customer-visible dish name found in the original utterance; ambiguous or absent
names remain clarification cases.

Inference deployment is independent from the local restaurant backend. The
shared OpenAI-compatible provider reads its endpoint URL, model alias, optional
bearer credential, and local/remote runtime mode from configuration. Remote GPU
inference changes no FastAPI, PostgreSQL, cart, ordering, billing, or grounded
rendering behavior; local llama.cpp startup remains a local-mode concern only.

The customer AI routes are thin API wrappers under `/api/v1`. There are no
owner AI routes in Task 012, and no API accepts filesystem model paths, raw SQL,
provider credentials, or arbitrary tool definitions from clients.

Task 013 keeps this architecture unchanged for multilingual text. Qwen maps
English, Hindi, Hinglish, Gujarati, Gujlish, and code-switched wording to the
same customer tool schemas and canonical backend enums. The response follows
the latest customer language/style, but backend dish names, IDs, prices, and
safety metadata remain untouched authoritative data. No translation service,
language-specific service, schema, route, or migration is required.

Task 014 adds a request-scoped STT edge: validated WAV bytes flow to a
long-running localhost whisper.cpp server, then the returned transcript flows
into `CustomerAIConversationService`. Whisper cannot access restaurant data or
tools. The process-local STT gate permits one active local inference, raw audio
is never persisted, and FastAPI does not start or manage the speech process.

Task 014A splits preview from send. The preview endpoint checks conversation
scope and uses that same STT edge, but ends at a response schema containing
only transcript text and detected language. A later normal text-message call
is the explicit boundary that may invoke the customer AI and its existing
tools. This keeps preview side-effect free and leaves the Task 014 direct
voice-message endpoint backward-compatible.
