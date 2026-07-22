"""LangChain Qdrant vector store wrapper. This is the single source of truth for the KB.

Epic 3's agent imports this module directly rather than constructing a second store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client.models import FieldCondition, Filter, MatchAny

from app.config import get_settings
from app.embeddings.voyage import get_embeddings
from app.ingestion.models import GLOBAL_SESSION, Chunk

if TYPE_CHECKING:
    from langchain_core.vectorstores.base import VectorStoreRetriever


def _chunk_metadata(chunk: Chunk) -> dict:
    metadata: dict = {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "chunk_type": chunk.chunk_type,
        "section_path": chunk.section_path,
        "session_id": chunk.session_id,
    }
    if chunk.page_no is not None:
        metadata["page_no"] = chunk.page_no
    for key, value in chunk.metadata.items():
        if isinstance(value, (str, int, float, bool)):
            metadata[key] = value
    return metadata


def _to_document(chunk: Chunk) -> Document:
    return Document(page_content=chunk.text, metadata=_chunk_metadata(chunk))


def _build_filter(chunk_types: list[str] | None, session_id: str | None) -> Filter:
    """Always includes the global corpus; additionally includes `session_id`'s own
    uploads if given. This is the only thing that makes uploaded documents searchable
    only by the session that uploaded them -- see ARCHITECTURE.md.

    `QdrantVectorStore`'s dict-based filter shorthand only supports flat equality
    matching (no `$in`/`$and`) and is deprecated by the library itself -- building a
    real `qdrant_client.models.Filter` directly is the supported path. `must=[...]` is
    the AND, `MatchAny` is the IN. Metadata lives under LangChain's `metadata` payload
    key, hence the `metadata.<field>` key prefix.
    """
    session_ids = [GLOBAL_SESSION] if not session_id or session_id == GLOBAL_SESSION else [GLOBAL_SESSION, session_id]
    must = [FieldCondition(key="metadata.session_id", match=MatchAny(any=session_ids))]
    if chunk_types:
        must.append(FieldCondition(key="metadata.chunk_type", match=MatchAny(any=chunk_types)))
    return Filter(must=must)


class QdrantStore:
    def __init__(self, url: str | None = None, collection_name: str | None = None) -> None:
        settings = get_settings()
        # `construct_instance` creates the collection if it doesn't exist yet (detecting
        # the vector size via a throwaway probe embedding that's never persisted as a
        # point) or validates dimension/distance against it if it does -- either way
        # this is the one place that needs to run before any upsert/query against a
        # fresh Qdrant instance. `client_options` is passed straight through to
        # `QdrantClient(**client_options)` internally.
        self._store = QdrantVectorStore.construct_instance(
            embedding=get_embeddings(),
            client_options={"url": url or settings.qdrant_url},
            collection_name=collection_name or settings.qdrant_collection,
        )

    def upsert(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        documents = [_to_document(chunk) for chunk in chunks]
        self._store.add_documents(documents, ids=[chunk.chunk_id for chunk in chunks])

    async def query(
        self,
        query: str,
        top_k: int,
        chunk_types: list[str] | None = None,
        session_id: str | None = None,
    ) -> list[Document]:
        # `qdrant-client`'s `QdrantVectorStore` (as of langchain-qdrant 1.1.0) has no
        # native async client of its own, same as Chroma -- `asimilarity_search` is
        # still `VectorStore`'s thread-pool-shimmed default. Kept async regardless: it's
        # free (no extra dependency, no behavior change either way) and keeps this
        # call's signature consistent with the rest of the already-async /ask chain.
        where = _build_filter(chunk_types, session_id)
        return await self._store.asimilarity_search(query, k=top_k, filter=where)

    def as_retriever(self, top_k: int) -> VectorStoreRetriever:
        return self._store.as_retriever(search_kwargs={"k": top_k})

    def count(self) -> int:
        return self._store.client.count(self._store.collection_name, exact=True).count
