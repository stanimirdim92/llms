"""Tenant isolation proved against a real Qdrant engine, not against the filter's shape.

`test_tenant_scoping.py` asserts that `_build_filter` returns the right `Filter` object. That
catches a malformed filter but cannot catch a *correct-looking* filter that doesn't exclude what
it should -- a wrong payload key, a wrong nesting level, `should` where `must` was meant. Those
all produce a plausible object and leak data.

These run the query through `qdrant_client`'s in-memory engine, which is a genuine
implementation of Qdrant's payload filtering (verified: nested `metadata.tenant_id` keys and
`MatchAny` both behave). No server and no API keys, so this runs in CI, unlike the store's real
network path -- which is still untested and is where the point-ID constraint escaped to
production.

Embeddings are faked deliberately. Whether the filter excludes another tenant's chunk has
nothing to do with vector similarity, and requiring a Voyage key would put this back in the
"skipped in CI" category that let the original bugs through.
"""

from __future__ import annotations

import uuid

import pytest
from qdrant_client import QdrantClient, models

from app.ingestion.models import GLOBAL_TENANT, Chunk, ChunkType
from app.vectorstore.qdrant_store import QdrantStore, _build_filter, _chunk_metadata, _point_id

VECTOR_SIZE = 4
TENANT_A = "a" * 32
TENANT_B = "b" * 32


def _chunk(*, doc_id: str, tenant_id: str, index: int = 0, chunk_type: ChunkType = "text") -> Chunk:
    return Chunk(
        chunk_id=f"{doc_id}-{chunk_type}-{index:04d}",
        doc_id=doc_id,
        tenant_id=tenant_id,
        chunk_type=chunk_type,
        text=f"content of {doc_id} {chunk_type} {index}",
        section_path="Results",
        page_no=1,
    )


@pytest.fixture
def client() -> QdrantClient:
    """A real Qdrant engine, in process. Same payload layout the app writes: LangChain nests
    `Document.metadata` under a `metadata` payload key, which is why every filter key in
    `_build_filter` is prefixed `metadata.` -- get that wrong and nothing errors, the filter
    just matches nothing or everything.
    """
    qdrant = QdrantClient(location=":memory:")
    qdrant.create_collection(
        "test",
        vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
    )
    return qdrant


def _insert(qdrant: QdrantClient, *chunks: Chunk) -> None:
    qdrant.upsert(
        "test",
        points=[
            models.PointStruct(
                id=_point_id(chunk.chunk_id),
                vector=[1.0] * VECTOR_SIZE,
                payload={"page_content": chunk.text, "metadata": _chunk_metadata(chunk)},
            )
            for chunk in chunks
        ],
    )


def _search(qdrant: QdrantClient, query_filter: models.Filter | None) -> list[str]:
    hits = qdrant.query_points("test", query=[1.0] * VECTOR_SIZE, query_filter=query_filter, limit=50).points
    return [hit.payload["metadata"]["chunk_id"] for hit in hits if hit.payload]


def test_a_tenant_cannot_retrieve_another_tenants_chunk(client: QdrantClient) -> None:
    """The leak this whole boundary exists to prevent, executed rather than inspected."""
    _insert(
        client,
        _chunk(doc_id="doc-a", tenant_id=TENANT_A),
        _chunk(doc_id="doc-b", tenant_id=TENANT_B),
    )

    visible = _search(client, _build_filter(None, TENANT_A))

    assert visible == ["doc-a-text-0000"]


def test_the_shared_corpus_is_visible_to_every_tenant(client: QdrantClient) -> None:
    """`GLOBAL_TENANT` is readable by all and owned by none, so a tenant's own filter must match
    both its uploads and the corpus -- and still not the other tenant.
    """
    _insert(
        client,
        _chunk(doc_id="corpus", tenant_id=GLOBAL_TENANT),
        _chunk(doc_id="doc-a", tenant_id=TENANT_A),
        _chunk(doc_id="doc-b", tenant_id=TENANT_B),
    )

    visible = _search(client, _build_filter(None, TENANT_A))

    assert sorted(visible) == ["corpus-text-0000", "doc-a-text-0000"]


def test_no_tenant_filter_means_corpus_only(client: QdrantClient) -> None:
    """What an unauthenticated or corpus-only path should see: never a tenant's uploads."""
    _insert(
        client,
        _chunk(doc_id="corpus", tenant_id=GLOBAL_TENANT),
        _chunk(doc_id="doc-a", tenant_id=TENANT_A),
    )

    visible = _search(client, _build_filter(None, None))

    assert visible == ["corpus-text-0000"]


