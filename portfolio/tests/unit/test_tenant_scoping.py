"""The retrieval security boundary.

`_build_filter` is the only thing preventing one tenant from reading another's documents,
and it fails *silently* when wrong -- a bad filter returns results rather than raising. So
these assert on the constructed filter directly, which needs no live Qdrant and therefore
runs on every commit.
"""

import pytest
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from app.ingestion.uploads import upload_doc_id
from app.vectorstore.qdrant_store import _build_filter


def _tenants_in(where: Filter) -> list[str]:
    """The tenant values a filter permits -- what actually decides who can read what.

    Returns a list even though the answer is now always exactly one value, and that is the
    point: it makes "how many tenants does this filter admit?" a question the caller can
    assert on. A helper returning a bare string would make a filter that widened to two
    tenants unrepresentable here, so the widening would show up as a passing test.

    The asserts narrow `Filter.must`, which is typed as an optional union of several condition
    kinds. They double as the test: if the tenant condition ever stops being the first
    `FieldCondition` on `metadata.tenant_id`, these fail rather than silently reading the wrong
    condition and passing. `MatchAny` is accepted as well as `MatchValue` for the same reason --
    a switch back to a list must be *visible* to the assertions, not rejected by the helper
    before they run.
    """
    must = where.must
    assert isinstance(must, list)
    condition = must[0]
    assert isinstance(condition, FieldCondition)
    assert condition.key == "metadata.tenant_id"
    match = condition.match
    if isinstance(match, MatchValue):
        return [str(match.value)]
    assert isinstance(match, MatchAny), f"unexpected tenant match kind: {type(match).__name__}"
    return [str(value) for value in match.any]


def test_the_filter_admits_exactly_one_tenant() -> None:
    """Exactly one, asserted as a whole-filter equality so an extra condition cannot slip in.

    This replaced two tests that asserted the filter matched `["global", tenant]` -- the shared
    corpus, readable by everyone. That corpus is gone, and the assertion here is deliberately
    the strictest form available: `MatchValue`, one value, nothing else in `must`.
    """
    where = _build_filter(chunk_types=None, tenant_id="abc123")

    assert where == Filter(must=[FieldCondition(key="metadata.tenant_id", match=MatchValue(value="abc123"))])


def test_tenant_cannot_reach_another_tenants_documents() -> None:
    """The whole point of Phase 1. Tenant A's filter must not admit tenant B's chunks.

    Asserts the permitted set *exactly*, not `a in / b not in`. The weaker form passed while the
    filter also admitted a third value, which is how the shared corpus was invisible here for
    months: it was permitted, correctly at the time, and no assertion mentioned it either way.
    """
    tenant_a, tenant_b = "a" * 32, "b" * 32

    permitted = _tenants_in(_build_filter(chunk_types=None, tenant_id=tenant_a))

    assert permitted == [tenant_a], f"filter admits more than its own tenant: {permitted}"
    assert tenant_b not in permitted


@pytest.mark.parametrize("missing", ["", None])
def test_a_missing_tenant_is_refused_rather_than_matching_everything(missing: str | None) -> None:
    """The failure mode created by deleting the shared corpus, closed at the same time.

    `tenant_id=None` used to be meaningful -- "corpus only" -- and safe, because the corpus was a
    real tenant tag. With the corpus gone, the same permissive signature would mean "build a
    filter with no tenant condition", i.e. every tenant's chunks returned to a caller who
    supplied nothing. Silently, since a filter that is too wide returns rows instead of raising.

    Raising is the only defensible reading. Delete the guard in `_build_filter` and this goes red.
    """
    with pytest.raises(ValueError, match="tenant_id is required"):
        _build_filter(chunk_types=None, tenant_id=missing)  # ty: ignore[invalid-argument-type]


def test_chunk_types_narrow_without_widening_tenant_scope() -> None:
    """A chunk-type filter must AND with the tenant condition, never replace it -- dropping
    the tenant condition while adding another would read as 'filtered' but leak everything.
    """
    where = _build_filter(chunk_types=["table", "figure"], tenant_id="abc123")

    assert where == Filter(
        must=[
            FieldCondition(key="metadata.tenant_id", match=MatchValue(value="abc123")),
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
