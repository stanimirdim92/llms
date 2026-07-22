"""Voyage AI embeddings via LangChain's `Embeddings` interface — one embedding space shared
by text, table, and figure-caption chunks, and usable directly as `QdrantVectorStore`'s
`embedding` argument.
"""

from functools import lru_cache

from langchain_voyageai import VoyageAIEmbeddings

from app.config import get_settings


@lru_cache
def get_embeddings() -> VoyageAIEmbeddings:
    settings = get_settings()
    return VoyageAIEmbeddings(api_key=settings.voyage_api_key, model=settings.voyage_model)
