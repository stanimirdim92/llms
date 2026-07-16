"""Rerank retrieved chunks. Backend is env-selectable so the system isn't hard-locked to a paid API."""

from functools import lru_cache

import cohere

from app.config import get_settings
from app.vectorstore.chroma_store import RetrievedChunk


@lru_cache
def _local_cross_encoder():
    from sentence_transformers import CrossEncoder

    settings = get_settings()
    return CrossEncoder(settings.local_reranker_model)


def _rerank_cohere(query: str, chunks: list[RetrievedChunk], top_n: int) -> list[RetrievedChunk]:
    settings = get_settings()
    client = cohere.ClientV2(api_key=settings.cohere_api_key)
    response = client.rerank(
        model=settings.cohere_rerank_model,
        query=query,
        documents=[c.text for c in chunks],
        top_n=min(top_n, len(chunks)),
    )
    return [chunks[result.index] for result in response.results]


def _rerank_local(query: str, chunks: list[RetrievedChunk], top_n: int) -> list[RetrievedChunk]:
    model = _local_cross_encoder()
    scores = model.predict([(query, c.text) for c in chunks])
    ranked = sorted(zip(chunks, scores, strict=True), key=lambda pair: pair[1], reverse=True)
    return [chunk for chunk, _score in ranked[:top_n]]


def rerank(query: str, chunks: list[RetrievedChunk], top_n: int | None = None) -> list[RetrievedChunk]:
    settings = get_settings()
    n = top_n or settings.rerank_top_n
    if not chunks:
        return []
    if settings.reranker_backend == "local":
        return _rerank_local(query, chunks, n)
    return _rerank_cohere(query, chunks, n)
