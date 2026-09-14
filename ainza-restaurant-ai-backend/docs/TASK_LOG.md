# Task log

## Task 015F-11 - Remote Qwen3-8B Complete Backend Validation

- **Date:** 2026-09-11
- **Status:** Stopped before validation; remote endpoint connection unavailable.
- **Remote attempt:** The first bounded customer message failed during HTTPS
  connection establishment before model generation, planning, tool execution,
  or database mutation. The remaining three messages were not sent.
- **Security:** The remote API key was neither printed nor persisted.
- **Migration:** None; Alembic head remains `014_customer_ai_conversations`.

## Task 015F-10 - Remote GPU Inference Readiness

- **Date:** 2026-09-11
- **Status:** Complete.
- **Boundary:** Inference endpoint, model alias, runtime mode, timeouts, and
  optional bearer auth are configuration-only. Remote mode does not require a
  local model file or start llama.cpp.
- **Validation:** Deterministic configuration/provider tests only; no model
  endpoint or inference request is used.
- **Migration:** None expected; Alembic head remains `014_customer_ai_conversations`.

## Task 015F-9 - Hierarchical Intent Classification and Slot Extraction

- **Date:** 2026-09-11
- **Status:** Complete; not ready for unrestricted human typed testing.
- **Boundary:** A constrained classifier selects a capability before a second,
  intent-specific constrained slot extraction. The compiler remains the only
  component that resolves IDs and invokes existing customer tools.
- **Real validation:** Four sequential local-4B messages confirmed constrained
  Stage A/Stage B operation but exposed classifier reliability limits. The 4B
  misclassified search, cart add, and casual messages as menu overview or
  orders, so no unsafe mutation occurred. It correctly ran a Stage B schema
  for one misclassified menu search. No further model requests were sent.
- **Migration:** None expected; Alembic head remains `014_customer_ai_conversations`.

## Task 015F-8 - Schema-Reliable Customer Intent Planning

- **Date:** 2026-09-11
- **Status:** Complete; not ready for unrestricted human typed testing.
- **Boundary:** Customer plans use compact provider-constrained JSON where
  accepted, then an explicit field allowlist and strict semantic validation.
  Unknown model fields are diagnostic names only and cannot influence tools.
- **Real validation:** Four sequential local-4B messages confirmed llama.cpp
  JSON-schema formatting. It removed the former unknown fields. Menu overview
  and casual plans remained correct. The model still supplied a full phrase as
  `text_query` for menu search and omitted `dish_query` for cart add, so the
  backend returned grounded no-match/safe validation responses without a cart
  mutation. No further model requests were sent.
- **Migration:** None expected; Alembic head remains `014_customer_ai_conversations`.

## Task 015F-7 - Typed Customer Intent Planning and Backend Tool Compilation

- **Date:** 2026-09-11
- **Status:** Complete; not ready for unrestricted human typed testing.
- **Boundary:** Customer messages are interpreted as compact validated plans;
  the backend resolves entity names and compiles only approved existing tools.
  Tool results remain the sole factual source for grounded rendering.
- **Real validation:** Four sequential local-4B messages were run against the
  PostgreSQL E2E database. Casual chat and menu overview produced valid plans;
  menu overview executed `menu_get` and rendered authoritative data. The 4B
  emitted unsupported extra JSON fields for menu search and cart add on both
  bounded planner attempts, so validation safely rejected the plans before any
  factual tool execution or cart mutation. No further model requests were sent.
- **Migration:** None expected; Alembic head remains `014_customer_ai_conversations`.

## Task 015F-6 - Enforced Grounding and Deterministic Tool Rendering

- **Date:** 2026-09-11
- **Status:** Complete; not ready for unrestricted human typed testing.
- **Boundary:** Tool-routed customer turns require successful executor evidence,
  retry one declined tool call, and render backend results without a factual model
  continuation. Casual no-tool turns remain model-generated.
- **Search:** `menu_search` accepts `text_query` plus existing canonical filters
  while preserving the legacy `query` field.
- **Real validation:** Exactly four sequential local-4B turns used PostgreSQL E2E
  data. The full-menu request rendered authoritative results. Paneer and cart
  requests selected invalid model tool inputs and returned safe verification failures
  without invented facts or cart mutation. A casual greeting was over-routed to menu
  lookup but remained evidence-backed. No further real requests were sent.
- **Migration:** None; Alembic head remains `014_customer_ai_conversations`.

## Task 001 — Project Foundation

- **Date:** 2026-09-09
- **Status:** Complete
- **Summary:** Created the FastAPI, settings, async SQLAlchemy, Alembic,
  PostgreSQL Docker, logging, exception, documentation, and health-test
  foundation.
- **Files created:** See the project tree and `README.md`.
- **Validation:** Commands for the targeted health test, Ruff, and mypy were
  attempted. They could not run because the workspace Python environment has
  none of the project dependencies installed. Installation was attempted but
  the available Python 3.10 environment does not satisfy the project's Python
  3.11+ requirement.
- **Blockers:** Install dependencies with Python 3.11+ before running the
  application checks.

## Task 001A — Environment and Foundation Validation

- **Date:** 2026-09-09
- **Status:** Blocked by missing Python 3.12 installation
- **Python discovery:** `py -0p` listed 3.13, 3.12, 3.11, and 3.10, but
  the registered 3.11-3.13 executable paths do not exist. `where.exe python`
  found Python 3.10 and the WindowsApps alias; `python --version` reported
  Python 3.10.0.
