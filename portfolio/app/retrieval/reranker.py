"""Rerank retrieved chunks via LangChain's document-compressor interface. Backend is
env-selectable so the system isn't hard-locked to a paid API."""

from functools import lru_cache

from langchain_core.documents import Document

from app.config import get_settings


@lru_cache
def _local_compressor():
    from langchain_classic.retrievers.document_compressors import CrossEncoderReranker
    from langchain_community.cross_encoders import HuggingFaceCrossEncoder

    settings = get_settings()
    model = HuggingFaceCrossEncoder(model_name=settings.local_reranker_model)
    return CrossEncoderReranker(model=model, top_n=settings.rerank_top_n)


def _voyage_compressor():
    from langchain_voyageai import VoyageAIRerank

    settings = get_settings()
    return VoyageAIRerank(voyage_api_key=settings.voyage_api_key, model=settings.voyage_rerank_model, top_k=settings.rerank_top_n)


def rerank(query: str, documents: list[Document], top_n: int | None = None) -> list[Document]:
    settings = get_settings()
    if not documents:
        return []
    compressor = _local_compressor() if settings.reranker_backend == "local" else _voyage_compressor()
    reranked = compressor.compress_documents(documents, query)
    n = top_n or settings.rerank_top_n
    return list(reranked)[:n]
