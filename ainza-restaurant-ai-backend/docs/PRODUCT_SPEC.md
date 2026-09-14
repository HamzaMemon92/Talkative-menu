# Product specification

## Vision

Ainza is an India-first intelligent restaurant platform. Customers can use a
normal digital menu and optionally “Talk to the Menu”; owners can eventually
“Talk to the Restaurant”. AI enhances normal restaurant workflows rather than
replacing them.

## Principles and scope

The normal menu remains available with approved exact images, categories,
descriptions, prices, dietary information, spice/allergen information,
availability, Today's Special, featured dishes, offers, and normal ordering.
Customer AI ordering and future owner commands must use the same backend truth.

Task 013 supports customer text in English, Hindi (Devanagari), Hinglish,
Gujarati, Gujlish, and code-switched text through the same conversation API.
The local Qwen model interprets language only: canonical backend tools, enums,
IDs, prices, availability, safety metadata, cart rules, and external order
confirmation remain the source of truth. Exact menu names are preserved; no
translation service, cloud fallback, or language-specific business path exists.
The design is multilingual and India-first.

Task 014 permits a customer to explicitly submit a short WAV voice message.
Local whisper.cpp transcribes it without translation, then the normal customer
conversation receives the transcript as visible user text. V1 is WAV-only,
bounded to 30 seconds and 8 MB, has no raw-audio retention, no TTS, no
streaming/always-listening mode, and no cloud speech fallback. Voice cart and
order intent use the same deterministic tools and explicit order confirmation.

Task 014A makes transcript preview the preferred voice interaction. A valid
conversation may submit WAV bytes to the transcription endpoint and receives
only text plus detected language. Preview does not invoke Qwen or tools and
does not persist a message or mutate cart, order, kitchen, or billing state.
The customer can accept the exact transcript, edit it, or discard it; only an
accepted/edited text message uses the normal customer conversation workflow.

Availability may support a next-opening reset. Today's Special, Featured,
Bestseller, and Offers are separate concepts. Billing and tax calculations must
be deterministic and use an explicit tax profile. Consequential owner actions
require confirmation.

Real-time availability is operational state, not catalog lifecycle. A dish can
remain active in the catalog and present in a published menu while temporarily
sold out. Effective availability is derived from blocking causes: direct dish
overrides and required confirmed ingredient overrides. Optional ingredient
relationships do not block a dish, and dish names are never used to infer
ingredient impact.

Owner availability changes use preview and confirmation. Proposal creation
calculates affected dishes, stores that snapshot, computes expiry, and does not
mutate availability. Confirmation rechecks affected dishes and next-opening
expiry to reject stale proposals. Restores revoke active overrides without
deleting audit history and do not guarantee availability while another blocker
remains.

Next-opening expiry uses the outlet IANA timezone and weekly operating hours,
including split shifts, closed periods, overnight service, closed days, and the
Sunday/Monday boundary. Continuous 24/7 outlets have no distinct next-opening
boundary and must use timestamp or indefinite duration. Expired overrides stop
blocking at read time, so correctness does not depend on a scheduler.

Today's Special, Featured Dish, Chef Recommended, Offer, and Bestseller are
distinct. Chef Recommended remains a persistent catalog badge. Today's Special
is temporary merchandising and may have a temporary price overlay. Featured Dish
is dynamic placement with no price change. Offers are deterministic commercial
rules. Bestseller is not manually editable and will be calculated later from
real order/analytics data.

Task 005 uses one catalog truth. Specials, featured dishes, and offers reference
existing confirmed published dishes, variants, or categories; they do not copy
names, images, prices, diet, allergens, or ingredients. Special prices and
offers never override Task 004 availability. A sold-out special or featured dish
remains sold out.

Offer preview evaluates one specified offer using authoritative prices only. It
supports amount-to-threshold guidance, selected dish/category scope, fixed-price
combos, maximum percentage caps, and flat-discount floors. Pricing precedence is
catalog or variant price, then active special price, then selected offer. Tax,
GST, final billing, automatic best-offer selection, and offer stacking are
future work.

The customer digital menu is a read model over existing authoritative facts. It
shows only active restaurants, active outlets, published menus, active
categories, active confirmed dishes, active variants, approved exact images,
active modifiers/options, confirmed ingredients, effective specials/features,
and effective offers. Temporary unavailability does not hide a dish; customers
see a safe sold-out state instead of internal operational notes.