- **Environment result:** A project `.venv` could not be created because the
  Python 3.12 launcher entry points to a missing executable.
- **Dependency installation:** Not attempted in a virtual environment because
  Python 3.12 is unavailable. No global installation was performed.
- **Validation:** pytest, Ruff, mypy, compileall, FastAPI import, health test,
  and Alembic validation could not be run under the required `.venv`.
- **Blocker:** Install Python 3.12 and ensure `py -3.12` resolves to an
  existing executable, then rerun Task 001A.

## Task 001B — Python 3.12 Environment and Foundation Validation

- **Date:** 2026-09-09
- **Status:** Complete
- **Python version:** Python 3.12.10
- **Environment:** Created `.venv` explicitly with `py -3.12`.
- **Dependency installation:** Upgraded pip, setuptools, and wheel, then
  installed the project and development dependencies with editable install.
- **Validation:** pytest passed (1 test); Ruff check passed; Ruff format check
  passed; mypy passed with no issues in 21 source files; compileall passed;
  FastAPI import passed; `/health` passed through pytest; SQLAlchemy engine,
  session factory, and metadata imports passed; Alembic configuration and
  metadata validation passed.
- **Settings/security:** Settings loaded without `.env`; `.env` is absent and
  ignored; `.env.example` exists.
- **Files changed:** `pyproject.toml`, `README.md`, and this task log.
- **Blockers:** None.

## Task 002C — Outlet Food & Dietary Policy Extension

- **Date:** 2026-09-09
- **Status:** Complete
- **Summary:** Added a one-to-one `OutletFoodPolicy` with explicit
  unknown-first halal, certification, pork, and alcohol enums. Writes require
  owner confirmation and are exposed through versioned outlet food-policy
  read/write endpoints. The policy is intentionally optional for onboarding
  readiness.
- **Migration:** `003_outlet_food_policy.py` (the Task 002 migration was not
  modified).
- **Validation:** Focused onboarding and food-policy tests passed before Task
  003. The final full suite passed (12 tests), with Ruff check/format, mypy,
  compileall, app/OpenAPI import, SQLAlchemy metadata, and Alembic chain
  checks all passing.

## Task 003 — Menu Catalog Foundation

- **Date:** 2026-09-09
- **Status:** Complete
- **Summary:** Added draft-first menus, categories, restaurant-owned cuisines
  and ingredients, dishes, variants, Decimal prices, ingredient links,
  controlled dietary/allergen/halal/spice values, provenance/review fields,
  image metadata and approval, modifier groups/options, and controlled badges.
  Replacement operations validate ownership before atomic replacement and
  publishing has explicit validation.
- **Scope guard:** No import/OCR/AI/upload bytes, availability, ordering,
  billing, Today's Special, Featured, Bestseller, or Offers behavior was added.
- **Migration:** `004_menu_catalog.py` follows `003_outlet_food_policy.py`;
  prior migrations were not modified.
- **Validation:** Full pytest, Ruff check/format, mypy, compileall, app/OpenAPI
  import, SQLAlchemy metadata, and Alembic history/head checks passed.

## Task 002 — Restaurant Onboarding Foundation (audit and repair)

- **Date:** 2026-09-09
- **Status:** Complete
- **Summary:** Audited and repaired the Task 002 implementation. Added typed
  status/onboarding enums, normalized unique slugs, outlet CRUD with a
  database-backed primary-outlet invariant, zoneinfo/country normalization,
  atomic schedule replacement, complete tax-profile fields and explicit
  confirmation, structured readiness requirements, and versioned `/api/v1`
  endpoints. Finalization now requires `{ "confirm": true }`.
- **Scope guard:** Menu, ordering, AI, billing calculations, auth, and Task 003
  remain unimplemented.
- **SQLite strategy:** Onboarding tests use an in-memory SQLite database with
  `aiosqlite`; PostgreSQL remains the production database and asyncpg remains
  the production driver.
- **Validation:** Ten tests passed, including health, slug collision, primary
  outlet switching, timezone rejection, schedule edge cases, tax validation,
  explicit finalization, atomic schedule replacement, and no-auto-tax-rate
  behavior. Ruff check and format check, mypy, compileall, FastAPI
  import/OpenAPI checks, SQLAlchemy metadata import, and Alembic checks passed
  using `.venv\\Scripts\\python.exe`.
- **Follow-up correction:** Finalization now sets the approved
  `ready_for_menu` onboarding status, and nullable tax rates are accepted when
  no tax rate has been explicitly configured.

## Task 002C/003 — Compliance Audit and Validation

- **Date:** 2026-09-09
- **Status:** Complete
- **Summary:** Audited the food-policy and menu-catalog implementation against the
  complete approved behavior matrix. Added migrations `005_catalog_compliance`
  and `006_food_policy_semantics` without changing prior migration history.
  The audit also corrected outlet menu listing so an outlet cannot receive
  another outlet's menus.
- **Validation:** 13 tests passed; Ruff check and format check passed; mypy
  passed with no issues in 32 source files; compileall passed; FastAPI/OpenAPI
  and SQLAlchemy metadata imports passed; Alembic head and offline SQL rendering
  passed through `006_food_policy_semantics`.
- **Warnings:** Test execution reports existing Starlette/httpx and anyio
  deprecation warnings. A live Alembic database check was not run because no
  PostgreSQL service/credentials were available; offline migration validation
  passed.
