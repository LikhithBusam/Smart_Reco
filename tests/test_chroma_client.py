from unittest.mock import patch

import pytest

from app.config import settings
from app.vector import chroma_client


@pytest.fixture(autouse=True)
def _isolated_chroma_dir(tmp_path, monkeypatch):
    """Point Chroma at a throwaway directory per test and reset the cached
    client/collection so tests never touch real persisted data or leak
    state between tests."""
    monkeypatch.setattr(settings, "chroma_persist_dir", str(tmp_path / "chroma"))
    chroma_client._client.cache_clear()
    chroma_client._products_collection.cache_clear()
    yield
    chroma_client._client.cache_clear()
    chroma_client._products_collection.cache_clear()


def _stub_embed(text: str) -> list[float]:
    # Deterministic stand-in for mesh_client.embed — proves the Chroma
    # integration works without needing a real Mesh API key.
    return [float(len(text) % 7), 0.5, 0.25]


def test_upsert_product_is_retrievable_by_query():
    with patch("app.vector.chroma_client.mesh_client.embed", side_effect=_stub_embed):
        chroma_client.upsert_product(
            product_id="11111111-1111-1111-1111-111111111111",
            title="Agentic AI Systems",
            description="Build autonomous LangGraph agents",
            category="ai",
            price=99.0,
        )

        results = chroma_client.query_products("agentic AI course", n_results=5)

    assert "11111111-1111-1111-1111-111111111111" in results["ids"][0]


def test_delete_product_removes_it_from_results():
    with patch("app.vector.chroma_client.mesh_client.embed", side_effect=_stub_embed):
        chroma_client.upsert_product(
            product_id="22222222-2222-2222-2222-222222222222",
            title="Intro to Python",
            description="Learn Python basics",
            category="programming",
            price=49.0,
        )
        chroma_client.delete_product("22222222-2222-2222-2222-222222222222")

        results = chroma_client.query_products("python course", n_results=5)

    assert "22222222-2222-2222-2222-222222222222" not in results["ids"][0]


def test_default_embedding_function_refuses_to_run():
    guard = chroma_client._RefuseDefaultEmbedding()

    with pytest.raises(RuntimeError, match="must never run"):
        guard(["some text"])
