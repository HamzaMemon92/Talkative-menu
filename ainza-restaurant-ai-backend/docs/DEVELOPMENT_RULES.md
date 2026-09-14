# Development rules

- Use Python typing and small understandable functions.
- Run Ruff, mypy, and pytest for relevant changes.
- Use Alembic migrations for schema changes.
- Never commit secrets or use fake production data.
- Use structured error handling and meaningful, non-sensitive logging.
- Keep legal, tax, and business rules explicitly configured.
- Never treat an LLM output as authoritative business state.
- Require human review for consequential changes.
- Keep catalog lifecycle separate from operational availability.
- Recheck authoritative availability before future order placement.
- Do not let AI or clients calculate discounts; use deterministic backend offer
  preview/evaluation.
- Do not add manually editable Bestseller state before order analytics exist.
- Future frontend, terminal, and AI clients must consume the customer menu read
  model rather than duplicating menu interpretation logic.
- Customer-facing availability must not leak owner/internal reason notes.
- Never turn UNKNOWN dietary, halal, spice, or allergen values into negative or
  safe customer claims.
- Derive table occupancy from open dining sessions; do not add independently
  mutable occupied flags.
- Treat table QR codes and dining-session tokens as opaque context locators, not
  authenticated user identity.
- Keep table, QR, and dining-session data independent of future frontend
  template or branding choices.
- Keep submitted dining orders immutable; kitchen execution must use order
  snapshots rather than current menu data.
- Create KOT records atomically with successful cart submission. Order success
  must imply a KOT exists.
- Advance kitchen item status only through explicit monotonic transitions and
  synchronize ticket/order aggregate status in the same operation.
- Do not close a dining session while its cart is nonempty or any order round is
  unserved.
- Do not let an LLM choose tenant/session scope, call raw SQL, receive a
  SQLAlchemy session, or calculate authoritative money, tax, availability,
  discounts, bills, or order state.
- AI tools must wrap deterministic backend services and preserve UNKNOWN
  dietary, halal, spice, Jain, vegan, and allergen metadata.
- Consequential AI tool execution must require external human confirmation;
  model-generated `confirm=true` is not authorization.
- Customer AI conversation storage must not persist hidden reasoning,
  chain-of-thought, or scratchpad text.
- Customer AI must expose only customer tools. Owner AI routes require explicit
  future approval after authentication exists.
- Do not let model output choose cart quote tokens or idempotency keys for
  order submission; server code must inject them.
- Local LLM integration must use pre-provisioned local runtime/model files only.
- Multilingual customer text must reuse the customer tool layer and canonical backend enums;
  do not add translation services, language-specific business paths, or natural-language
  consequential-action confirmation.
- Voice input must use an externally started local STT server, validate bounded WAV bytes,
  retain no raw audio, and pass only the transcript to the existing customer AI service.
  Do not add model downloads, hosted LLM SDKs, embeddings, vector stores,
  LangChain/LlamaIndex, transformers, torch, vLLM, Ollama, or
  `llama-cpp-python` without explicit approval.
- Do not add kitchen stations, printer integration, inventory deduction, order
  cancellation, payments, owner AI chat, voice, WhatsApp, auth, frontend, or
  React template coupling without explicit task approval.
