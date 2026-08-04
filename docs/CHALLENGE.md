# SmartReco — Build a Behavioral AI Recommendation Agent

Original hackathon brief (SmartReco Build Challenge 2026). Kept here as ground truth — see `ARCHITECTURE.md` for the actual technical design and `CLAUDE.md` for build conventions.

## The Challenge

Build a web platform (think of a course/product site like an online learning marketplace) that watches how each user behaves and intelligently recommends the right products to them — with AI-generated, persuasive messaging that actually motivates them to take action.

This is not a simple "related products" widget. It's an agentic recommendation system: a backend agent that continuously observes a user's activity, understands their interests, retrieves the most relevant products, and generates personalized, convincing recommendations that update as the user's behavior changes.

## The Story

A user lands on the platform and starts exploring. Every meaningful action is tracked. An AI agent watches this activity build up, reasons over it, retrieves relevant products from a knowledge base, and generates a personalized recommendation — a short narrative on why it matters to them, plus the specific products that fit. Recommendations are stored, shown on the site, and refresh as behavior evolves. Bonus: proactive delivery (e.g. an afternoon email recap).

## What to build

1. **The platform** — email/password auth (keep simple), two roles (regular user, admin). Clean schema: users, products, activity/events, stored recommendations.
2. **Product management with dual-write** — admin CRUD on products/courses; every write goes to both the main DB and a vector DB for semantic retrieval, kept in sync.
3. **Behavioral event tracking** — page/product views, searches, clicks, time spent. Must be efficient and non-blocking (batching, throttling, no frontend freezing). Stored with a sensible schema (who, what, when).
4. **The agentic recommendation engine** — consumes tracked activity, reasons about interests, decides what to recommend. RAG/semantic retrieval over the vector DB — grounded in the real catalog, never made up. Persuasive, personalized narrative + specific products. Stored and refreshed as behavior changes.
5. **Efficiency & production thinking (judged)** — don't fire an LLM call on every action; use meaningful triggers and caching. Efficient, batched, non-blocking event storage.

## Highlighted bonus (optional, strongly encouraged)

- ⭐ Structured agent framework (e.g. LangGraph) — explicit nodes for analyze, decide-to-retrieve, evaluate retrieval quality, refine, generate.
- ⭐ Scheduled proactive delivery — email or Telegram digest via a real scheduler (Celery Beat / APScheduler / cron), not a manual button.
- ⭐ Observability — tracing (e.g. LangSmith) across the agent workflow.
- ⭐ Retrieval polish — re-ranking, metadata filtering, better chunking, or graph-based retrieval.

## Required & suggested stack

- Backend: Flask or FastAPI (Python) — required
- LLM access: all LLM/AI calls must go through **Mesh API** — mandatory
- Vector DB: any (Chroma, Pinecone, Qdrant, FAISS, etc.)
- Frontend: server-rendered templates (Jinja2) + JavaScript for tracking
- Database: SQLite or PostgreSQL
- Agent (bonus): LangGraph · Scheduling (bonus): Celery / APScheduler · Observability (bonus): LangSmith

Keep API keys in a local `.env` (never commit it).

## Using Mesh API

Mesh is an OpenAI-compatible gateway — one key gives access to 1000+ models.

```python
from openai import OpenAI
client = OpenAI(base_url="https://api.meshapi.ai/v1", api_key="rsk_...")
client.chat.completions.create(
    model="openai/gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
)
```

Key starts with `rsk_`, created on the Mesh dashboard. Add it to a gitignored `.env` and as the GitHub secret `MESH_API_KEY`.

## Submission requirements

- Public GitHub repository containing all code (this is what gets evaluated).
- README explaining what was built, the architecture, setup/run instructions, and which bonus features were implemented.
- (Optional) short demo video and deployed URL — reviewed for finalists.

## What a great submission looks like

- Tracking that captures rich behavioral signals without slowing the site down.
- Products genuinely dual-written to SQL and a vector database, kept in sync.
- An agent that actually uses behavior to drive catalog-grounded recommendations — not generic popular-product lists.
- Persuasive copy reflecting the specific user's interests.
- Production thinking: efficient AI-call triggering, caching, batched events, and (bonus) proper scheduled delivery.

## Setup & automated checks

Repository must contain: all source code, `requirements.txt`/`pyproject.toml`/`Pipfile` listing a web framework + LLM client, `README.md`, `.gitignore` including `.env`.

Repository secrets needed: `MESH_API_KEY` (Mesh API key — mandatory for every LLM call), `SUBMISSION_TOKEN` (from the submission dashboard).

Critical checks (must pass): code compiles (no syntax errors), dependencies present (web framework + LLM client listed). Advisory only (non-blocking): no committed `.env`, README present, `.gitignore` ignores `.env`.

## Terms

- Submissions are first screened by an automated AI system; top submissions are reviewed by human judges.
- Using Mesh API is mandatory — a submission that doesn't route LLM/AI calls through Mesh API is not valid.
- Judges' decisions are final.