- **Scope guard:** No availability, ordering, billing, AI, OCR, speech,
  WhatsApp, frontend, upload-byte, import, offer, payment, authentication, or
  Task 004 work was started.

## Task 004 - Real-Time Availability Engine

- **Date:** 2026-09-10
- **Status:** Complete
- **Summary:** Added deterministic real-time availability without changing
  catalog lifecycle. `Dish.is_active` and menu publication remain catalog
  concepts; effective availability is derived from active dish and required
  ingredient blockers.
- **Models:** Added `AvailabilityProposal`,
  `AvailabilityProposalAffectedDish`, `DishAvailabilityOverride`, and
  `IngredientAvailabilityOverride`.
- **Service design:** Proposal creation validates outlet ownership, computes
  affected dishes, stores a relational affected-dish snapshot, and does not
  mutate availability. Confirmation is explicit and transactionally creates or
  revokes override rows. Reads derive active blockers from non-revoked,
  non-expired rows.
- **APIs:** Added proposal create/read/confirm/cancel, dish availability,
  ingredient availability, and outlet availability endpoints under `/api/v1`.
- **Migration:** Added `007_real_time_availability.py` after
  `006_food_policy_semantics`; prior migrations were not modified.
- **Time edge cases:** Covered split shifts, between-shift closed time, evening
  service to next day, overnight intervals, closed days, Sunday/Monday boundary,
  IANA timezone conversion, custom timestamp expiry, indefinite expiry, and
  continuous 24/7 rejection for next-opening mode.
- **Tests:** Added service/API tests for proposal preview without mutation,
  explicit confirmation, direct dish blocking/restoring, ingredient blocking,
  optional ingredient non-blocking, pending dish review non-blocking, no name
  inference, multiple blockers, stale proposal protection, proposal expiry,
  cancellation, double-confirm idempotency, outlet availability, and automatic
  expiry without cleanup.
- **Issue found and fixed:** The current shell exposed `DEBUG=release`, which
  caused settings import to fail before tests could collect. `Settings.debug`
  now narrowly normalizes `release`, `prod`, and `production` to `False`.
- **Validation:** Full suite passed with 28 tests. Ruff check, Ruff format
  check, mypy, and compileall passed. FastAPI/OpenAPI import, SQLAlchemy
  metadata import, Alembic heads/history/offline SQL, and Task 004 migration
  import validation passed.
- **Warnings:** Existing Starlette/httpx and anyio deprecation warnings remain.
  Pytest cache writes are denied in this workspace but do not affect test
  results. Live PostgreSQL migration validation was not performed because no
  clearly local disposable PostgreSQL database was verified.
- **Scope guard:** No Today's Special, Featured, Offers, menu import, AI, voice,
  WhatsApp, cart/order/kitchen/billing, auth, realtime transport/WebSocket, or
  frontend work was started.

## Task 005 - Today's Special / Featured / Offers Engine

- **Date:** 2026-09-10
- **Status:** Complete
- **Summary:** Added a merchandising module for Today's Special, Featured Dish,
  and deterministic Offers without introducing AI, ordering, billing, or
  frontend behavior.
- **Models:** Added `TodaysSpecial`, `FeaturedDish`, `Offer`,
  `OfferDishScope`, `OfferCategoryScope`, and `OfferComboItem`.
- **API:** Added special create/list/effective/read/patch/activate/deactivate,
  featured create/list/effective/read/patch/activate/deactivate, offer
  create/list/effective/read/patch/scope/combo/activate/pause/deactivate, and
  offer preview endpoints.
- **Schedule semantics:** Specials support until-service-end and timestamp
  windows. Featured and offers use aware schedules. Effective state is derived
  from lifecycle plus time, with no scheduler required.
- **Price precedence:** Preview resolves catalog/variant price, applies active
  special price for the exact dish/variant, then evaluates one selected offer.
  Tax, GST, final invoice, best-offer selection, and stacking remain out of
  scope.
- **Offer evaluator:** Supports percentage, flat, selected dish/category scope,
  threshold guidance, maximum percentage cap, flat discount floor, and combo
  fixed-price bundle counting.
- **Migration:** Added `008_merchandising_and_offers.py` after
  `007_real_time_availability`; earlier migrations were not modified.
- **Tests:** Added deterministic tests for Urban Tadka specials, service-end
  boundaries, special price non-mutation, duplicate overlap, featured
  independence, percentage/flat offers, category/dish scope, combo preview,
  special-price precedence, availability reporting, pending/draft catalog
  rejection, active-offer immutability, and absence of manual Bestseller
  endpoints/models.
- **Issues discovered:** Activation and scope replacement needed explicit row
  refreshes after commit so server-updated timestamps were safe in async reads.
  Added refreshes and regression coverage.
- **Validation:** Full suite passed with 39 tests. Ruff check, mypy, compileall,
  FastAPI/OpenAPI, SQLAlchemy metadata, Alembic head/history/offline SQL, and
  Task 005 migration import validation passed.
- **Warnings:** Existing Starlette/httpx and anyio deprecation warnings remain.
  Pytest cache writes are denied in this workspace but do not affect test
  results. Live PostgreSQL migration validation was not performed because no
  clearly local disposable PostgreSQL database was verified.
