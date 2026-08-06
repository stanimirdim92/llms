"""Vector search over the Qdrant KB. Embedding of the query happens inside
`QdrantVectorStore` itself (via the `Embeddings` instance passed to `QdrantStore`), so
this stays a thin wrapper -- apart from the registry check below, which is here because it is
the one place every retrieval path passes through.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from app.config import get_settings
from app.db import get_session, init_db
from app.registry.db import list_ingested_doc_ids
from app.vectorstore.qdrant_store import QdrantStore

if TYPE_CHECKING:
    from langchain_core.documents import Document

log = structlog.get_logger(__name__)


class Retriever:
    def __init__(self, store: QdrantStore | None = None) -> None:
        self._store = store or QdrantStore()

    async def retrieve(
        self,
        query: str,
        tenant_id: str,
        top_k: int | None = None,
        doc_ids: list[str] | None = None,
    ) -> list[Document]:
        """Search this tenant's **ingested** documents only.

        Postgres decides what is searchable and Qdrant cannot: `ingest_document` upserts points
        and *then* writes the registry row, so a failure between the two leaves retrievable chunks
        behind a row saying `processing` or `failed`. Filtering on the registry's `ingested` set
        closes that -- a half-ingested or failed document cannot reach an answer.

        The check lives here rather than in the router because `/ask` and the Streamlit UI both
        arrive through this method, and a check in one caller is a check the other forgets.
        """
        settings = get_settings()
        await init_db()
        async with get_session() as session:
            ingested = await list_ingested_doc_ids(session, tenant_id=tenant_id)

        permitted = sorted(set(ingested) & set(doc_ids)) if doc_ids is not None else ingested
        if not permitted:
            # Nothing searchable: either the tenant has no ingested document, or the scope it asked
            # for is not among them (it failed since the scope was resolved). Both answer from
            # nothing rather than widening -- falling back to the tenant's *other* documents would
            # answer a question about document X from document Y.
            #
            # Returning here also keeps an empty allow-list away from Qdrant entirely. There was
            # a second, earlier `if not ingested` branch doing that separately; mutation-testing
            # showed deleting it changed no test, because this check already covers it.
            log.info("retrieval.nothing_searchable", tenant_id=tenant_id, requested=doc_ids, ingested=len(ingested))
            return []

        return await self._store.query(
            query, top_k=top_k or settings.retrieval_top_k, tenant_id=tenant_id, doc_ids=permitted
        )
