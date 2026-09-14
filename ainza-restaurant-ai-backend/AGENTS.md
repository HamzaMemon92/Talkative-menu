# Agent Instructions

1. Human instructions are the final authority.
2. Implement only the explicitly requested task.
3. Do not silently introduce product features.
4. Do not guess product, legal, tax, or restaurant requirements.
5. Never invent menu, pricing, availability, offer, or billing facts.
6. The database/backend is the source of truth.
7. Keep AI outputs non-authoritative for business state.
8. Consequential owner actions require human confirmation.
9. Use migrations for schema changes.
10. Never commit secrets or `.env` files.
11. Do not push to a remote without explicit instruction.
12. Do not disable tests or suppress real errors.
13. Keep the modular monolith understandable and testable.
14. Record completed work in `docs/TASK_LOG.md`.
