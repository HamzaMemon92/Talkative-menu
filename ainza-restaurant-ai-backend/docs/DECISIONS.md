# Architecture decisions

- **ADR-001:** Python + FastAPI for the backend.
- **ADR-002:** PostgreSQL is the primary database.
- **ADR-003:** SQLAlchemy 2 async APIs + Alembic manage persistence.
- **ADR-004:** Use a modular monolith in V1.
- **ADR-005:** The database is authoritative restaurant truth.
- **ADR-006:** Money calculations belong to deterministic code.
- **ADR-007:** Consequential AI actions require confirmation.
- **ADR-008:** Keep an abstraction boundary for AI providers.
- **ADR-009:** Do not introduce microservices in V1.
- **ADR-010:** Normal and AI ordering share the same menu data.
- **ADR-011:** Onboarding stores tax-profile confirmation but never auto-fills
  tax rates.
- **ADR-012:** Weekly operating intervals are validated as half-open ranges on
  a circular seven-day clock; touching intervals are allowed, overlaps are not.
- **ADR-013:** Task 002 stores restaurant `status` separately from
  `onboarding_status`; explicit finalization changes onboarding state to
  `ready_for_menu` only.
- **ADR-014:** Tax rates are nullable `NUMERIC(5,2)` values with no default and
  can only be considered configured after explicit owner confirmation.
- **ADR-015:** Catalog lifecycle and real-time availability are separate.
  `Dish.is_active` means the dish belongs in the catalog; operational
  unavailability is derived from active blocking override rows.
- **ADR-016:** Availability mutations require a proposal snapshot and explicit
  human confirmation. Proposal confirmation rechecks affected dishes and
  next-opening expiry to reject stale previews.
- **ADR-017:** Ingredient availability blocks dishes only through explicit
  required-for-availability links on confirmed or approved dishes. Optional
  links and dish-name inference never make a dish unavailable.
- **ADR-018:** Next-opening expiry uses outlet IANA time zones and weekly
  operating intervals, including split shifts, overnight intervals, closed
  days, and circular week boundaries. Continuous 24/7 schedules reject
  next-opening duration because there is no distinct boundary.
- **ADR-019:** Availability expiry is evaluated at read time. Background
  cleanup may archive old rows later, but availability correctness cannot
  depend on a scheduler.
- **ADR-020:** Restore actions revoke active override rows and preserve audit
  history. They do not guarantee availability when other active blockers remain.
- **ADR-021:** Today's Special, Featured Dish, Chef Recommended, Offers, and
  Bestseller are separate concepts. Bestseller remains calculated later from
  order data and is not manually editable.
- **ADR-022:** Merchandising references authoritative catalog entities instead
  of duplicating product data. Special prices and offers never mutate
  `Dish.base_price` or `DishVariant.price`.
- **ADR-023:** Merchandising and offers do not override Task 004 availability.
  Sold-out dishes remain unavailable even when special, featured, or discounted.
- **ADR-024:** Offer preview evaluates one specified offer using deterministic
  Decimal math. No offer stacking, automatic best-offer selection, tax, GST,
  invoice, cart, or order persistence is included in Task 005.
- **ADR-025:** Pricing precedence is catalog/variant price, then active
  Today's Special price, then the selected eligible offer. Future billing will
  apply tax after discounted subtotal.
- **ADR-026:** The customer digital menu is a read-only service-layer
  composition over authoritative catalog, availability, and merchandising state.
  It does not copy dishes into customer-menu tables and requires no
  synchronization job for correctness.
- **ADR-027:** Sold-out customer-visible dishes remain visible with safe
  availability state. Internal availability reason notes and operational causes
  are not exposed through the customer menu.
- **ADR-028:** Outlet currency is explicit data (`currency_code`) and customer
  APIs return currency codes plus Decimal prices, not formatted symbols.
- **ADR-029:** Customer search and filters are deterministic AND/substring
  operations over customer-visible confirmed data. AI ranking, embeddings, fuzzy
  LLM matching, offer stacking, and automatic best-offer selection are deferred.
- **ADR-030:** Physical tables, QR locators, and dining sessions are separate
  domain concepts. Table occupancy is derived from an open session; no
  authoritative `is_occupied` field is stored.
- **ADR-031:** Table QR codes are stable high-entropy public locators, not
  authentication credentials. Explicit rotation is available for exceptional
  administrative cases, and QR changes are never automatic side effects of menu,
  price, offer, branding, or template changes.
- **ADR-032:** Dining sessions keep context only and never snapshot the customer
  menu. Task 006 remains the authoritative current menu read model while future
  order items will snapshot monetary/order facts at order time.
- **ADR-033:** The dining schema is frontend-template agnostic. Future React
  templates are presentation configuration and must not require changing table,
  QR, session, menu, or business entity identifiers.
- **ADR-034:** One open dining session per table is enforced in service logic
  and with a database partial unique index. Multiple customer devices join the
  same open session rather than creating per-device sessions.
