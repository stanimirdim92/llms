"""Chroma persistent collection wrapper. This is the single source of truth for the KB.

Epic 3's agent imports this module directly rather than constructing a second store.
"""

from dataclasses import dataclass

import chromadb

from app.config import get_settings
from app.embeddings.voyage import EmbeddedChunk
from app.ingestion.models import Chunk


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    chunk_type: str
    text: str
    page_no: int | None
    section_path: str
    metadata: dict
    distance: float


class ChromaStore:
    def __init__(self, path: str | None = None, collection_name: str | None = None) -> None:
        settings = get_settings()
        self._client = chromadb.PersistentClient(path=path or str(settings.chroma_path))
        self._collection = self._client.get_or_create_collection(
            name=collection_name or settings.chroma_collection,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, embedded_chunks: list[EmbeddedChunk]) -> None:
        if not embedded_chunks:
            return
        self._collection.upsert(
            ids=[ec.chunk.chunk_id for ec in embedded_chunks],
            embeddings=[ec.embedding for ec in embedded_chunks],
            documents=[ec.chunk.text for ec in embedded_chunks],
            metadatas=[_chunk_metadata(ec.chunk) for ec in embedded_chunks],
        )

    def query(
        self,
        query_embedding: list[float],
        top_k: int,
        chunk_types: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        where = {"chunk_type": {"$in": chunk_types}} if chunk_types else None
        result = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
        )
        retrieved: list[RetrievedChunk] = []
        ids = result["ids"][0]
        documents = result["documents"][0]
        metadatas = result["metadatas"][0]
        distances = result["distances"][0]
        for chunk_id, text, meta, distance in zip(ids, documents, metadatas, distances, strict=True):
            retrieved.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    doc_id=meta.get("doc_id", ""),
                    chunk_type=meta.get("chunk_type", "text"),
                    text=text,
                    page_no=meta.get("page_no"),
                    section_path=meta.get("section_path", ""),
                    metadata=meta,
                    distance=distance,
                )
            )
        return retrieved

    def count(self) -> int:
        return self._collection.count()


def _chunk_metadata(chunk: Chunk) -> dict:
    metadata: dict = {
        "doc_id": chunk.doc_id,
        "chunk_type": chunk.chunk_type,
        "section_path": chunk.section_path,
    }
    if chunk.page_no is not None:
        metadata["page_no"] = chunk.page_no
    for key, value in chunk.metadata.items():
        if isinstance(value, (str, int, float, bool)):
            metadata[key] = value
    return metadata
