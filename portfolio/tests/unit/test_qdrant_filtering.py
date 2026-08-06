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
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from qdrant_client import QdrantClient, models

from app.ingestion.models import Chunk, ChunkType
from app.vectorstore.qdrant_store import (
    QdrantStore,
    _build_filter,
    _chunk_metadata,
    _ensure_payload_indexes,
    _point_id,
)

if TYPE_CHECKING:
    from langchain_qdrant import QdrantVectorStore

VECTOR_SIZE = 4
VERSION = "v" * 32
"""One generation, for the tests that do not care which. The ones that do define their own."""

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


def _insert(qdrant: QdrantClient, *chunks: Chunk, version: str = VERSION) -> None:
    """Writes one generation, exactly as `QdrantStore.upsert` does -- id and payload both derived
    from the same `version`, because splitting them is the one way this design breaks silently.
    """
    qdrant.upsert(
        "test",
        points=[
            models.PointStruct(
                id=_point_id(chunk.chunk_id, version),
                vector=[1.0] * VECTOR_SIZE,
                payload={"page_content": chunk.text, "metadata": _chunk_metadata(chunk, version)},
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


def test_point_ids_are_collision_free_within_a_generation_and_across_them() -> None:
    """Qdrant rejects arbitrary strings as point ids, so `_point_id` derives a uuid5 -- but *of
    what* is the design, not a detail.

    Within one `ingestion_version` it is deterministic, so re-running an interrupted ingest
    overwrites rather than duplicating. Across versions the same chunk id deliberately maps to a
    *different* point, which is what lets two generations coexist while Postgres decides which is
    live. Collapse the version out of the derivation and the new insert overwrites the old points in
    place: the insert becomes the delete, and there is nothing to fall back to when it fails.
    """
    other_version = "w" * 32
    assert _point_id("doc-text-0000", VERSION) == _point_id("doc-text-0000", VERSION)
    assert _point_id("doc-text-0000", VERSION) != _point_id("doc-text-0001", VERSION)
    assert _point_id("doc-text-0000", VERSION) != _point_id("doc-text-0000", other_version)
    uuid.UUID(str(_point_id("doc-text-0000", VERSION)))  # raises if it isn't a valid UUID


def test_a_shorter_re_ingest_leaves_no_readable_stale_points(client: QdrantClient) -> None:
    """The contract that replaced delete-then-insert, executed against the real engine.

    Chunk ids encode position, so a document that yields fewer chunks the second time (a different
    `chunk_max_tokens`, a Docling upgrade, one more figure detected) used to leave the
    higher-numbered points behind -- still matching the tenant filter, still retrievable, now stale.
    A delete before the insert was the old fix and cost a document its points whenever the insert
    that followed failed.

    Nothing is deleted here. Both generations are present and only the active one is *readable*,
    which is the whole trade: storage for the ability to fall back. The count assertion is the half
    that would otherwise go untested -- an implementation that quietly deleted would satisfy the
    visibility assertion perfectly.
    """
    new_version = "n" * 32
    _insert(client, *(_chunk(doc_id="doc-a", tenant_id=TENANT_A, index=i) for i in range(3)))
    _insert(client, _chunk(doc_id="doc-a", tenant_id=TENANT_A, index=0), version=new_version)

    visible = _search(client, _build_filter(None, TENANT_A, versions=[new_version]))

    assert visible == ["doc-a-text-0000"], "a superseded generation's points were readable"
    assert client.count("test", exact=True).count == 4, "the superseded points must still be there to fall back to"


def test_omitting_the_version_condition_readmits_every_generation(client: QdrantClient) -> None:
    """The inverse, pinning *why* `versions=` is not optional -- and it is the dangerous kind of
    optional, because omitting it returns more data rather than raising.

    A retrieval path that forgot the condition would answer from three generations of one document
    at once: the same passage two or three times, differing wherever the chunker did, ranked against
    each other. The tenant filter alone does not exclude any of it.
    """
    _insert(client, *(_chunk(doc_id="doc-a", tenant_id=TENANT_A, index=i) for i in range(3)))
    _insert(client, _chunk(doc_id="doc-a", tenant_id=TENANT_A, index=0), version="n" * 32)

    assert len(_search(client, _build_filter(None, TENANT_A))) == 4


# The empty-`versions` guard is pinned in `test_retrieval_consistency.py`, next to its `doc_ids`
# twin, and deliberately not here: it is an assertion about a raise, and this engine cannot
# strengthen it. Probed -- `MatchAny(any=[])` returns zero points, so the dangerous mutation
# (`if versions:`, which emits no condition at all) is invisible to any query-based test.


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
        store.upsert(mixed, VERSION)


def test_upsert_still_refuses_a_batch_spanning_two_documents() -> None:
    """The pre-existing guard, kept under test so adding the tenant one didn't displace it."""
    store = QdrantStore.__new__(QdrantStore)
    mixed = [
        _chunk(doc_id="doc-a", tenant_id=TENANT_A, index=0),
        _chunk(doc_id="doc-b", tenant_id=TENANT_A, index=0),
    ]

    with pytest.raises(ValueError, match="exactly one document"):
        store.upsert(mixed, VERSION)


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

    # `QdrantStore.delete_document`, not a hand-built filter. An earlier version of this test
    # constructed the same selector inline and called `client.delete` directly -- so it
    # exercised qdrant-client and not the change, and passed with the tenant condition
    # deleted from `qdrant_store.py`. Rule 15: a test that survives the feature's removal is
    # documentation.
    store = QdrantStore.__new__(QdrantStore)  # no __init__: it bills a probe embedding
    # `cast` because the stand-in only needs the two attributes `delete_document` touches;
    # a real QdrantVectorStore would need a live server and a billed probe embedding.
    store._store = cast("QdrantVectorStore", SimpleNamespace(client=client, collection_name="test"))

    store.delete_document("collide", TENANT_A)

    assert _search(client, _build_filter(None, TENANT_A)) == []
    assert _search(client, _build_filter(None, TENANT_B)) == ["collide-text-0001"]


def test_pruning_keeps_the_live_generation_and_drops_the_rest(client: QdrantClient) -> None:
    """`delete_superseded` is the only delete on the ingest path, and its selector is inverted
    (`must_not` the version to keep) -- so getting it backwards deletes precisely the generation
    that is serving reads, which is the one way this design can lose data.

    Driven through the real method rather than a hand-built selector, because a hand-built copy
    passes with the production selector broken. Three generations, so "keeps the live one" is
    distinguishable from "keeps the newest" and from "keeps one arbitrarily".

    The bystander is another tenant holding the **same `doc_id`**, not a different document -- with a
    different id the `doc_id` condition alone protects it and the test passes with the tenant
    condition deleted. Verified by mutation: that was this test's first shape.
    """
    live = "n" * 32
    superseded = "1" * 32
    for version, index in ((superseded, 0), ("2" * 32, 1), (live, 2)):
        _insert(client, _chunk(doc_id="doc-a", tenant_id=TENANT_A, index=index), version=version)
    _insert(client, _chunk(doc_id="doc-a", tenant_id=TENANT_B, index=9), version=superseded)
    assert client.count("test", exact=True).count == 4

    store = QdrantStore.__new__(QdrantStore)  # no __init__: it bills a probe embedding
    store._store = cast("QdrantVectorStore", SimpleNamespace(client=client, collection_name="test"))

    store.delete_superseded("doc-a", TENANT_A, live)

    assert _search(client, _build_filter(None, TENANT_A, versions=[live])) == ["doc-a-text-0002"]
    assert _search(client, _build_filter(None, TENANT_B, versions=[superseded])) == ["doc-a-text-0009"], (
        "another tenant's points were pruned by a delete scoped to this tenant's document"
    )
    assert client.count("test", exact=True).count == 2, "both of this tenant's superseded points should be gone"


def test_the_tenant_field_is_indexed_as_a_tenant_field() -> None:
    """`is_tenant=True` on `metadata.tenant_id`, which is the whole point of the index.

    Plain "indexed" is not enough and this is why the assertion targets the flag rather than
    the field list: `is_tenant` tells Qdrant the field identifies tenants, so a tenant's
    vectors are stored together and a tenant-filtered search is served by sequential reads.
    Without it, the tenant filter degrades toward a scan as the collection grows -- invisible
    at six documents, and the target is 10k tenants x 10 documents (order 1M points).
    `qdrant-scaling` lists omitting it under things not to do.

    **This asserts the calls, not the effect, and that is a real limitation.** `qdrant_client`'s
    local mode warns "Payload indexes have no effect in the local Qdrant" and leaves
    `payload_schema` empty, so the in-memory engine the rest of this file uses cannot observe an
    index at all. The effect was verified once against a real `qdrant/qdrant:v1.18.3` container
    -- `metadata.tenant_id` came back `data_type=keyword, is_tenant=True` -- and that is
    recorded in `docs/TECHNICAL_DECISIONS.md` rather than re-run here.
    """
    calls: list[tuple[str, object]] = []

    class _Recorder:
        def create_payload_index(self, *, collection_name: str, field_name: str, field_schema: object) -> None:
            assert collection_name == "kb"
            calls.append((field_name, field_schema))

    _ensure_payload_indexes(cast("QdrantClient", _Recorder()), "kb")

    indexed = dict(calls)
    assert set(indexed) == {"metadata.tenant_id", "metadata.doc_id"}, (
        f"unexpected set of indexed fields: {sorted(indexed)}"
    )
    assert getattr(indexed["metadata.tenant_id"], "is_tenant", None) is True, (
        "metadata.tenant_id must be indexed with is_tenant=True, not merely indexed"
    )
    assert getattr(indexed["metadata.doc_id"], "is_tenant", None) is False, (
        "only the tenant field is a tenant field; is_tenant on doc_id would co-locate by document"
    )
    # Not indexed on purpose: `_build_filter` accepts `chunk_types` but no production caller
    # passes it, so an index would cost write amplification on every upsert to serve nothing.
    assert "metadata.chunk_type" not in indexed


def test_a_failed_index_creation_does_not_stop_the_store_from_constructing() -> None:
    """An index is a performance property, not a correctness one.

    The filters return exactly the same points unindexed, just more slowly, so a Qdrant that
    refuses `create_payload_index` must not take the api down at startup -- same reasoning as the
    rate limiter failing open. The loud log is what keeps it from being silent.

    Both fields are attempted even when the first fails, which is the part a naive
    try/except around the whole loop would get wrong: one unsupported field would silently
    cost the other its index.
    """
    attempted: list[str] = []

    class _Broken:
        def create_payload_index(self, *, collection_name: str, field_name: str, field_schema: object) -> None:
            attempted.append(field_name)
            msg = "index creation refused"
            raise RuntimeError(msg)

    _ensure_payload_indexes(cast("QdrantClient", _Broken()), "kb")  # must not raise

    assert attempted == ["metadata.tenant_id", "metadata.doc_id"], (
        f"a failure on one field skipped the others: {attempted}"
    )
