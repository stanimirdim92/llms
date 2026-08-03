"""LangChain Qdrant vector store wrapper. This is the single source of truth for the KB.

Epic 3's agent imports this module directly rather than constructing a second store.
"""

from __future__ import annotations

import uuid

import structlog
from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchAny, MatchValue

from app.config import get_settings
from app.embeddings.voyage import get_embeddings
from app.ingestion.models import GLOBAL_TENANT, Chunk

log = structlog.get_logger(__name__)

# Fixed, arbitrary namespace for deriving Qdrant point IDs from our own chunk_id strings
# via uuid5 -- never regenerate this, or every existing point ID changes and re-ingesting
# unchanged documents would duplicate rather than upsert. Qdrant point IDs must be an
# unsigned integer or a UUID (unlike Chroma, which accepted arbitrary strings); our
# chunk_id values ("{doc_id}-text-0000" etc.) are neither, so they can't be used as the
# point ID directly. uuid5 (not uuid4) keeps this deterministic: the same chunk_id always
# maps to the same point ID, which is what makes re-ingesting identical content an upsert
# rather than a duplicate. The human-readable chunk_id itself is unaffected -- it's still
# stored in the payload (_chunk_metadata below) and is what citations actually read.
_POINT_ID_NAMESPACE = uuid.UUID("6f2d7e2a-9b1a-4c3e-8f7a-1d2e3c4b5a6f")


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_POINT_ID_NAMESPACE, chunk_id))


def _chunk_metadata(chunk: Chunk) -> dict:
    metadata: dict = {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "chunk_type": chunk.chunk_type,
        "section_path": chunk.section_path,
        "tenant_id": chunk.tenant_id,
    }
    if chunk.page_no is not None:
        metadata["page_no"] = chunk.page_no
    dropped = []
    for key, value in chunk.metadata.items():
        if isinstance(value, (str, int, float, bool)):
            metadata[key] = value
        else:
            dropped.append(key)
    if dropped:
        # Logged, not raised: a non-primitive value is a caller mistake, not a reason to fail an
        # ingest that is otherwise fine. But it must be *visible* -- silently dropping means the
        # key is simply absent from the payload later, and the reader's first guess is that
        # ingestion never ran rather than that their value was a list.
        log.info("qdrant.metadata_dropped", chunk_id=chunk.chunk_id, keys=dropped)
    return metadata


def _to_document(chunk: Chunk) -> Document:
    return Document(page_content=chunk.text, metadata=_chunk_metadata(chunk))


