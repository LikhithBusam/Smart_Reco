# SmartReco — Enterprise Architecture

Behavioral AI recommendation platform. This document is the technical design of record — Claude Code should treat it as ground truth alongside `docs/CHALLENGE.md` (the original brief) and `CLAUDE.md` (working conventions).

---

## 1. Stack decisions (locked — do not deviate mid-build)

| Layer | Choice | Why |
|---|---|---|
| Backend | **FastAPI** (async) | Non-blocking event ingestion needs real async I/O; native Pydantic validation; pairs cleanly with SQLAlchemy 2.0 async and background tasks |
| Primary DB | **PostgreSQL** (SQLAlchemy 2.0 async + Alembic migrations) | JSONB for event metadata, concurrent writes, production-credible over SQLite |
| Vector DB | **Chroma** (persistent local client, `PersistentClient`) | Zero external service to stand up — critical for automated CI checks and judges running this in one command. Metadata filtering is sufficient for our retrieval needs. (Qdrant is the noted scale-out path — same interface pattern, swap the client.) Embeddings are generated via `mesh_client.embed()` (Mesh `/embeddings`), never Chroma's built-in default embedding function — every vector written or queried goes through the same Mesh path as chat completions. |
| Cache / queue | **Redis** | Event buffering before batch-flush to Postgres, LLM-output caching, trigger-counter state, and a short-TTL per-user lock (`agent_lock:{user_id}`) so concurrent requests never trigger two LangGraph runs for the same user |
| Agent framework | **LangGraph** | Explicit reasoning graph — bonus requirement, and it's the right tool for a retrieve→evaluate→refine loop |
| LLM access | **Mesh API only**, via OpenAI SDK, `base_url="https://api.meshapi.ai/v1"` | Mandatory per hackathon rules — every AI call, no exceptions (chat *and* embeddings), goes through one wrapper module (`mesh_client.py`: `chat()` + `embed()`) |
| Scheduler | **APScheduler** (in-process) | Lower ops than Celery Beat for a single-service hackathon deploy; still satisfies the "real scheduler, not a manual button" bonus requirement |
| Observability | **LangSmith** tracing on the LangGraph runs, plus a first-party `agent_runs` table | Judges can see both a dashboard and query the DB directly |
| Frontend | Jinja2 server-rendered templates + vanilla JS tracker | Matches required stack exactly; no framework overhead to justify |
| Auth | Email/password, bcrypt hash, JWT access token, `role` column (`user` / `admin`) | Simple per brief, but real hashing + real tokens, not session-in-memory |
| Local dev / judging | **Docker Compose** (api, postgres, redis) | One-command spin-up — this alone is a visible production-thinking signal |

---

## 2. Data model

```sql
-- users
id UUID PK
email TEXT UNIQUE NOT NULL
hashed_password TEXT NOT NULL
role TEXT NOT NULL DEFAULT 'user'      -- 'user' | 'admin'
created_at TIMESTAMPTZ DEFAULT now()

-- products
id UUID PK
title TEXT NOT NULL
description TEXT NOT NULL
category TEXT NOT NULL
price NUMERIC(10,2) NOT NULL
is_deleted BOOLEAN DEFAULT false
created_at TIMESTAMPTZ DEFAULT now()
updated_at TIMESTAMPTZ DEFAULT now()

-- product_sync_outbox   (drives the dual-write — see §3)
id UUID PK
product_id UUID FK -> products.id
operation TEXT NOT NULL                -- 'upsert' | 'delete'
status TEXT NOT NULL DEFAULT 'pending' -- 'pending' | 'done' | 'failed'
attempts INT DEFAULT 0
created_at TIMESTAMPTZ DEFAULT now()
processed_at TIMESTAMPTZ

-- events
id UUID PK
user_id UUID FK -> users.id
event_type TEXT NOT NULL               -- 'view' | 'search' | 'click' | 'time_on_page' ...
entity_type TEXT                       -- 'product' | 'category' | null
entity_id UUID
metadata JSONB
session_id TEXT
created_at TIMESTAMPTZ DEFAULT now()
-- index: (user_id, created_at DESC)

-- recommendations
id UUID PK
user_id UUID FK -> users.id
narrative TEXT NOT NULL
product_ids UUID[] NOT NULL
trigger_reason TEXT                    -- 'event_threshold' | 'time_ttl' | 'manual'
is_active BOOLEAN DEFAULT true
generated_at TIMESTAMPTZ DEFAULT now()
agent_run_id UUID FK -> agent_runs.id

-- agent_runs   (observability — judged criterion, don't skip this table even if LangSmith is also wired up)
id UUID PK
user_id UUID FK -> users.id
trigger_type TEXT
status TEXT                            -- 'cache_hit' | 'completed' | 'failed'
retry_count INT DEFAULT 0
token_usage INT
started_at TIMESTAMPTZ
completed_at TIMESTAMPTZ
```

---

## 3. Dual-write: PostgreSQL + vector DB (outbox pattern)

Naive dual-write (write SQL, then write vector, hope both succeed) drifts the moment one call fails mid-request. Use an **outbox**:

