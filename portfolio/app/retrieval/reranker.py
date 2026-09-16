"""Rerank retrieved chunks via LangChain's document-compressor interface. Backend is
env-selectable so the system isn't hard-locked to a paid API.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

import structlog

from app.config import get_settings

if TYPE_CHECKING:
    from langchain_core.documents import Document
    from langchain_core.documents.compressor import BaseDocumentCompressor

log = structlog.get_logger(__name__)


@lru_cache
def _local_compressor() -> BaseDocumentCompressor:
    # Imported lazily: sentence-transformers/torch are only needed for this fallback
    # path (the `local-reranker` optional dependency group), not the default Voyage one.
    from langchain_classic.retrievers.document_compressors import CrossEncoderReranker  # noqa: PLC0415
    from langchain_community.cross_encoders import HuggingFaceCrossEncoder  # noqa: PLC0415

    settings = get_settings()
    model = HuggingFaceCrossEncoder(model_name=settings.local_reranker_model)
    return CrossEncoderReranker(model=model, top_n=settings.rerank_top_n)


def _voyage_compressor() -> BaseDocumentCompressor:
    from langchain_voyageai import VoyageAIRerank  # noqa: PLC0415

    settings = get_settings()
    return VoyageAIRerank(
        voyage_api_key=settings.voyage_api_key, model=settings.voyage_rerank_model, top_k=settings.rerank_top_n
    )


async def rerank(query: str, documents: list[Document], top_n: int | None = None) -> list[Document]:
    """Reranks `documents`, or falls back to the vector-similarity order that's already there
    if the reranker call itself fails.

    `documents` arrives already ranked -- `QdrantStore.query`'s `asimilarity_search` returns
    similarity order -- so a slice of it is a real, if less precise, fallback rather than
    nothing. Rule 9: reranking is one layer of a guardrail on answer quality, not the
    retrieval itself, so its own outage must not become `/ask`'s outage. Contrast
    `QdrantStore.query`, where a failure has no honest fallback (there is no answer without a
    query vector) and is deliberately let through as a clear error instead -- see
    `RetrievalUnavailableError`.
    """
    settings = get_settings()
    if not documents:
        return []
    n = top_n or settings.rerank_top_n
    compressor = _local_compressor() if settings.reranker_backend == "local" else _voyage_compressor()
    try:
        # VoyageAIRerank has a real async client; the local cross-encoder falls back to
        # BaseDocumentCompressor's default (sync call run in a thread pool) since torch
        # inference has no async form -- either way this doesn't block the event loop.
        reranked = await compressor.acompress_documents(documents, query)
    except Exception as exc:  # noqa: BLE001 -- an external-provider outage, not a local bug; degrade, don't fail
        log.warning("reranker.unavailable", backend=settings.reranker_backend, error=str(exc))
        return documents[:n]
    return list(reranked)[:n]