def _build_filter(chunk_types: list[str] | None, tenant_id: str | None, doc_ids: list[str] | None = None) -> Filter:
    """Always includes the global corpus; additionally includes `tenant_id`'s own uploads.

    This is the entire retrieval security boundary: it is what stops one tenant reading
    another's documents. `tenant_id` must therefore only ever come from
    `api/deps.py::current_tenant` -- i.e. from a verified API key, never from a request body.
    Accepting a caller-supplied scope here is exactly the vulnerability this replaced.

    `QdrantVectorStore`'s dict-based filter shorthand only supports flat equality
    matching (no `$in`/`$and`) and is deprecated by the library itself -- building a
    real `qdrant_client.models.Filter` directly is the supported path. `must=[...]` is
    the AND, `MatchAny` is the IN. Metadata lives under LangChain's `metadata` payload
    key, hence the `metadata.<field>` key prefix.
    """
    tenant_ids = [GLOBAL_TENANT] if not tenant_id or tenant_id == GLOBAL_TENANT else [GLOBAL_TENANT, tenant_id]
    must = [FieldCondition(key="metadata.tenant_id", match=MatchAny(any=tenant_ids))]
    if chunk_types:
        must.append(FieldCondition(key="metadata.chunk_type", match=MatchAny(any=chunk_types)))
    if doc_ids:
        # ANDed with the tenant condition above, never replacing it: a doc_id is resolved from
        # the caller's own registry rows, but this filter is the security boundary and must not
        # depend on that being true somewhere upstream.
        must.append(FieldCondition(key="metadata.doc_id", match=MatchAny(any=doc_ids)))
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

    def delete_document(self, doc_id: str, tenant_id: str) -> None:
        """Remove every point belonging to `doc_id` *within one tenant*, whatever its chunk
        ids were.

        `tenant_id` is required, not optional, and it is ANDed into the selector rather than
        checked by the caller. Today `doc_id` is tenant-salted so a cross-tenant delete is
        not reachable -- but that is a property of `upload_doc_id`, enforced in a different
        module, and every read path in this file carries the tenant condition regardless.
        A write that can erase data deserves at least the guard a read has: if the id scheme
        ever changes, this fails closed instead of deleting a stranger's points.

        Upserting by id alone is NOT sufficient to make re-ingestion idempotent: chunk ids
        encode position (`{doc_id}-text-0000`, `fig-{page}-{index}`), so anything that
        changes how many chunks a document yields -- a different `chunk_max_tokens`, a
        Docling upgrade that detects one more figure, toggling `do_ocr` -- shifts the ids.
        The new ids upsert cleanly while the *old* points stay behind, still matching the
        session filter, still retrievable, now stale. Deleting by `doc_id` first makes
        re-ingestion correct regardless of how the chunk ids moved.
        """
        self._store.client.delete(
            collection_name=self._store.collection_name,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(key="metadata.doc_id", match=MatchValue(value=doc_id)),
                        FieldCondition(key="metadata.tenant_id", match=MatchValue(value=tenant_id)),
                    ]
                )
            ),
        )

    def upsert(self, chunks: list[Chunk]) -> None:
        """Replace a document's points: delete-then-insert, not insert-by-id.

        See `delete_document` for why the delete is required rather than paranoid. All
        chunks passed in one call must share a `doc_id` **and** a `tenant_id` -- that's how
        every caller uses it (`ingest_document` handles exactly one document for one
        tenant), and the guards make the assumption fail loudly here rather than silently
        deleting the wrong document's points if a future caller batches across either.

        The tenant guard is the one that was missing: without it a mixed batch would have
        derived its delete selector from `doc_ids.pop()` alone and taken out whichever
        tenant's points matched.
        """
        if not chunks:
            return
        doc_ids = {chunk.doc_id for chunk in chunks}
        if len(doc_ids) != 1:
            msg = f"upsert() expects chunks from exactly one document, got {sorted(doc_ids)}"
            raise ValueError(msg)
        tenant_ids = {chunk.tenant_id for chunk in chunks}
        if len(tenant_ids) != 1:
            msg = f"upsert() expects chunks from exactly one tenant, got {sorted(tenant_ids)}"
            raise ValueError(msg)

        self.delete_document(doc_ids.pop(), tenant_ids.pop())
        documents = [_to_document(chunk) for chunk in chunks]
        self._store.add_documents(documents, ids=[_point_id(chunk.chunk_id) for chunk in chunks])

    async def query(
        self,
        query: str,
        top_k: int,
        chunk_types: list[str] | None = None,
        tenant_id: str | None = None,
        doc_ids: list[str] | None = None,
    ) -> list[Document]:
        # `chunk_types` has no production caller today -- `Retriever` never passes it, so every
        # `/ask` searches text, tables and figures together, which is the intended behaviour.
        # Kept, and said out loud rather than left as an unexplained unused parameter, because
        # Epic 2's eval work needs exactly this to measure recall per chunk kind: "does the
        # reranker ever surface a table" is unanswerable without being able to ask for one kind
        # at a time. `tests/unit/test_qdrant_filtering.py` covers it through the in-memory engine,
        # so it is exercised rather than merely present.
        # `qdrant-client`'s `QdrantVectorStore` (as of langchain-qdrant 1.1.0) has no
        # native async client of its own, same as Chroma -- `asimilarity_search` is
        # still `VectorStore`'s thread-pool-shimmed default. Kept async regardless: it's
        # free (no extra dependency, no behavior change either way) and keeps this
        # call's signature consistent with the rest of the already-async /ask chain.
        where = _build_filter(chunk_types, tenant_id, doc_ids)
        return await self._store.asimilarity_search(query, k=top_k, filter=where)

    # There is deliberately no `as_retriever()`. One existed, returning
    # `self._store.as_retriever(search_kwargs={"k": top_k})` -- no tenant filter, no doc
    # filter, not even an empty one. It had no callers, which is the only reason it was a
    # latent hazard rather than an incident: the first caller to use it for an answer would
    # have read every tenant's uploads, from the one file whose entire job is to prevent
    # exactly that. If a LangChain `Retriever` object is ever genuinely needed, it must take
    # `tenant_id` as a required argument and go through `_build_filter` like `query` does,
    # with a cross-tenant exclusion test alongside it in `test_qdrant_filtering.py`.

    def count(self) -> int:
        return self._store.client.count(self._store.collection_name, exact=True).count