- **Scope guard:** No menu image/PDF ingestion, OCR/VLM, AI, voice, WhatsApp,
  table/QR, cart/order/kitchen/billing, payments, analytics, auth, frontend,
  manual Bestseller, offer stacking, or automatic best-offer selection was
  started.

## Task 006 - Customer Digital Menu Read Model

- **Date:** 2026-09-10
- **Status:** Complete
- **Summary:** Added a read-only customer menu module that composes published
  catalog, availability, Today's Special, Featured Dish, Offers, images,
  modifiers, ingredients, cuisines, dietary/allergen metadata, tax-inclusion
  metadata, food policy, and currency for future frontend/AI/terminal clients.
- **API:** Added `GET /api/v1/outlets/{outlet_id}/customer-menu`,
  `GET /api/v1/outlets/{outlet_id}/customer-menu/dishes/{dish_id}`, and
  `GET /api/v1/outlets/{outlet_id}/customer-menu/search`.
- **Visibility:** Only active restaurants, active outlets, published menus,
  active categories, active confirmed dishes, active variants, approved exact
  images, active modifiers/options, and effective promotions are exposed.
- **Availability:** Temporarily unavailable dishes remain visible as sold out;
  internal reason notes are not leaked.
- **Pricing:** Catalog/variant price remains authoritative, effective Today's
  Special price overlays it when applicable, offers are returned separately, and
  no tax/order/cart totals are calculated.
- **Currency:** Added configurable outlet `currency_code` with migration
  `009_customer_menu_currency`; customer APIs return ISO-style currency codes
  plus Decimal prices, not symbols.
- **UNKNOWN safety:** UNKNOWN dietary, vegan, Jain, halal, spice, and allergen
  values remain explicit and filters match only explicit requested values.
- **Food policy:** Confirmed outlet food policy is exposed as customer-safe
  owner declaration only; certification claim is separate from halal
  declaration and not platform verification.
- **Performance:** Customer menu reads batch related menu state and include a
  query-count regression test for a synthetic multi-dish menu to avoid obvious
  N+1 behavior.
- **Tests:** Added customer-menu tests covering public visibility, ordering,
  prices, variant specials, availability, safe notes, special/featured
  separation, dietary UNKNOWN safety, filters, search, images, modifiers,
  ingredients, allergens, food policy, offers, no mutation, wrong-outlet
  protection, and bulk-read query count.
- **Scope guard:** No table/QR sessions, cart, ordering, kitchen, billing,
  payments, PDF/image import, AI, voice, WhatsApp, realtime transport, auth, or
  frontend work was started.

## Task 007 - Table / QR / Dining Session Foundation

- **Date:** 2026-09-10
- **Status:** Complete
- **Summary:** Added physical outlet tables, stable opaque QR locators, QR
  resolution, and temporary dining sessions without adding cart, order,
  kitchen, billing, payment, AI, voice, WhatsApp, frontend, or React templates.
- **Models:** Added `RestaurantTable` and `DiningSession`.
- **Table invariants:** Table labels are preserved for display and normalized
  for active-label uniqueness per outlet. Capacity is nullable but positive
  when supplied. `is_active` means the physical table is configured/usable, not
  occupied.
- **Occupancy:** Derived from an open `DiningSession`; no stored
  `is_occupied` flag was added.
- **QR behavior:** Each table receives a globally unique high-entropy
  `public_qr_code` generated with `secrets`. QR codes are stable across menu,
  pricing, offers, branding, and frontend-template changes. Explicit
  confirmation is required for rotation; old rotated codes stop resolving.
- **Session lifecycle:** Dining sessions are `open` or `closed`, have opaque
  public session tokens, optional party size, and `qr` or `manual` start source.
  Close is explicit and idempotent; closed sessions remain history and are not
  reopened.
- **Concurrency strategy:** Service logic checks for an existing open session
  and the database enforces one open session per table using a partial unique
  index. Session token and QR code uniqueness are also database-backed.
- **API:** Added table CRUD-without-delete, QR resolution, QR session start/join,
  manual table session start, dining-session read, active-session read, QR
  rotation, and session close endpoints.
- **Customer menu integration:** QR/session responses return the Task 006
  customer-menu route and availability flag. Dining sessions do not snapshot or
  duplicate menu serialization.
- **Template boundary:** No table, QR, or session schema includes React
  template ID, frontend route, theme, color, or component metadata. Future
  templates remain presentation-only.
- **Migration:** Added `010_tables_and_dining_sessions.py` after
  `009_customer_menu_currency`; earlier migrations were not modified.
- **Tests:** Added coverage for table creation, label normalization,
  duplicate-label rules, QR opacity/resolution/rotation, inactive eligibility,
  QR and manual sessions, join-existing behavior, close/new-party flow, one-open
  DB invariant, token uniqueness, Task 006 menu availability integration,
  deactivation safety, template-agnostic schema checks, and table-list
  query-count performance.
- **Issues discovered:** SQLite returns timezone columns as naive datetimes in
  tests, so dining-session API reads normalize timestamps to UTC. Intentional
  rollback tests can expire ORM fixtures in async sessions, so tests capture IDs
  before triggering integrity failures.
- **Warnings:** Management endpoints remain unauthenticated development-stage
  APIs. QR possession is not identity authentication. Rate limiting and abuse
  protection are future work. Live PostgreSQL migration validation was not run;
  offline Alembic validation passed.
- **Scope guard:** No persistent cart, order/order items, kitchen/KDS,
  billing/invoice, payment, menu PDF/image import, OCR/VLM, AI, Talk-to-Menu,
  voice, WhatsApp, frontend, or React template work was started.