def test_chunk_type_narrows_within_the_tenant_not_across_it(client: QdrantClient) -> None:
    """Both conditions are ANDed. A `should` here instead of `must` would still build a valid
    Filter and would return the other tenant's tables.
    """
    _insert(
        client,
        _chunk(doc_id="doc-a", tenant_id=TENANT_A, chunk_type="text"),
        _chunk(doc_id="doc-a", tenant_id=TENANT_A, chunk_type="table"),
        _chunk(doc_id="doc-b", tenant_id=TENANT_B, chunk_type="table"),
    )

    visible = _search(client, _build_filter(["table"], TENANT_A))

    assert visible == ["doc-a-table-0000"]


def test_point_ids_are_deterministic_and_collision_free() -> None:
    """Qdrant rejects arbitrary strings as point ids, so `_point_id` derives a uuid5. Two
    properties matter: the same chunk id must always map to the same point (or re-ingestion
    would duplicate instead of overwrite), and different chunk ids must not collide.
    """
    assert _point_id("doc-text-0000") == _point_id("doc-text-0000")
    assert _point_id("doc-text-0000") != _point_id("doc-text-0001")
    uuid.UUID(str(_point_id("doc-text-0000")))  # raises if it isn't a valid UUID


def test_reingesting_fewer_chunks_leaves_no_stale_points(client: QdrantClient) -> None:
    """The delete-then-insert contract, executed.

    Chunk ids encode position, so a document that yields fewer chunks the second time (different
    `chunk_max_tokens`, a Docling upgrade, toggling `do_ocr`) leaves the higher-numbered points
    behind -- still matching the tenant filter, still retrievable, now stale. Upserting by id
    cannot fix that; only deleting by `doc_id` first can.
    """
    _insert(
        client,
        *(_chunk(doc_id="doc-a", tenant_id=TENANT_A, index=i) for i in range(3)),
    )
    assert len(_search(client, _build_filter(None, TENANT_A))) == 3

    # What QdrantStore.upsert does first: delete every point for the doc_id.
    client.delete(
        "test",
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key="metadata.doc_id", match=models.MatchValue(value="doc-a"))]
            )
        ),
    )
    _insert(client, _chunk(doc_id="doc-a", tenant_id=TENANT_A, index=0))

    visible = _search(client, _build_filter(None, TENANT_A))

    assert visible == ["doc-a-text-0000"], "stale points from the longer first ingest survived"


def test_without_the_delete_step_stale_points_survive(client: QdrantClient) -> None:
    """The inverse of the test above, pinning *why* the delete exists rather than trusting the
    comment. Re-inserting only the first chunk leaves the other two retrievable.
    """
    _insert(client, *(_chunk(doc_id="doc-a", tenant_id=TENANT_A, index=i) for i in range(3)))
    _insert(client, _chunk(doc_id="doc-a", tenant_id=TENANT_A, index=0))  # upsert, no delete

    assert len(_search(client, _build_filter(None, TENANT_A))) == 3


def test_upsert_refuses_a_batch_spanning_two_tenants() -> None:
    """The write-side guard. Without it the delete selector is derived from `doc_ids.pop()`
    alone, so a mixed batch erases whichever tenant's points happen to match -- a write path
    with less protection than every read path in the same file.

    Constructed without a live store: the guard runs before any client call, which is the
    point -- it must fail before deleting, not after.
    """
    store = QdrantStore.__new__(QdrantStore)  # no __init__: it bills a probe embedding
    mixed = [
        _chunk(doc_id="shared-id", tenant_id=TENANT_A, index=0),
        _chunk(doc_id="shared-id", tenant_id=TENANT_B, index=1),
    ]

    with pytest.raises(ValueError, match="exactly one tenant"):
        store.upsert(mixed)


def test_upsert_still_refuses_a_batch_spanning_two_documents() -> None:
    """The pre-existing guard, kept under test so adding the tenant one didn't displace it."""
    store = QdrantStore.__new__(QdrantStore)
    mixed = [
        _chunk(doc_id="doc-a", tenant_id=TENANT_A, index=0),
        _chunk(doc_id="doc-b", tenant_id=TENANT_A, index=0),
    ]

    with pytest.raises(ValueError, match="exactly one document"):
        store.upsert(mixed)


def test_the_delete_selector_carries_the_tenant(client: QdrantClient) -> None:
    """Two tenants holding the same `doc_id` -- unreachable today because `upload_doc_id`
    salts with the tenant, but that is enforced in another module. Deleting one tenant's
    document must not touch the other's, whatever the id scheme does later.
    """
    _insert(
        client,
        _chunk(doc_id="collide", tenant_id=TENANT_A, index=0),
        _chunk(doc_id="collide", tenant_id=TENANT_B, index=1),
    )

    client.delete(
        "test",
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(key="metadata.doc_id", match=models.MatchValue(value="collide")),
                    models.FieldCondition(key="metadata.tenant_id", match=models.MatchValue(value=TENANT_A)),
                ]
            )
        ),
    )

    assert _search(client, _build_filter(None, TENANT_A)) == []
    assert _search(client, _build_filter(None, TENANT_B)) == ["collide-text-0001"]
