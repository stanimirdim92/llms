"""Voyage AI embeddings — one embedding space shared by text, table, and figure-caption chunks."""

from dataclasses import dataclass

import voyageai

from app.config import get_settings
from app.ingestion.models import Chunk

_BATCH_SIZE = 128


@dataclass(frozen=True)
class EmbeddedChunk:
    chunk: Chunk
    embedding: list[float]


def _client() -> voyageai.Client:
    settings = get_settings()
    return voyageai.Client(api_key=settings.voyage_api_key)


def embed_texts(texts: list[str], *, input_type: str) -> list[list[float]]:
    """Embed raw strings in batches. `input_type` is "document" for ingestion, "query" for retrieval."""
    settings = get_settings()
    client = _client()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), _BATCH_SIZE):
        batch = texts[start : start + _BATCH_SIZE]
        result = client.embed(batch, model=settings.voyage_model, input_type=input_type)
        vectors.extend(result.embeddings)
    return vectors


def embed_chunks(chunks: list[Chunk]) -> list[EmbeddedChunk]:
    if not chunks:
        return []
    vectors = embed_texts([c.text for c in chunks], input_type="document")
    return [EmbeddedChunk(chunk=chunk, embedding=vector) for chunk, vector in zip(chunks, vectors, strict=True)]


def embed_query(query: str) -> list[float]:
    return embed_texts([query], input_type="query")[0]
