"""Vector search over the Chroma KB."""

from app.config import get_settings
from app.embeddings.voyage import embed_query
from app.vectorstore.chroma_store import ChromaStore, RetrievedChunk


class Retriever:
    def __init__(self, store: ChromaStore | None = None) -> None:
        self._store = store or ChromaStore()

    def retrieve(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
        settings = get_settings()
        query_embedding = embed_query(query)
        return self._store.query(query_embedding, top_k=top_k or settings.retrieval_top_k)
