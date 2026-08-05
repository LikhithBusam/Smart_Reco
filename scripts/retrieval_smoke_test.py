"""Retrieval smoke test — real evidence for the grounding claim, not just
prompt wording (ARCHITECTURE.md §12 Phase 7).

Seeds a throwaway Chroma collection with a known catalog via REAL Mesh API
embedding calls, then checks that 8 known interest phrases retrieve the
expected product in their top-3 results. Needs a real MESH_API_KEY in .env
and network access — this is why it's a standalone script, not part of the
mocked pytest suite (which must run without either).

Run: python scripts/retrieval_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402

settings.chroma_persist_dir = tempfile.mkdtemp(prefix="smartreco_smoke_")

from app.vector import chroma_client  # noqa: E402

CATALOG = [
    ("11111111-1111-1111-1111-111111111101", "Agentic AI Systems", "Build autonomous LangGraph agents that reason and act", "ai", 99.0),
    ("11111111-1111-1111-1111-111111111102", "Prompt Engineering Foundations", "Craft effective prompts for large language models", "ai", 49.0),
    ("11111111-1111-1111-1111-111111111103", "Data Engineering with Spark", "Build scalable batch and streaming data pipelines", "data", 79.0),
    ("11111111-1111-1111-1111-111111111104", "SQL for Analysts", "Query and join relational databases confidently", "data", 39.0),
    ("11111111-1111-1111-1111-111111111105", "UI Design Fundamentals", "Typography, layout, and color theory for interfaces", "design", 45.0),
    ("11111111-1111-1111-1111-111111111106", "Figma for Product Designers", "Prototype and hand off designs in Figma", "design", 35.0),
    ("11111111-1111-1111-1111-111111111107", "Kubernetes in Production", "Deploy and operate containerized applications at scale", "devops", 89.0),
    ("11111111-1111-1111-1111-111111111108", "CI/CD Pipelines with GitHub Actions", "Automate build, test, and deploy workflows", "devops", 29.0),
]

# (query, expected product id, expected title — title is just for readable output)
QUERIES = [
    ("I want to build autonomous AI agents", CATALOG[0][0], CATALOG[0][1]),
    ("How do I write better prompts for GPT models", CATALOG[1][0], CATALOG[1][1]),
    ("I need to process large datasets with Spark", CATALOG[2][0], CATALOG[2][1]),
    ("Teach me SQL queries for data analysis", CATALOG[3][0], CATALOG[3][1]),
    ("I'm interested in UI and UX design basics", CATALOG[4][0], CATALOG[4][1]),
    ("I want to learn Figma prototyping", CATALOG[5][0], CATALOG[5][1]),
    ("How do I deploy applications with Kubernetes", CATALOG[6][0], CATALOG[6][1]),
    ("Help me automate my deployment pipeline", CATALOG[7][0], CATALOG[7][1]),
]


def main() -> int:
    print(f"Seeding {len(CATALOG)} products via real Mesh embeddings...")
    for product_id, title, description, category, price in CATALOG:
        chroma_client.upsert_product(product_id, title, description, category, price)
    print("Seeded.\n")

    passed = 0
    for query, expected_id, expected_title in QUERIES:
        results = chroma_client.query_products(query, n_results=3)
        top_ids = results["ids"][0] if results.get("ids") else []
        ok = expected_id in top_ids
        passed += ok
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] '{query}' -> expected '{expected_title}' in top-3 (got {len(top_ids)} results)")

    print(f"\n{passed}/{len(QUERIES)} queries retrieved the expected product in their top-3.")
    return 0 if passed == len(QUERIES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