- **ADR-035:** A shared cart is live draft state; a submitted `DiningOrder` is
  immutable commercial history. New customer additions after submission create a
  later round rather than mutating an earlier submitted order.
- **ADR-036:** Every new successful `DiningOrder` submission creates exactly one
  `KitchenTicket` in the same transaction. Correctness does not depend on a
  background worker or a separate "send to kitchen" action.
- **ADR-037:** Kitchen execution uses submitted order snapshots for display.
  Current dish, variant, modifier, price, offer, special, or availability
  changes cannot rewrite accepted KOT history.
- **ADR-038:** Kitchen item transitions are monotonic and centralized in the
  kitchen service. Ticket and order aggregate status is derived from item states
  after each mutation to avoid drift.
- **ADR-039:** Dining sessions remain open after food is served until an
  explicit close action. Close is blocked by a nonempty cart or any unserved
  order round; billing may add further close rules later.
- **ADR-040:** Task 009 keeps one outlet-wide kitchen queue. Staff auth,
  stations, printer integration, inventory deduction, cancellation, realtime
  push, billing, payment, AI, voice, and frontend templates are deferred.
- **ADR-041:** Billing previews and finalized invoices use submitted order
  snapshots plus explicit outlet tax profile data. The backend does not infer
  statutory tax categories, split GST components, service charge, tips,
  payments, refunds, credit notes, or split bills in Task 010.
- **ADR-042:** The AI tool layer is provider-neutral internal infrastructure.
  Future model adapters consume project-owned Pydantic schemas rather than
  OpenAI/Anthropic/LangChain-specific definitions.
- **ADR-043:** AI tools are explicit allowlisted definitions with actor
  permissions, safety levels, server-bound context, and Pydantic input models
  using `extra="forbid"` for model-generated arguments.
- **ADR-044:** Consequential AI actions require external
  `ToolExecutionAuthorization`. Model-generated arguments cannot self-confirm
  cart submission or owner availability confirmation.
- **ADR-045:** AI tools wrap existing deterministic services. The LLM never
  receives raw SQL, SQLAlchemy session access, arbitrary code execution, or an
  authoritative money/tax/availability calculator.
- **ADR-046:** Customer text AI uses the local llama.cpp OpenAI-compatible
  server against the pre-provisioned Qwen GGUF model. The backend does not
  download model files, install model runtimes, or depend on provider SDKs.
- **ADR-047:** Conversation persistence stores visible transcript and
  confirmation metadata only. Hidden reasoning, chain-of-thought, scratchpads,
  and model-internal thinking are not persisted or returned.
- **ADR-048:** Customer AI conversations expose only customer tool schemas. A
  model request for owner tools is handled as a forbidden tool result and does
  not execute owner handlers.
- **ADR-049:** AI cart submission is a two-step pending confirmation flow. The
  server injects the current cart quote token and a server-generated
  idempotency key; final order creation requires the external confirmation
  endpoint.
- **ADR-050:** Customer multilingual text uses the same pre-provisioned local
  Qwen model and customer tools for English, Hindi, Hinglish, Gujarati,
  Gujlish, and code-switching. No translator, cloud fallback, separate API,
  language-specific enum, or second business-logic path is introduced.
- **ADR-051:** Customer voice is push-to-talk WAV-only input to a separately
  started localhost whisper.cpp server. Whisper transcribes but never
  translates or owns restaurant decisions; only the visible transcript enters
  the existing customer conversation. Raw audio is not persisted.
- **ADR-052:** Voice transcript preview is an explicit human decision boundary.
  It validates conversation scope and performs STT only; it cannot invoke the
  model, tools, cart, ordering, kitchen, billing, or persistence. Accepted or
  edited transcript text uses the existing customer message endpoint.
- **ADR-053:** Tool-backed customer facts require authoritative executor
  evidence. The LLM interprets intent and selects tools; deterministic backend
  services verify facts; `GroundedResponseRenderer` presents those results.
  A free-form continuation cannot override a tool result.
- **ADR-054:** Customer menu search accepts structured text plus canonical
  filters. The legacy `query` field remains supported, while `text_query` and
  existing enum filters separate dish concepts from dietary, availability,
  Jain, vegan, and spice constraints.
- **ADR-055:** Customer AI uses a typed semantic intent plan as the primary
  control plane. The LLM interprets language only; a deterministic compiler
  resolves authoritative entities and invokes existing allowlisted tools. Plans
  cannot carry internal IDs, prices, or confirmation authority.
- **ADR-056:** Direct model tool planning is retained temporarily only for
  injected provider compatibility and rollback. It may be removed after typed
  planning completes human typed, speech-to-text, and regression validation.
- **ADR-057:** Customer intent planning uses provider JSON-schema output where
  supported, followed by an explicit plan-field allowlist projection and strict
  intent-specific validation. Provider-constrained output improves reliability;
  projection and validation remain mandatory trust boundaries.
- **ADR-058:** Customer semantic planning is hierarchical: Stage A classifies
  intent and Stage B uses only the schema selected by that validated intent.
  This is a durable separation of intent recognition from slot extraction, not
  a model-specific workaround.
