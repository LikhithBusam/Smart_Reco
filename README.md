# SmartReco

A behavioral AI recommendation platform built for the SmartReco Build Challenge 2026. Users browse a course catalog; an agentic backend watches their activity, reasons about their interests, retrieves relevant courses from a vector store, and generates a personalized, persuasive recommendation — grounded strictly in the real catalog, never invented.

## What's actually in here

- **Behavioral tracking that doesn't slow the page down** — an in-memory client-side queue flushed in batches (20 events / 10s / tab-hide via `sendBeacon`), landing in Redis and never on the request's critical path.
- **A real outbox pattern**, not a hopeful double-write — every product write lands in Postgres and an outbox row in the same transaction; a background worker syncs Chroma from the outbox, with retries and a `failed` state after N attempts.
- **A LangGraph agent**, not a single prompt — `should_trigger → analyze_interest → retrieve → evaluate_retrieval → refine_query? → generate_recommendation → persist`, gated so most page loads cost zero LLM tokens.
- **Grounding enforced in code, not just prompted for** — `persist()` filters the model's `product_ids` against the actual retrieved set before writing anything. A hallucinated ID never reaches storage.
- **A concurrency lock** (Redis `SET NX`) so two requests for the same user can never trigger two LangGraph runs at once, and a **pending-signal reset** so the same events can't re-trigger a run past the threshold forever.

Full technical design, data model, and the reasoning behind each of the above: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Original hackathon brief: [`docs/CHALLENGE.md`](docs/CHALLENGE.md).

## Stack

| Layer | Choice |
|---|---|
| Backend | FastAPI (async) |
| Database | PostgreSQL, SQLAlchemy 2.0 async, Alembic migrations |
| Vector DB | Chroma (persistent, embeddings via Mesh API only — never Chroma's default embedder) |
| Cache / queue | Redis (event buffering, trigger counters, caches, locks, rate limiting) |
| Agent | LangGraph |
| LLM access | Mesh API only, via the OpenAI SDK — every call routes through `app/services/mesh_client.py` |
| Scheduler | APScheduler, one shared instance for every background job |
| Frontend | Jinja2 server-rendered templates + vanilla JS (no React/Vue) |
| Auth | Email/password, bcrypt, JWT in an httpOnly cookie |

## Bonus features implemented

- ⭐ **Structured agent framework** — the full LangGraph workflow above, not a single call.
- ⭐ **Scheduled proactive delivery** — a daily digest email job on APScheduler, reusing each user's existing active recommendation rather than forcing a regeneration (`app/services/digest.py`).
- ⭐ **Observability** — LangSmith tracing (env-driven, traces every node automatically) plus `GET /admin/agent-runs` so judges can see cache-hit efficiency without LangSmith access, straight from the DB.
- ⭐ **Retrieval polish** — metadata filtering: the agent infers a dominant product category from the user's recent activity and narrows the Chroma query to it, dropping the filter on refine to broaden the search instead.

## Setup & run

### 1. Configure environment

```bash
cp .env.example .env
```

Fill in `SECRET_KEY` (any long random string) and `MESH_API_KEY` (from the [Mesh dashboard](https://meshapi.ai), starts with `rsk_`). Everything else has a sane default for local dev.

### 2. Run with Docker Compose (recommended — one command)

```bash
docker compose up -d
```

This starts Postgres and Redis, then the API container runs `alembic upgrade head` and starts `uvicorn` with `--reload`. The app is at `http://localhost:8000`.

### 3. Or run locally without Docker

Needs a local PostgreSQL and Redis reachable at the URLs in `.env`.

```bash
python -m venv .venv
source .venv/bin/activate  # .venv\Scripts\activate on Windows
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

### 4. Try it

- `http://localhost:8000/register` → create an account → browse the catalog → the recommendation panel populates once the agent has enough signal (or after the TTL, whichever comes first).
- `http://localhost:8000/docs` → interactive Swagger UI, including the admin product CRUD endpoints. No separate admin UI was built for this — FastAPI's own docs already cover create/edit/delete, and building a second interface for the same thing would've been unrequested scope.
- Seed the catalog first via `POST /admin/products` (register a user, then manually flip their `role` to `admin` in the DB, or promote via `psql`/a DB client — there's no self-serve "become admin" flow by design).

## Running the tests

```bash
pytest
```

66 tests, all fast and fully mocked against fakeredis / mocked DB sessions / mocked Mesh calls — no live infrastructure required to run the suite. Covers: auth, dual-write outbox, event batching, the LangGraph agent (including the grounding filter, the concurrency lock, and retry/fail-closed behavior), the recommendations API, the digest job, the admin observability endpoint, rate limiting, and structured logging.

### Retrieval smoke test (needs a real Mesh key + network)

```bash
python scripts/retrieval_smoke_test.py
```

Seeds a throwaway Chroma collection with 8 known courses via **real** Mesh embedding calls, then checks that 8 known interest phrases retrieve the expected course in their top-3 — real evidence for the grounding/retrieval claim, not just prompt wording. This is intentionally kept out of the main `pytest` suite since it needs live network access and a real API key, neither of which CI has.

## API surface

```
POST   /auth/register
POST   /auth/login              (rate-limited)
POST   /auth/logout
GET    /auth/me

GET    /admin/products
POST   /admin/products
PUT    /admin/products/{id}
DELETE /admin/products/{id}
GET    /admin/agent-runs

POST   /api/events/batch        (rate-limited)
GET    /api/recommendations

GET    /            (product browsing + search + recommendation panel)
GET    /login
GET    /register
GET    /health
```

## Project structure

```
app/
├── main.py                # app assembly, static mount, structured logging
├── config.py               # env/settings + LangSmith env wiring
├── logging_config.py        # stdlib JSON log formatter
├── db/                      # models, session, Alembic migrations
├── api/                     # route handlers (auth, admin, products, events, recommendations, pages)
├── core/                    # security, auth deps, rate limiting
├── services/                # mesh_client, redis_client, outbox_worker, event_consumer, scheduler, digest
├── agent/                   # LangGraph state, nodes, graph
└── vector/                  # chroma_client
static/js/tracker.js         # behavioral event tracker
templates/                   # Jinja2 pages
scripts/retrieval_smoke_test.py
docs/                        # ARCHITECTURE.md, CHALLENGE.md
tests/                       # pytest suite
```

## Known limitations

- No live end-to-end run (Docker/Postgres/real Mesh key) has happened in the environment this was built in — every phase was verified as thoroughly as possible without that infrastructure (real Chroma persistence with stubbed embeddings, real Jinja2 rendering, real fakeredis, mocked DB sessions with correctness-checked assertions) but a first real run on your machine is still worth doing.
- No admin UI beyond FastAPI's `/docs` — a deliberate scope call, not an oversight.
- Rate limiting is a cheap fixed-window Redis counter (`INCR` + `EXPIRE`), not a precise sliding-window log — adequate for a hackathon abuse guard, not tuned for exact per-second limits.
