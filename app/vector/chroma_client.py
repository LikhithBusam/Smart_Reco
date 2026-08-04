"""Chroma is a store for precomputed vectors only. Every embedding written or
queried here comes from app.services.mesh_client — this module never lets
Chroma compute its own embeddings (CLAUDE.md non-negotiable constraint).
"""

from functools import lru_cache
from typing import Any

import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings

from app.config import settings
from app.services import mesh_client

PRODUCTS_COLLECTION = "products"


class _RefuseDefaultEmbedding(EmbeddingFunction):
    """Guard: if any code path calls Chroma without precomputed embeddings,
    fail loudly instead of silently falling back to Chroma's local model."""

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002 - chroma's protocol names it "input"
        raise RuntimeError(
            "Chroma's default embedding function must never run. "
            "Precompute embeddings via app.services.mesh_client and pass them explicitly."
        )


@lru_cache
def _client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=settings.chroma_persist_dir)


@lru_cache
def _products_collection():
    return _client().get_or_create_collection(
        name=PRODUCTS_COLLECTION,
        embedding_function=_RefuseDefaultEmbedding(),
    )


def _product_text(title: str, description: str, category: str) -> str:
    return f"{title}\n\n{description}\n\nCategory: {category}"


def upsert_product(
    product_id: str,
    title: str,
    description: str,
    category: str,
    price: float,
) -> None:
    text = _product_text(title, description, category)
    embedding = mesh_client.embed(text)
    _products_collection().upsert(
        ids=[product_id],
        embeddings=[embedding],
        documents=[text],
        metadatas=[{"category": category, "price": price}],
    )


def delete_product(product_id: str) -> None:
    _products_collection().delete(ids=[product_id])


def query_products(
    query_text: str,
    n_results: int = 5,
    where: dict[str, Any] | None = None,
) -> dict:
    embedding = mesh_client.embed(query_text)
    return _products_collection().query(
        query_embeddings=[embedding],
        n_results=n_results,
        where=where,
    )
