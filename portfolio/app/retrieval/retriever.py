"""Vector search over the Chroma KB. Embedding of the query happens inside `Chroma` itself
(via the `Embeddings` instance passed to `ChromaStore`), so this stays a thin wrapper."""

from langchain_core.documents import Document

from app.config import get_settings
from app.vectorstore.chroma_store import ChromaStore


class Retriever:
    def __init__(self, store: ChromaStore | None = None) -> None:
        self._store = store or ChromaStore()

    def retrieve(self, query: str, top_k: int | None = None, session_id: str | None = None) -> list[Document]:
        settings = get_settings()
        return self._store.query(query, top_k=top_k or settings.retrieval_top_k, session_id=session_id)
