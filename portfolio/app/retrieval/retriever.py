"""Vector search over the Qdrant KB. Embedding of the query happens inside
`QdrantVectorStore` itself (via the `Embeddings` instance passed to `QdrantStore`), so
this stays a thin wrapper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import get_settings
from app.vectorstore.qdrant_store import QdrantStore

if TYPE_CHECKING:
    from langchain_core.documents import Document


class Retriever:
    def __init__(self, store: QdrantStore | None = None) -> None:
        self._store = store or QdrantStore()

    async def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        tenant_id: str | None = None,
        doc_ids: list[str] | None = None,
    ) -> list[Document]:
        settings = get_settings()
        return await self._store.query(
            query, top_k=top_k or settings.retrieval_top_k, tenant_id=tenant_id, doc_ids=doc_ids
        )
