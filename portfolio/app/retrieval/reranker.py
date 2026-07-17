"""Rerank retrieved chunks via LangChain's document-compressor interface. Backend is
env-selectable so the system isn't hard-locked to a paid API.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from app.config import get_settings

if TYPE_CHECKING:
    from langchain_core.documents import Document
    from langchain_core.documents.compressor import BaseDocumentCompressor


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


def rerank(query: str, documents: list[Document], top_n: int | None = None) -> list[Document]:
    settings = get_settings()
    if not documents:
        return []
    compressor = _local_compressor() if settings.reranker_backend == "local" else _voyage_compressor()
    reranked = compressor.compress_documents(documents, query)
    n = top_n or settings.rerank_top_n
    return list(reranked)[:n]