## Task 008 - Shared Cart / Multi-Round Ordering Foundation

- **Date:** 2026-09-10
- **Status:** Complete
- **Summary:** Added a shared dining-session cart and submitted dining-order
  rounds without adding kitchen execution, billing, payment, AI, voice,
  WhatsApp, frontend, or auth behavior.
- **Models:** Added `DiningCart`, `CartItem`, `CartItemModifier`,
  `DiningOrder`, `DiningOrderItem`, and `DiningOrderItemModifier`.
- **Cart behavior:** One shared cart is lazily created per dining session.
  Mutations require an open session, support optional expected-version checks,
  preserve separate line configurations, trim customer notes, and maintain live
  pricing and availability on reads.
- **Pricing:** Cart pricing resolves catalog dish/variant price, active
  Today's Special price, modifier deltas, quantity totals, and one explicitly
  selected offer. No automatic best-offer selection, stacking, tax, GST, final
  bill, invoice, or payment math was added.
- **Submission:** `confirm=true` and a current quote token are required.
  Submission revalidates availability and quote freshness, snapshots item,
  modifier, price, selected-offer, and tax-category metadata, clears the cart,
  and creates deterministic multi-round submitted order history.
- **Idempotency:** Per-session idempotency keys return the original submitted
  order and do not create duplicate rounds.
- **Dining interaction:** Dining sessions with nonempty carts cannot be closed.
  Empty carts and submitted order history do not block session close.
- **API:** Added cart read, item add/patch/remove, offer select/remove, cart
  submit, and order-history endpoints under `/api/v1/dining-sessions/...`.
- **Migration:** Added `011_cart_and_multi_round_orders.py` after
  `010_tables_and_dining_sessions`; earlier migrations were not modified.
- **Tests:** Added Task 008 coverage for shared cart versioning, modifier
  bounds, variants, customer-visible dish validation, special-price repricing,
  stale quote rejection, availability blocking without cart deletion, selected
  offers, submission snapshots, idempotency, multi-round ordering, and session
  close behavior.
- **Issue discovered:** SQLAlchemy's async identity map could reuse a stale
  loaded `cart.items` collection after cart mutations. Cart reads now force
  `populate_existing=True` so shared cart state is freshly evaluated.
- **Validation:** Full suite passed with 53 tests. Ruff check, Ruff format
  check, mypy, compileall, FastAPI import, SQLAlchemy metadata import, and
  Alembic offline SQL rendering through `011_cart_and_multi_round_orders`
  passed using `.venv\\Scripts\\python.exe`.
- **Warnings:** Existing Starlette/httpx and anyio deprecation warnings remain.
  Pytest cache writes are denied in this workspace but do not affect test
  results. Live PostgreSQL migration validation was not performed because no
  clearly local disposable PostgreSQL database was verified.
- **Scope guard:** No kitchen/KDS/KOT, cooking state, billing/invoice/GST final
  calculations, payments, menu PDF/image import, OCR/VLM, AI, Talk-to-Menu,
  owner natural-language commands, multilingual AI, voice, WhatsApp, frontend,
  React templates, or auth work was started.

## Task 009 - Kitchen / KOT / Order Execution Foundation

- **Date:** 2026-09-10
- **Status:** Complete
- **Summary:** Added a kitchen execution module that creates and manages KOTs
  for submitted dining-order rounds without adding billing, payment, AI,
  frontend, auth, stations, printers, inventory, or cancellation behavior.
- **Models:** Added `KitchenTicket` and `KitchenTicketItem`, with unique
  constraints from `DiningOrder` to ticket and from `DiningOrderItem` to ticket
  item. Added explicit kitchen ticket/item enums and extended
  `DiningOrderStatus` with execution summary states.
- **Automatic KOT creation:** `CartService.submit_cart` now creates the
  `DiningOrder`, order items, `KitchenTicket`, ticket items, and cart clearing
  in one transaction. Forced KOT creation failure rolls back the order and
  leaves the cart intact.
- **Item state machine:** Kitchen items support monotonic queued, preparing,
  ready, and served transitions. Queued-to-ready is allowed for quick items.
  Backward transitions are rejected and same-state retries are idempotent
  without timestamp rewrites.
- **Aggregate state machine:** A centralized synchronization function derives
  ticket status and `DiningOrder.status` from item states in the same mutation.
  All queued means queued/submitted, mixed work means in progress/in
  preparation, all ready-or-served with at least one ready means ready, and all
  served means served.
- **Session integration:** Dining sessions cannot close with a nonempty cart or
  any unserved order round. Served orders do not close the session
  automatically, and customers may submit later rounds while the session remains
  open.
- **APIs:** Added outlet kitchen queue, ticket detail, ticket-level
  start/ready/serve, and item-level start/ready/serve endpoints. No generic
  arbitrary order-status patch endpoint was added.
- **Migration:** Added `012_kitchen_order_execution.py` after
  `011_cart_and_multi_round_orders`; earlier migrations were not modified.
- **Tests:** Added coverage for automatic KOT creation, one-to-one constraints,
  snapshots, idempotency, rollback safety, availability-after-submission,
  item/bulk transitions, aggregate status, session-close blocking, queue
  outlet isolation/filtering/read safety, no cancellation/status-patch routes,
  and queue eager-loading performance.
