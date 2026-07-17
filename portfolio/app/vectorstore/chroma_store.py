"""LangChain Chroma vector store wrapper. This is the single source of truth for the KB.

Epic 3's agent imports this module directly rather than constructing a second store.
"""

from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.config import get_settings
from app.embeddings.voyage import get_embeddings
from app.ingestion.models import Chunk


def _chunk_metadata(chunk: Chunk) -> dict:
    metadata: dict = {
        "chunk_id": chunk.chunk_id,
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


def _to_document(chunk: Chunk) -> Document:
    return Document(page_content=chunk.text, metadata=_chunk_metadata(chunk))


class ChromaStore:
    def __init__(self, path: str | None = None, collection_name: str | None = None) -> None:
        settings = get_settings()
        self._store = Chroma(
            collection_name=collection_name or settings.chroma_collection,
            embedding_function=get_embeddings(),
            persist_directory=path or str(settings.chroma_path),
            collection_metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        documents = [_to_document(chunk) for chunk in chunks]
        self._store.add_documents(documents, ids=[chunk.chunk_id for chunk in chunks])

    def query(self, query: str, top_k: int, chunk_types: list[str] | None = None) -> list[Document]:
        where = {"chunk_type": {"$in": chunk_types}} if chunk_types else None
        return self._store.similarity_search(query, k=top_k, filter=where)

    def as_retriever(self, top_k: int):
        return self._store.as_retriever(search_kwargs={"k": top_k})

    def count(self) -> int:
        return self._store._collection.count()
