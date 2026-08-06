"""LangChain Qdrant vector store wrapper. This is the single source of truth for the KB.

Epic 3's agent imports this module directly rather than constructing a second store.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client.models import (
    FieldCondition,
    Filter,
    FilterSelector,
    KeywordIndexParams,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
)

from app.config import get_settings
from app.embeddings.voyage import get_embeddings

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

    from app.ingestion.models import Chunk

log = structlog.get_logger(__name__)

# Fixed, arbitrary namespace for deriving Qdrant point IDs via uuid5 -- never regenerate this, or
# every stored point becomes an orphan no filter and no prune can reach. Qdrant point IDs must be an
# unsigned integer or a UUID (unlike Chroma, which accepted arbitrary strings); our chunk_id values
# ("{doc_id}-text-0000" etc.) are neither, so they can't be used as the point ID directly.
#
# uuid5 (not uuid4) for determinism, but note *of what*: the input is
# f"{ingestion_version}:{chunk_id}", so it is deterministic within one generation and deliberately
# different across generations -- see `_point_id`. The human-readable chunk_id is unaffected: it stays
# in the payload (_chunk_metadata below) and is what citations actually read.
_POINT_ID_NAMESPACE = uuid.UUID("6f2d7e2a-9b1a-4c3e-8f7a-1d2e3c4b5a6f")


def _point_id(chunk_id: str, ingestion_version: str) -> str:
    """A point id per (chunk, ingestion attempt).

    The version is hashed in, **not** appended to `chunk_id`. `chunk_id` is a public response field
    (`CitationResponse.chunk_id`, `RetrievedChunkResponse.chunk_id`) that `README.md` documents and
    Streamlit prints, so moving it would churn every citation on every re-ingest and leak an
    internal attempt id into the API. Only the *point* id has to differ per attempt, and this is
    the single boundary where it is derived.

    Without the version, a re-ingest would overwrite the previous generation in place -- the insert
    would *be* the delete, and there would be nothing to fall back to when it failed.
    """
    return str(uuid.uuid5(_POINT_ID_NAMESPACE, f"{ingestion_version}:{chunk_id}"))


# Payload fields that carry a filter on a production path, and therefore need an index. Every
# query in this module filters on `metadata.tenant_id`; `metadata.doc_id` is filtered by
# `delete_superseded` (once per re-ingest) and by `/ask`'s document scoping.
#
# **`metadata.ingestion_version` is filtered on every query and is deliberately NOT indexed.** It
# is a strictly finer partition of `metadata.doc_id`, which is indexed and sits in the same `must`,
# so the version condition only discriminates during the window where two generations coexist and
# against orphans a prune failed to collect. Against that: a payload index is *resident* memory
# rather than reclaimable page cache, on a 16GB target; and `_ensure_payload_indexes` runs from
# `__init__` against whatever collection exists, so on any instance that already holds points the
# index would be created *after* HNSW is built, which `qdrant-performance-optimization` says breaks
# the filterable vector index -- and its documented remedy is a re-index that nothing here
# triggers, with creation failures already swallowed below by design. Same test that rejected an
# index on `metadata.chunk_type`. Revisit only with a measurement.
#
# **`is_tenant=True` on the tenant field is the load-bearing part**, and it is not a synonym for
# "indexed": it tells Qdrant the field identifies tenants, so each tenant's vectors are stored
# together and a tenant-filtered search is served by sequential reads instead of jumping around
# the segment. Without it a tenant filter degrades toward a scan as the collection grows --
# invisible at six documents, and the stated target is 10k tenants x 10 documents, order 1M
# points. `qdrant-scaling` lists omitting it under things not to do. Requires Qdrant v1.11+;
# compose pins v1.18.3.
#
# `metadata.chunk_type` is deliberately **not** indexed. `_build_filter` accepts `chunk_types`
# but no production caller passes it, so an index there would cost write amplification on every
# upsert to serve nothing. Add it if a caller appears.
_TENANT_FIELD = "metadata.tenant_id"
_INDEXED_PAYLOAD_FIELDS: tuple[tuple[str, bool], ...] = (
    (_TENANT_FIELD, True),
    ("metadata.doc_id", False),
)


def _ensure_payload_indexes(client: QdrantClient, collection_name: str) -> None:
    """Create the keyword payload indexes this store's filters depend on.

    Called from `__init__` after the collection is created or validated, which makes it the one
    place a fresh Qdrant instance gets indexed. `create_payload_index` is idempotent -- verified,
    not assumed: a second identical call returns `completed` rather than raising -- so this is
    safe on every construction and needs no "does it exist" read first.

    Failures are logged and swallowed. An index is a performance property, not a correctness
    one: the filters in this module return exactly the same points unindexed, just more slowly,
    so a store that cannot create an index should still serve. The alternative is refusing to
    construct, which would take the whole api down over something that only matters at scale.
    That is the same fail-open reasoning as the rate limiter, and the loud log is what stops it
    being silent.

    **Not observable in tests.** `qdrant_client`'s local/in-memory mode warns "Payload indexes
    have no effect in the local Qdrant" and leaves `payload_schema` empty, so no in-memory test
    can assert the effect -- only that the right calls were made with the right parameters. The
    effect was verified once against a real `qdrant/qdrant` container; see
    `docs/TECHNICAL_DECISIONS.md`.
    """
    for field, is_tenant in _INDEXED_PAYLOAD_FIELDS:
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field,
                field_schema=KeywordIndexParams(type=PayloadSchemaType.KEYWORD, is_tenant=is_tenant),
            )
        except Exception as exc:  # noqa: BLE001 -- an index is performance, not correctness
            log.warning("qdrant.payload_index_failed", field=field, error=str(exc))


def _chunk_metadata(chunk: Chunk, ingestion_version: str) -> dict:
    metadata: dict = {
        "ingestion_version": ingestion_version,
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


def _to_document(chunk: Chunk, ingestion_version: str) -> Document:
    return Document(page_content=chunk.text, metadata=_chunk_metadata(chunk, ingestion_version))


def _build_filter(
    chunk_types: list[str] | None,
    tenant_id: str,
    doc_ids: list[str] | None = None,
    versions: list[str] | None = None,
) -> Filter:
    """Matches exactly one tenant's chunks. Nothing else is readable.

    This is the entire retrieval security boundary: it is what stops one tenant reading
    another's documents. `tenant_id` must therefore only ever come from
    `api/deps.py::current_tenant` -- i.e. from a verified API key, never from a request body.
    Accepting a caller-supplied scope here is exactly the vulnerability this replaced.

    **One tenant, via `MatchValue`, not a single-element `MatchAny`.** A list invites a second
    element, which is exactly the leak this function exists to prevent. It *was* a list, matching
    `[GLOBAL_TENANT, tenant_id]`, until the shared corpus was removed.

    **`tenant_id` is required and must be non-empty.** It once accepted `None`, meaning "corpus
    only" -- safe because the corpus existed. Without it, the same permissive shape means no tenant
    condition at all: every tenant's chunks, to a caller who supplied nothing.

    Must be a real `qdrant_client.models.Filter`. `QdrantVectorStore`'s dict shorthand supports only
    flat equality (no `$in`/`$and`) and is deprecated by the library; getting that wrong does not
    error, it silently breaks tenant scoping. `must=[...]` is the AND, `MatchAny` the IN, and
    LangChain nests metadata under a `metadata` payload key -- hence the `metadata.` prefix.
    """
    if not tenant_id:
        msg = "tenant_id is required: an absent tenant would build a filter matching every tenant"
        raise ValueError(msg)
    must = [FieldCondition(key="metadata.tenant_id", match=MatchValue(value=tenant_id))]
    if chunk_types:
        must.append(FieldCondition(key="metadata.chunk_type", match=MatchAny(any=chunk_types)))
    if versions is not None:
        # ANDed, never replacing the others. This is the third condition whose omission is
        # *silent* rather than an error, and the one that decides whether a superseded generation
        # of points is readable -- so it is built here rather than left to callers to remember.
        if not versions:
            msg = "versions is empty: refusing to build a filter that would match every generation"
            raise ValueError(msg)
        must.append(FieldCondition(key="metadata.ingestion_version", match=MatchAny(any=versions)))
    if doc_ids is not None:
        # `is not None`, not truthiness: an empty list means "no document is permitted", and under
        # `if doc_ids:` it fell through to no document condition at all -- i.e. every document the
        # tenant owns. Callers now pass the tenant's *ingested* set here, so that difference is the
        # difference between searching nothing and searching documents the registry says failed.
        if not doc_ids:
            msg = "doc_ids is empty: refusing to build a filter that would match every document"
            raise ValueError(msg)
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
        _ensure_payload_indexes(self._store.client, self._store.collection_name)

    def delete_document(self, doc_id: str, tenant_id: str) -> None:
        """Remove every point belonging to `doc_id` within one tenant, whatever its chunk ids were.

        `tenant_id` is required, not optional, and it is ANDed into the selector rather than
        checked by the caller. Today `doc_id` is tenant-salted so a cross-tenant delete is
        not reachable -- but that is a property of `upload_doc_id`, enforced in a different
        module, and every read path in this file carries the tenant condition regardless.
        A write that can erase data deserves at least the guard a read has: if the id scheme
        ever changes, this fails closed instead of deleting a stranger's points.

        Deletes **every** generation of the document, so this is not the re-ingest path -- see
        `delete_superseded`, which keeps the active one. No production caller today; it exists for
        the planned delete endpoint (`docs/EPIC_4_PLAN.md` 5.5).
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

    def delete_superseded(self, doc_id: str, tenant_id: str, keep_version: str) -> None:
        """Drop every generation of `doc_id` except `keep_version`.

        Returns nothing, and deliberately does not report how many points went: Qdrant's delete
        answers with an operation status, not a count, so the only honest number would need a
        `count` before and after. The caller logs and moves on either way.

        Hygiene, not correctness, and the distinction is the point: a superseded generation is
        already unreadable because `_build_filter` admits only active versions, so a failure here
        leaves points that cost storage and nothing else. Callers log and continue rather than
        failing an ingest that has already published successfully.

        `must_not` rather than a second `must`: the selector is "this document, this tenant, any
        version but the live one". Getting that inverted deletes exactly the generation that is
        serving reads, so the tenant condition is ANDed in for the same reason `delete_document`
        carries it -- a write that can erase data gets at least the guard a read has.
        """
        result = self._store.client.delete(
            collection_name=self._store.collection_name,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(key="metadata.doc_id", match=MatchValue(value=doc_id)),
                        FieldCondition(key="metadata.tenant_id", match=MatchValue(value=tenant_id)),
                    ],
                    must_not=[FieldCondition(key="metadata.ingestion_version", match=MatchValue(value=keep_version))],
                )
            ),
        )
        log.info("qdrant.superseded_pruned", doc_id=doc_id, keep_version=keep_version, status=str(result.status))

    def upsert(self, chunks: list[Chunk], ingestion_version: str) -> None:
        """Insert one generation of a document's points, deleting **nothing**.

        This replaced delete-then-insert. The old shape made a document's correctness depend on
        a delete having succeeded: if the delete landed and the insert failed, a working document
        lost its points while its registry row still said `ingested`, so retrieval permitted the
        `doc_id` and found nothing -- and an unscoped question was answered from the tenant's
        *other* documents with no indication.

        Now nothing is destroyed here. `ingestion_version` is hashed into every point id, so this
        generation cannot collide with the previous one, and both coexist until Postgres flips
        which is active (`registry.db.activate_document_version`). That flip is the commit point;
        this method publishes nothing on its own.

        **`ingestion_version` is a parameter, not a field on `Chunk`.** It describes the *attempt*,
        not the chunk -- and as a scalar it makes a mixed-version batch impossible rather than
        something a guard has to catch.

        The doc_id/tenant guards remain: one call is one document for one tenant, which is how both
        callers use it, and `delete_superseded` derives its selector the same way.
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

        documents = [_to_document(chunk, ingestion_version) for chunk in chunks]
        self._store.add_documents(documents, ids=[_point_id(chunk.chunk_id, ingestion_version) for chunk in chunks])

    async def query(  # noqa: PLR0913 -- each parameter is one filter condition; see below
        self,
        query: str,
        top_k: int,
        tenant_id: str,
        *,
        chunk_types: list[str] | None = None,
        doc_ids: list[str] | None = None,
        versions: list[str] | None = None,
    ) -> list[Document]:
        # Six parameters, and bundling three of them into a filter object is the obvious tidy-up
        # that must not happen: each one is a condition `_build_filter` ANDs into the security
        # boundary, and a bundle makes "the caller forgot `versions`" and "the caller passed a
        # filter with no version condition" the same call site. Keyword-only from `tenant_id` on,
        # so no condition can be supplied positionally into the wrong slot.
        #
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
        where = _build_filter(chunk_types, tenant_id, doc_ids, versions)
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