- **Issues discovered:** KOT route presence tests initially checked app routes
  directly, but FastAPI exposes included paths reliably through OpenAPI. Session
  close tests also needed to identify second-round tickets by order ID rather
  than relying on same-second SQLite timestamp ordering.
- **Validation:** Focused Task 009 tests passed with 6 tests. Full suite passed
  with 59 tests before documentation edits. Ruff check and mypy passed before
  docs were updated; final quality-gate results are recorded in the task close
  response.
- **Warnings:** Kitchen mutation endpoints remain unauthenticated
  development-stage APIs and are not production-safe without staff
  authorization. Partial-quantity readiness within one order line, stations,
  printers, inventory deduction, cancellation, billing, tax/final invoice,
  payment, realtime push, menu ingestion, AI, voice, frontend, and React
  templates remain out of scope. Live PostgreSQL migration validation was not
  performed unless separately recorded.

## Task 010 - Billing / Tax / Invoice Foundation

- **Date:** 2026-09-10
- **Status:** Complete
- **Summary:** Added deterministic bill preview and finalized invoice support
  for dining sessions using submitted order snapshots as the billing truth.
  Preview remains read-only and can run before orders are served; finalization
  requires explicit confirmation, a current billing quote token, complete
  explicit outlet tax configuration, an empty cart, all orders served, and no
  existing invoice.
- **Models:** Added `DiningInvoice`, `DiningInvoiceOrder`,
  `DiningInvoiceLine`, and `DiningInvoiceLineModifier`, with one finalized
  invoice per dining session and immutable restaurant/outlet/tax/order-line
  snapshots.
- **Tax behavior:** Uses only the owner-configured outlet total tax rate and
  `prices_include_tax` flag. No statutory inference, per-dish legal category
  inference, CGST/SGST/IGST split, service charge, tip, payment, refund, or
  cancellation behavior was added.
- **Quote/idempotency:** Billing quote tokens change when order, cart,
  execution, or explicit tax state changes. Successful finalization is
  idempotent by per-session idempotency key and duplicate invoice creation is
  database-constrained.
- **Session/order integration:** Finalized invoices lock further cart writes
  and order submission while leaving cart reads safe. Dining sessions with
  served orders now require a finalized invoice before close; zero-order
  sessions may still close without one.
- **API:** Added bill preview, invoice finalize, session invoice read, and
  invoice read endpoints under `/api/v1`.
- **Migration:** Added `013_billing_tax_invoice.py` after
  `012_kitchen_order_execution`; earlier migrations were not modified.
- **Tests:** Added Task 010 coverage for exclusive/inclusive/zero-rate tax,
  incomplete tax config, active-order/cart blockers, stale quote protection,
  finalization confirmation, idempotency, immutable snapshots, ordering locks,
  session close integration, rollback safety, route presence, and preview
  query-count regression.
- **Scope guard:** No payment, UPI, refund, cancellation/credit note, split
  billing, service-charge automation, statutory tax lookup/inference, AI,
  OCR/VLM, speech, WhatsApp, analytics, frontend, React templates, auth, or
  Task 011 work was started.

## Task 011 - AI Tool Layer Foundation

- **Date:** 2026-09-10
- **Status:** Complete
- **Summary:** Added an internal provider-neutral AI tool layer without
  connecting a model, adding public chat endpoints, or creating persistence.
  Future LLMs will interpret language, but registered tools call deterministic
  backend services and the database remains authoritative.
- **Provider abstraction:** Added a minimal `ToolCallingModelProvider` protocol
  and project-owned message/tool-call/response schemas. No provider SDKs or
  agent frameworks were added.
- **Context design:** Added server-injected `AIToolContext` with actor type,
  outlet scope, optional dining-session token, optional restaurant scope, and
  request ID. Tool payloads do not accept tenant/session override fields when
  context provides them.
- **Registry/executor:** Added explicit allowlist registration, provider-neutral
  schema export, actor permission checks, Pydantic input validation,
  confirmation enforcement, safe result/error envelopes, and internal error
  sanitization.
- **Safety model:** Added read-only, reversible mutation, and consequential
  mutation levels. Consequential tools require external
  `ToolExecutionAuthorization.explicit_user_confirmation`; model payloads
  cannot self-confirm.
- **Customer tools:** Registered menu, search, dish detail, dish availability,
  effective offers, cart read/add/update/remove/select-offer/submit, session
  orders, and bill preview tools.
- **Owner tools:** Registered outlet availability read, availability proposal
  create/read, and confirmed availability proposal mutation tools.
- **Tests:** Added `tests/test_ai_tools.py` covering registry/schema export,
  actor isolation, context-bound outlet/session scope, extra-field rejection,
  customer flow, owner proposal/confirmation flow, external confirmation,
  unknown metadata preservation, safe availability results, read-only
  non-mutation, provider protocol, no public AI route, no new migration, and no
  LLM/agent dependencies.
- **Scope guard:** No Task 012 text model, Qwen, model download, external LLM
  API, LangChain/LlamaIndex, chat endpoint, conversation tables, vector search,
  recommendation AI, OCR/VLM, voice, WhatsApp, frontend, React templates, auth,
  or AI audit database was added.

## Task 012 - Customer Talk-to-Menu Text AI

- **Date:** 2026-09-10
- **Status:** Complete
- **Summary:** Added customer-facing text AI conversations for open dining
  sessions using the existing provider-neutral tool layer, local llama.cpp
  runtime, and pre-provisioned Qwen GGUF model path. The implementation keeps
  deterministic backend services authoritative for menu facts, availability,
  offers, cart mutations, submitted orders, and bill previews.
