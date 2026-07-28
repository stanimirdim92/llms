"""The retrieval security boundary.

`_build_filter` is the only thing preventing one tenant from reading another's documents,
and it fails *silently* when wrong -- a bad filter returns results rather than raising. So
these assert on the constructed filter directly, which needs no live Qdrant and therefore
runs on every commit.
"""

from qdrant_client.models import FieldCondition, Filter, MatchAny

from app.ingestion.models import GLOBAL_TENANT
from app.ingestion.uploads import upload_doc_id
from app.vectorstore.qdrant_store import _build_filter


def _tenants_in(where: Filter) -> list[str]:
    """The tenant values a filter permits -- what actually decides who can read what.

    The asserts narrow `Filter.must`, which is typed as an optional union of several
    condition kinds. They double as the test: if the tenant condition ever stops being the
    first `FieldCondition` on `metadata.tenant_id`, these fail rather than silently reading
    the wrong condition and passing.
    """
    must = where.must
    assert isinstance(must, list)
    condition = must[0]
    assert isinstance(condition, FieldCondition)
    assert condition.key == "metadata.tenant_id"
    match = condition.match
    assert isinstance(match, MatchAny)
    return [str(value) for value in match.any]


def test_no_tenant_searches_only_the_shared_corpus() -> None:
    where = _build_filter(chunk_types=None, tenant_id=None)

    assert where == Filter(must=[FieldCondition(key="metadata.tenant_id", match=MatchAny(any=["global"]))])


def test_tenant_sees_the_corpus_and_its_own_uploads() -> None:
    where = _build_filter(chunk_types=None, tenant_id="abc123")

    assert where == Filter(must=[FieldCondition(key="metadata.tenant_id", match=MatchAny(any=["global", "abc123"]))])


def test_tenant_cannot_reach_another_tenants_documents() -> None:
    """The whole point of Phase 1. Tenant A's filter must not admit tenant B's chunks."""
    tenant_a, tenant_b = "a" * 32, "b" * 32

    permitted = _tenants_in(_build_filter(chunk_types=None, tenant_id=tenant_a))

    assert tenant_a in permitted
    assert tenant_b not in permitted


def test_shared_corpus_stays_readable_by_every_tenant() -> None:
    for tenant_id in ("a" * 32, "b" * 32, None):
        assert GLOBAL_TENANT in _tenants_in(_build_filter(chunk_types=None, tenant_id=tenant_id))


def test_global_tenant_is_not_duplicated() -> None:
    where = _build_filter(chunk_types=None, tenant_id="global")

    assert where == Filter(must=[FieldCondition(key="metadata.tenant_id", match=MatchAny(any=["global"]))])


def test_chunk_types_narrow_without_widening_tenant_scope() -> None:
    """A chunk-type filter must AND with the tenant condition, never replace it -- dropping
    the tenant condition while adding another would read as 'filtered' but leak everything.
    """
    where = _build_filter(chunk_types=["table", "figure"], tenant_id="abc123")

    assert where == Filter(
        must=[
            FieldCondition(key="metadata.tenant_id", match=MatchAny(any=["global", "abc123"])),
            FieldCondition(key="metadata.chunk_type", match=MatchAny(any=["table", "figure"])),
        ]
    )


def test_upload_doc_id_is_deterministic_per_tenant_and_content() -> None:
    doc_id_a = upload_doc_id("tenant-1", b"same bytes")
    doc_id_b = upload_doc_id("tenant-1", b"same bytes")

    assert doc_id_a == doc_id_b
    assert doc_id_a.startswith("tenant-1-")


def test_upload_doc_id_differs_across_tenants_for_same_content() -> None:
    """Different ids *and* no shared suffix: comparing two tenants' ids must not reveal
    that they uploaded identical content.
    """
    doc_id_a = upload_doc_id("tenant-1", b"same bytes")
    doc_id_b = upload_doc_id("tenant-2", b"same bytes")

    assert doc_id_a != doc_id_b
    assert doc_id_a.split("-", 1)[1] != doc_id_b.split("-", 1)[1]


def test_upload_doc_id_differs_across_content_for_same_tenant() -> None:
    assert upload_doc_id("tenant-1", b"content a") != upload_doc_id("tenant-1", b"content b")