1. Admin creates/edits/deletes a product → single DB transaction writes the `products` row **and** a `product_sync_outbox` row (`status='pending'`) atomically.
2. Request returns immediately — the vector write is not on the critical path.
3. A background worker (registered as an APScheduler job in `scheduler.py` — see §4, one scheduler instance drives this job, the event consumer, and the digest email, not three independent loops) polls `product_sync_outbox` for `pending` rows, embeds the product text (title + description + category) via `mesh_client.embed()`, upserts into Chroma keyed by `product_id`, marks the outbox row `done`. On failure, increments `attempts` and retries with backoff; after N attempts, marks `failed` and logs for manual review.
4. Delete follows the same path: soft-delete in Postgres (`is_deleted=true`) + outbox `operation='delete'` → worker removes the Chroma entry.

This is the actual "enterprise" answer to the brief's dual-write requirement — it's what separates "we call both APIs and hope" from a system that stays consistent under partial failure.

---

## 4. Behavioral event tracking

**Client side** (`tracker.js`):
- In-memory queue, not `localStorage`.
- Flush triggers: queue reaches 20 events, OR 10s elapsed, OR `visibilitychange`/`pagehide` fires `navigator.sendBeacon` (fire-and-forget, survives navigation).
- Only semantic events are tracked (`view`, `search`, `click`, `time_on_page` at pre-computed intervals) — raw `mousemove`/`scroll` are debounced/aggregated client-side, never sent per-pixel.

**Server side**:
- `POST /api/events/batch` — validates payload shape, pushes straight to a Redis list (`LPUSH`), returns `202` immediately. No DB write on the request path.
- A consumer job on the shared APScheduler instance (`scheduler.py` — same instance that runs the outbox worker and digest email, running every few seconds for this job specifically) `LRANGE`+`LTRIM`s the Redis list and bulk-inserts into `events` via `executemany`-style batch insert.
- Same consumer tick increments each affected user's `pending_signal:{user_id}` counter in Redis — this is what feeds the trigger decision in §5, so tracking and triggering share one pass instead of two.

---

## 5. Agentic recommendation engine (LangGraph)

State object: `{ user_id, raw_events, interest_summary, retrieved_products, retry_count, recommendation }`

```
load_activity → should_trigger ─(no)→ serve_cached_recommendation [END]
                     │(yes)
                     ▼
              analyze_interest  (Mesh LLM call — cached by hash of event window)
                     ▼
                 retrieve  (Chroma semantic search + category/price metadata filter)
                     ▼
             evaluate_retrieval ─(weak, retry_count<2)→ refine_query ─┐
                     │(good)                                          │
                     ▼                                        (loops back to retrieve)
           generate_recommendation  (Mesh LLM call, structured JSON output,
                                      grounded strictly in retrieved product_ids)
                     ▼
                  persist  (write recommendations + agent_runs, invalidate old cache)
```

Concurrency guard: before this graph is invoked (from `GET /api/recommendations` or the digest job), acquire `agent_lock:{user_id}` in Redis (`SET NX PX 60000` or similar). If the lock is already held, skip invocation and serve the cached/active recommendation — a second request from the same user (e.g. a second browser tab) must never trigger a second concurrent run. Release the lock in `persist`, and in a `finally`/error path if the graph raises.

Node notes:
- **`should_trigger`** is the single most important node for the "efficiency" judged criterion. Condition: `pending_signal:{user_id} >= THRESHOLD` OR `now - last_recommendation.generated_at >= TTL`. `THRESHOLD` and `TTL` are settings in `config.py` (e.g. `TRIGGER_EVENT_THRESHOLD=5`, `RECOMMENDATION_TTL_HOURS=6`), not hardcoded in the agent module. If neither condition holds, short-circuit to the cached/active recommendation — zero LLM calls.
- **`analyze_interest`** output is cached in Redis keyed by `hash(user_id + sorted recent event ids)`. Identical activity windows never re-hit the LLM twice.
- **`retrieve`** always queries Chroma with the interest summary as the query string plus any inferred category/price filters — never skip retrieval, never let the LLM invent products.
- **`evaluate_retrieval`** is a cheap rule check (result count, top-score threshold), not another LLM call — keep it free.
- **`refine_query`** is bounded to 2 retries max to cap worst-case cost per trigger.
- **`generate_recommendation`** uses a structured output schema (`{"narrative": str, "product_ids": [uuid]}`) requested via Mesh's JSON-schema/structured-output mode where the underlying model supports it. Parse with Pydantic; on a validation error, re-prompt once with the parse error included, then fail closed (keep serving the last cached recommendation, log the failure to `agent_runs` with `status='failed'`) rather than persisting garbage. The model is instructed to only reference IDs present in the retrieved set, but that instruction is **not** the enforcement mechanism — see `persist` below.
- **`persist`** does three things, in order: (1) filter `product_ids` down to the intersection with the actual retrieved-set IDs from `retrieve` — anything the model referenced that wasn't retrieved is dropped and logged, this is the real grounding guarantee, not the prompt; (2) write `recommendations` + `agent_runs`, invalidate the old cache; (3) reset `pending_signal:{user_id}` to 0 and release `agent_lock:{user_id}` — skipping this reset is what causes re-trigger storms, since the counter would otherwise keep climbing past `THRESHOLD` on every subsequent page load.