- **Local runtime:** Added `LlamaCppToolCallingProvider`, which calls
  llama.cpp's OpenAI-compatible chat-completions API at `LOCAL_LLM_BASE_URL`.
  It maps provider-neutral tool schemas into function tools, feeds tool results
  back as tool messages, parses tool calls, maps timeout/unavailable/parse
  failures to safe error codes, and strips visible `<think>...</think>` blocks.
- **Conversation persistence:** Added `ai_conversations`,
  `ai_conversation_messages`, and `ai_pending_tool_confirmations` through
  `014_customer_ai_conversations.py`. Persistence stores visible transcript,
  status/error metadata, and pending confirmation payloads only; no hidden
  reasoning or chain-of-thought columns were added.
- **Customer API:** Added conversation create/read, message send, and
  confirmation endpoints under `/api/v1`. Conversations are dining-session and
  outlet scoped. No owner AI routes were added.
- **Tool behavior:** Customer conversations expose only customer tool schemas.
  Added non-mutating `menu_quote_selection` so budget/selection claims can be
  verified with backend pricing without altering cart state.
- **Order confirmation:** Model-requested `cart_submit` creates a pending
  confirmation instead of submitting the order. The backend injects the live
  cart quote token and a server-generated idempotency key; successful external
  confirmation executes the persisted validated payload exactly once.
- **Scripts:** Added local startup/check/demo scripts for the pre-provisioned
  local llama.cpp runtime and Qwen model. No dependency install or model
  download command was added.
- **Tests:** Added `tests/test_customer_ai_conversation.py` covering visible
  transcript persistence, idempotent client message replay, customer tool-loop
  handoff, owner-tool blocking, pending confirmation, confirm/cancel/expiry,
  no duplicate order/KOT creation, loop-limit failure, non-mutating selection
  quote with variant/modifier pricing, adapter request/parsing behavior,
  reasoning stripping, provider error propagation, route scope, and absence of
  hidden reasoning columns.
- **Scope guard:** No Task 013 work, no speech, OCR/VLM, WhatsApp, frontend,
  auth, payments, hosted LLM API, model download, embeddings, vector search,
  owner AI chat, LangChain/LlamaIndex, transformers, torch, vLLM, Ollama, or
  `llama-cpp-python` was added.

## Task 013 - Multilingual Customer Text AI

- **Date:** 2026-09-10
- **Status:** Complete
- **Summary:** Extended the existing Task 012 customer conversation prompt and
  customer tool guidance for English, Hindi (Devanagari), Hinglish, Gujarati,
  Gujlish, and normal code-switching. The existing local Qwen model performs
  interpretation only; the existing customer tool layer and deterministic
  backend services remain authoritative.
- **Safety:** Exact backend menu names and IDs remain identifiable. Canonical
  backend enums are reused, UNKNOWN remains UNKNOWN in every language, allergy
  uncertainty is not treated as safe, budget-fit claims require
  `menu_quote_selection`, cart changes need explicit mutation intent, and
  order submission remains an external confirmation endpoint action.
- **Unicode:** Existing visible-message persistence and the 2,000-character
  input limit remain in force. The development CLI explicitly configures
  UTF-8 streams where supported by the Windows console.
- **Migration:** None. Existing Unicode-capable message columns require no
  schema change; Alembic head remains `014_customer_ai_conversations`.
- **Scope guard:** No translation model/service, cloud fallback, model/runtime
  download, language-specific route/service, voice, owner conversational AI,
  WhatsApp, OCR/VLM, semantic/vector search, frontend, React templates,
  customer identity, or long-term memory was added.

## Task 013A - Sequential Multilingual Real-Model Validation

- **Date:** 2026-09-10
- **Status:** Complete with model-quality limitation recorded
- **Validation:** Ran one sequential provider/tool-schema smoke loop per
  language against the pre-provisioned local Qwen model. Each loop used a
  controlled read-only `menu_search` result, then returned the result to Qwen
  for a final customer-facing response. No live database was used.
- **Finding:** Tool selection, canonical filters, tool-result feedback,
  factual grounding, and no-visible-reasoning behavior completed for English,
  Hindi, Hinglish, Gujarati, and Gujlish. Hindi improved after a concise prompt
  clarification. The model continued to respond in English for Latin-script
  Hinglish/Gujlish in the final retry, so this is recorded as a local-model
  response-language quality limitation rather than hidden by a translator or
  language-specific implementation.
- **Code change:** Customer prompt now explicitly says not to default to
  English for non-English input and to retain Latin script for Latin-script
  Hindi/Gujarati. Deterministic tests cover the prompt requirement.
- **Migration:** None; Alembic head remains `014_customer_ai_conversations`.
- **Scope guard:** No model/runtime download, cloud fallback, translator,
  language classifier, voice, owner AI, OCR/VLM, frontend, or Task 014 work
  was added.

## Task 013B - Multilingual Response-Mode Enforcement

- **Date:** 2026-09-10
- **Status:** Complete with Hinglish model-quality limitation recorded
- **Design:** Added a small presentation-only response-mode resolver for
  English, Hindi, Hinglish, Gujarati, and Gujlish. It uses explicit language
  requests first, Gujarati/Devanagari script detection next, then transparent
  narrow Latin-script lexical evidence. It does not affect customer tools,
  canonical enums, IDs, prices, availability, cart behavior, or tenant scope.
