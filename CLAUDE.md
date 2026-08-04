# CLAUDE.md

This file is read automatically at the start of every session in this repo. Follow it exactly — the goal is a consistent codebase across sessions, not creative reinterpretation of the stack.

## What this project is

SmartReco: a behavioral AI recommendation platform for the SmartReco Build Challenge 2026 hackathon. Full spec: `docs/CHALLENGE.md`. Full architecture: `docs/ARCHITECTURE.md`. Read both before writing code in a new session.

## Stack (locked — do not swap these)

- Backend: FastAPI, async throughout
- DB: PostgreSQL via SQLAlchemy 2.0 (async) + Alembic migrations
- Vector DB: Chroma, `PersistentClient`, local persistent storage
- Cache/queue: Redis
- Agent: LangGraph
- LLM access: Mesh API ONLY — `from openai import OpenAI; OpenAI(base_url="https://api.meshapi.ai/v1", api_key=os.environ["MESH_API_KEY"])`. Every single LLM call in this codebase — including embeddings, not just chat completions — goes through `app/services/mesh_client.py` (`chat()` and `embed()`). Never instantiate an OpenAI/Anthropic client anywhere else in the code, and never let Chroma fall back to its own default local embedding function.
- Scheduler: APScheduler (in-process)
- Observability: LangSmith tracing + the `agent_runs` table
- Frontend: Jinja2 templates + vanilla JS (`static/js/tracker.js`) — no React/Vue
- Auth: bcrypt + JWT, `role` column on `users`

## Non-negotiable constraints

1. **Never call an LLM synchronously per tracked event.** LLM calls only happen inside the LangGraph `analyze_interest` and `generate_recommendation` nodes, and only after `should_trigger` passes.
2. **Every product write is dual-written via the outbox pattern**, not a direct best-effort double-call. See `docs/ARCHITECTURE.md` §3. Never write directly to Chroma from an API route handler.
3. **Event ingestion must never block.** `/api/events/batch` pushes to Redis and returns; it never writes to Postgres inline and never waits on the LLM.
4. **Recommendations must be grounded in retrieved product IDs only.** The generation prompt must constrain output to the retrieved set — and after generation, filter `product_ids` against the actual retrieved set server-side before persisting. Prompt instructions alone are not enforcement; the post-generation filter is what makes the grounding guarantee real.
5. **Cache before you call.** Check the interest-summary cache and the recommendation cache before invoking the LLM. Log every agent invocation to `agent_runs`, including cache hits.
6. **Secrets only via `.env`**, loaded through `app/config.py` (pydantic-settings). Never hardcode a key. `.env` must stay in `.gitignore`.
7. **One agent run per user at a time.** Acquire a short-TTL Redis lock (`agent_lock:{user_id}`) before invoking the LangGraph run and release it in `persist` (or on failure). Prevents concurrent requests from the same user triggering duplicate LLM calls.
8. **Reset the trigger signal after a run completes.** `persist` must clear/reset `pending_signal:{user_id}` after a successful generation, or the same events keep re-triggering runs past the threshold.

## Conventions

- All routes use Pydantic request/response models — no raw `dict` in/out.
- Admin routes depend on a `require_admin` dependency, not an inline role check.
- Migrations: every schema change gets an Alembic revision, never hand-edited tables.
- Tests live in `tests/`, mirroring `app/` structure.
- Follow the phased build order in `docs/ARCHITECTURE.md` §12 — don't build the agent before the outbox and event pipeline exist.

## Do not

- Do not add a second web framework, ORM, or vector DB "just to try."
- Do not call Mesh directly from route handlers — always through `mesh_client.py`.
- Do not skip the `agent_runs` log for a run because LangSmith is already tracing it — the DB table is the fallback judges can query without LangSmith access.
- Do not commit `.env` or any API key.