Customer pricing preserves the deterministic precedence of catalog/variant
price first, effective Today's Special price second, and offers separately.
UNKNOWN dietary, halal, spice, and allergen states remain UNKNOWN and are never
treated as false, safe, vegan, mild, halal, or allergen-free. Outlet food-policy
metadata is exposed only as customer-safe confirmed owner declarations and never
as platform verification.

Physical restaurant tables and dining sessions are separate concepts. A table
is long-lived, has a display label such as `T2` or `Patio 1`, and may carry a
stable opaque QR locator. A dining session represents a temporary party seated
at that table and is closed explicitly when the party leaves. Occupancy is
derived from an open dining session, not stored as a mutable table boolean.

The table QR is a public locator, not proof of customer identity. Multiple
customer devices may join the same open dining session by scanning the same QR.
After the session is closed, the next scan starts a new session with a new
session token while the physical QR normally remains unchanged. Dining sessions
do not snapshot menus or override availability; Task 006 remains the
customer-menu authority.

A dining-session cart is shared draft order state. Customers may add multiple
items and then submit the cart as an immutable `DiningOrder` round. Submitted
orders preserve commercial truth: item names, variant names, modifiers, notes,
prices, selected offer, discount, currency, and tax-category snapshots. Later
menu, price, offer, special, or availability changes do not rewrite accepted
orders.

Kitchen execution is represented separately from the commercial order. A
`KitchenTicket`/KOT is the operational record created automatically for every
new submitted `DiningOrder`; a `KitchenTicketItem` tracks execution for each
submitted order line. The kitchen display uses order snapshots, not current
menu records. Availability changes after submission affect future carts and
orders only; they do not cancel or alter accepted KOTs.

Kitchen item status is monotonic. Allowed transitions are queued to preparing,
queued to ready, preparing to ready, and ready to served. Repeating the same
action is idempotent and does not rewrite first transition timestamps. Ticket
and order aggregate status is derived from item states: all queued means
submitted, mixed queued/preparing/ready/served means in preparation, all
ready-or-served with at least one ready means ready, and all served means
served. Ticket-level start, ready, and serve actions support simple kitchen
workflows while preserving item-level truth.

Dining sessions do not close automatically when food is served. A session may
close only when its cart is empty and all dining-order rounds are served. Ready
but unserved food still keeps the session active. Later billing may add bill and
payment requirements before close.

The founding version is free. Future Pro and Business plans are explicitly out
of scope for this foundation task. AI providers must remain replaceable.

The AI tool layer is an internal safety boundary for future customer and owner
language interfaces. AI interprets human language, but tools call deterministic
backend services and the database remains authoritative. Customer tools are
bound to server-provided outlet/session context and cannot select another
outlet or session through model arguments. Owner tools are internal
architecture only until authentication exists.

Consequential actions require human confirmation outside model-generated tool
payloads. A model cannot authorize `cart_submit` or owner availability
confirmation by emitting `confirm=true`. UNKNOWN dietary, allergen, halal,
Jain, vegan, and spice metadata remains UNKNOWN in tool results. AI does not
calculate authoritative money, discounts, tax, bill totals, availability, or
order state.

Customer Talk-to-Menu text AI is scoped to an existing open dining session. A
customer starts a conversation with a dining-session token, sends text, and
receives a visible assistant response. The assistant may use customer-safe menu,
availability, offer, cart, order-history, and bill-preview tools, but it cannot
select another outlet/session or call owner tools.

Conversation storage is operational transcript state, not model memory. It
stores visible user/assistant messages, pending confirmation records, and safe
error codes only. Hidden reasoning, chain-of-thought, model scratchpads, and
internal tool definitions are not persisted or returned.

AI order submission never happens solely because a model emitted a tool call.
When the model requests `cart_submit`, the backend creates a pending
confirmation using the current cart quote token and a server-generated
idempotency key. The order is placed only after the external confirmation
endpoint receives `confirm=true`.

The text AI runtime is local-only for this phase. No model downloads, hosted LLM
APIs, embeddings, vector search, OCR, speech, WhatsApp, payments, frontend, or
owner AI assistant are part of Task 012.
