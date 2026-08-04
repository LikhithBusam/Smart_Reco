# SmartReco

Behavioral AI recommendation platform for the SmartReco Build Challenge 2026.

**Status:** under active development, built in phases. See `docs/CHALLENGE.md` for the brief and `docs/ARCHITECTURE.md` for the full technical design (stack, data model, agent workflow, API surface).

## Progress

- [x] Phase 1 — Foundation: Docker Compose, FastAPI skeleton, SQLAlchemy models + Alembic, email/password auth (JWT via httpOnly cookie), role-guarded routes
- [x] Phase 2 — Product management + outbox: admin CRUD, `product_sync_outbox`, Chroma client (embeddings via Mesh API only), outbox worker
- [x] Phase 3 — Event tracking: `tracker.js`, `/api/events/batch`, Redis buffering, batch-flush consumer
- [ ] Phase 4 — Agent core (LangGraph)
- [ ] Phase 5 — Recommendations API + frontend
- [ ] Phase 6 — Bonuses (LangSmith, digest email, retrieval polish)
- [ ] Phase 7 — Hardening (full README, setup instructions, rate limiting)

A complete setup/run guide and architecture writeup will land here in Phase 7.