- **Steering:** The resolved server-controlled instruction is appended to the
  provider system message before the initial generation and retained for the
  post-tool-result final generation.
- **Validation:** Sequential controlled tool-schema smoke produced grounded
  English and Gujlish final responses. Gujlish was acceptable in Latin script.
  Hinglish continued to return Devanagari even after the bounded second attempt
  and explicit Latin-only instruction; this remains a local Qwen quality
  limitation, with no translator or second model added.
- **Test repair:** Made an existing expired-offer test fixture unambiguously
  expired to prevent live-clock flakiness.
- **Migration:** None; Alembic head remains `014_customer_ai_conversations`.
- **Scope guard:** No downloads, cloud fallback, translator, language-specific
  business service, voice, owner AI, OCR/VLM, frontend, or Task 014 work was
  added.

## Task 014 - Customer Voice / Speech-to-Text Foundation

- **Date:** 2026-09-10
- **Status:** Complete; human audio validation pending
- **Runtime:** Uses the pre-provisioned
  `D:\talkative menu\models\speech-to-text\whisper\ggml-large-v3-turbo-q5_0.bin`
  model and `D:\talkative menu\runtimes\whisper.cpp\Release\whisper-server.exe`.
  The development launcher binds the long-running server to `127.0.0.1:8082`
  with four threads, one processor, automatic language detection, and no
  timestamp output.
- **Provider/API:** Added provider-neutral speech-to-text types, a local
  whisper.cpp HTTP adapter, strict WAV validation, process-local single-request
  inference gate, and raw-WAV voice endpoint on the existing AI conversation.
  The transcript is passed to `CustomerAIConversationService`; no parallel
  voice orchestration, voice cart, or voice order path exists.
- **Privacy/safety:** V1 accepts only bounded 16-bit PCM WAV (mono/stereo,
  8-48 kHz, 30 seconds, 8 MB). Raw audio is neither stored nor logged; only the
  normal visible transcript is persisted. Voice reuses client-message
  idempotency before transcription when a completed message is replayed.
- **Scripts:** Added local STT launcher, readiness check, and WAV-to-FastAPI
  voice CLI. A dependency-free microphone helper was not added because it
  could not be physically validated in this environment.
- **Smoke:** whisper-server loaded the local model and answered a localhost
  readiness check. Synthetic Windows speech generation was unavailable because
  no local Windows voice is installed. No microphone test or database-backed
  voice-to-Qwen E2E test was performed.
- **Migration:** None; Alembic head remains `014_customer_ai_conversations`.
- **Scope guard:** No downloads, speech package, FFmpeg, cloud STT fallback,
  TTS, streaming, always-listening mode, owner voice, WhatsApp, frontend, or
  Task 015 work was added.

## Task 014A - Voice Transcript Preview + Human-Safe Send Flow

- **Date:** 2026-09-10
- **Status:** Complete; human preview-flow review pending
- **Preview boundary:** Added the conversation-scoped raw-WAV transcription
  endpoint. It requires a real existing conversation, reuses Task 014's WAV
  validator, local STT provider, and single-inference gate, then returns only
  `{transcript: {text, detected_language}}`. It does not call Qwen, customer
  tools, cart, order, KOT, billing, or message persistence.
- **Send flow:** The WAV CLI now previews `YOU SAID`, then requires explicit
  accept, edit, or discard. Only accepted or edited text is posted to the
  existing `/messages` endpoint. The Task 014 direct voice-message endpoint
  remains backward-compatible.
- **Human microphone evidence:** Direct local `whisper-stream.exe` testing
  succeeded with Microphone Array (Intel Smart Sound Technology for Digital
  Microphones), 16 kHz mono, `ggml-large-v3-turbo-q5_0.bin`, VAD step 0,
  10-second length, VAD threshold 0.2, four threads, and English. Spoken
  "Show me vegetarian dishes." produced that exact text once and "Show me the
  vegetarian dishes." once. No Hindi or Gujarati microphone result is claimed.
- **Migration:** None; Alembic head remains `014_customer_ai_conversations`.
- **Scope guard:** No downloads, packages, model/runtime changes, TTS,
  streaming, frontend recorder, audio persistence, or Task 015 work was added.

## Task 015E-1 - Real PostgreSQL Urban Tadka Seed

- **Date:** 2026-09-10
- **Status:** Complete; deterministic customer lifecycle validation pending.
- **Database:** The guarded seed runs only when `current_database()` is
  `ainza_restaurant_e2e`. It creates a fixture-owned Urban Tadka - Vesu outlet,
  six published categories, 15 explicit test dishes, operating intervals,
  T1/T2/T3, variants, modifiers, a confirmed availability proposal for Crispy
  Corn, special, featured item, and offer. Fixture cleanup is limited to the
  stable `urban-tadka-e2e` restaurant and its explicitly scoped availability
  proposal records.
- **Tax:** 5.00% is TEST FIXTURE TAX RATE - NOT LEGAL OR TAX ADVICE.
- **Validation:** The script completed twice consecutively against native
  PostgreSQL, including real customer-menu composition where Crispy Corn
  remained visible and unavailable.
- **Scope guard:** No cart/order/KOT/billing lifecycle, Qwen, Whisper, TTS,
  frontend, payment, downloads, or migrations were run.