---

## 6. Trigger & caching strategy (why this wins on "production thinking")

- LLM calls happen only at `analyze_interest` and `generate_recommendation` — never per tracked event.
- Two independent caches: interest-summary cache (keyed by activity-window hash) and recommendation cache (keyed by user, TTL-based, served on every page load until invalidated by a new trigger).
- `agent_runs.status = 'cache_hit'` rows prove — to judges reading the DB or a LangSmith trace — that most page loads cost zero tokens.

---

## 7. Proactive delivery (bonus)

APScheduler job, daily at a fixed hour: query users with `events.created_at` in the last 24h, reuse their active `recommendations` row if fresh (don't force a regeneration just for the email), render an HTML email template with the narrative + product cards, send via SMTP. Logged the same way as any other trigger in `agent_runs` (`trigger_type='scheduled_digest'`).

---

## 8. Observability (bonus)

- Wrap every LangGraph `.invoke()` with LangSmith tracing (`LANGCHAIN_TRACING_V2=true`, project name `smartreco`) — gives judges a node-by-node trace for free.
- `agent_runs` table is the fallback/complement — works even if a judge doesn't have LangSmith access, and directly demonstrates cache-hit efficiency via SQL.

---

## 9. API surface

```
POST   /auth/register
POST   /auth/login

GET    /admin/products
POST   /admin/products
PUT    /admin/products/{id}
DELETE /admin/products/{id}

POST   /api/events/batch

GET    /api/recommendations           # serves cached/active, triggers async regen if stale (lock-guarded, see §5)
GET    /admin/agent-runs              # observability view for judges
GET    /health
```

---

## 10. Security & production hardening

- Bcrypt password hashing, short-lived JWT access token (e.g. 30min expiry), delivered as an **httpOnly, `SameSite=Lax` cookie** — not `localStorage` — since `tracker.js` executes on every page and a JS-readable token is XSS-reachable from that surface. Role-guarded admin routes (dependency-injected `require_admin`).
- Pydantic request/response models on every route — no raw dict handling.
- Rate limiting on `/api/events/batch` **and `/auth/login`** (cheap sliding-window in Redis) — protects both the ingestion path and login from abuse/brute force.
- Structured JSON logging, `/health` endpoint, `.env` for all secrets (never committed — `.gitignore` covers it).

---

## 11. Repo structure

```
smartreco/
├── app/
│   ├── main.py
│   ├── config.py                # env/settings via pydantic-settings
│   ├── db/
│   │   ├── models.py
│   │   ├── session.py
│   │   └── migrations/          # alembic
│   ├── api/
│   │   ├── auth.py
│   │   ├── products.py
│   │   ├── events.py
│   │   └── recommendations.py
│   ├── services/
│   │   ├── mesh_client.py       # the ONE place that calls Mesh — chat() and embed()
│   │   ├── outbox_worker.py     # job logic, registered as a job in scheduler.py
│   │   ├── event_consumer.py    # job logic, registered as a job in scheduler.py
│   │   └── scheduler.py         # single APScheduler instance: outbox flush, event consumer, digest email
│   ├── agent/
│   │   ├── graph.py              # LangGraph definition
│   │   ├── nodes.py
│   │   └── state.py
│   └── vector/
│       └── chroma_client.py
├── static/js/tracker.js
├── templates/                    # Jinja2
├── docs/
│   ├── ARCHITECTURE.md           # this file
│   └── CHALLENGE.md              # original brief
├── tests/
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .gitignore
├── CLAUDE.md
└── README.md
```

---

## 12. Recommended build order (for Claude Code, phase by phase)

1. **Foundation** — Docker Compose (postgres, redis), FastAPI skeleton, SQLAlchemy models + Alembic, auth (register/login/JWT), role-guarded routes.
2. **Product management + outbox** — CRUD endpoints, `product_sync_outbox` table, Chroma client, outbox worker.
3. **Event tracking** — `tracker.js`, `/api/events/batch`, Redis buffering, batch-flush consumer.
4. **Agent core** — `mesh_client.py` wrapper first (test it standalone against Mesh), then the LangGraph graph node-by-node, then wire `should_trigger` + both caches.
5. **Recommendations API + frontend display** — serve stored recommendations, trigger async regen.
6. **Bonuses** — LangSmith tracing, APScheduler digest email, retrieval polish (metadata filtering, re-ranking).
7. **Hardening pass** — rate limiting, structured logging, `/health`, a small retrieval smoke test (5-10 known event patterns → expected products in top-3, backs the grounding claim with evidence instead of just prompt wording), README, verify `.gitignore`/`.env.example`, confirm CI workflow passes.

Build in this order — don't start the agent before the outbox and event pipeline exist, since it has nothing real to reason over otherwise.
