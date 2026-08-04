"""The ONE place in this codebase that talks to Mesh API. Every embedding or chat
call, anywhere in the app, goes through this module — never instantiate an
OpenAI client elsewhere, and never let Chroma fall back to its own default
embedding function (CLAUDE.md non-negotiable constraints).
"""

from functools import lru_cache

from openai import OpenAI

from app.config import settings


@lru_cache
def _client() -> OpenAI:
    return OpenAI(base_url=settings.mesh_base_url, api_key=settings.mesh_api_key)


def embed(text: str) -> list[float]:
    return embed_many([text])[0]


def embed_many(texts: list[str]) -> list[list[float]]:
    response = _client().embeddings.create(model=settings.mesh_embedding_model, input=texts)
    return [item.embedding for item in response.data]


# chat() lands in Phase 4 alongside the LangGraph agent — analyze_interest and
# generate_recommendation are the only two nodes allowed to call it.
