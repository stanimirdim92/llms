"""Pins filename-based question scoping.

Three failure modes matter here and they are not equally loud:

1. **Silent over-matching.** A tenant owning `data.pdf` asking "what data does the study
   use?" must NOT have its search narrowed to that file. There is no error when this goes
   wrong -- just a confident answer drawn from one document instead of the corpus, which is
   indistinguishable from a correct one.
2. **Silent under-matching.** A named document that stops resolving reverts to an unscoped
   search, which also answers successfully and also looks fine.
3. **Cross-tenant resolution.** `doc_id` is a content hash, so two tenants uploading the same
   bytes share one. Matching a filename against the wrong tenant's rows would resolve to
   their document.

All of it is pure -- no Postgres, no Qdrant, no API keys -- so it runs everywhere.
"""

from __future__ import annotations

from qdrant_client.models import FieldCondition, Filter

from app.registry.models import DocumentRecord
from app.retrieval.document_scope import mentions_a_filename, resolve_scope
from app.vectorstore.qdrant_store import _build_filter

TENANT = "t" * 32


def _condition_keys(where: Filter) -> list[str]:
    """The payload keys a built filter constrains on.

    `Filter.must` is typed as one condition, a list of them, or `None`, and most of the
    condition kinds in that union carry no `key` -- so reading `.key` straight off it is not
    statically safe. The `None` case is asserted rather than skipped because a filter with no
    conditions matches every tenant's chunks, which is the leak these tests exist to catch.
    """
    must = where.must
    assert must is not None, "an unconditioned filter matches every tenant's chunks"
    conditions = must if isinstance(must, list) else [must]
    return [condition.key for condition in conditions if isinstance(condition, FieldCondition)]


def _Record(doc_id: str, filename: str) -> DocumentRecord:
    """A real `DocumentRecord`, not a stand-in.

    A local dataclass with just `doc_id`/`filename` would type-check against nothing and
    would silently stop matching the model it stands for -- which is how a test keeps passing
    after the thing it tests has changed shape.
    """
    return DocumentRecord(
        doc_id=doc_id,
        tenant_id=TENANT,
        filename=filename,
        content_hash=doc_id,
        file_extension=".pdf",
        file_size_bytes=1,
    )


_RECORDS = [
    _Record("doc-flyer", "3020072D.pdf"),
    _Record("doc-cv", "Stanimir_Dimitrov_CV.pdf"),
    _Record("doc-data", "data.pdf"),
]


def test_a_named_document_scopes_the_search() -> None:
    scope = resolve_scope("give me the contents of document 3020072D.pdf", _RECORDS)

    assert scope.doc_ids == ["doc-flyer"]
    assert scope.filenames == ["3020072D.pdf"]
    assert scope.is_scoped


def test_matching_is_case_insensitive() -> None:
    """Users retype names; the stored casing should not decide whether scoping works."""
    assert resolve_scope("summarise 3020072d.PDF please", _RECORDS).doc_ids == ["doc-flyer"]


def test_two_named_documents_scope_to_both() -> None:
    scope = resolve_scope("compare 3020072D.pdf and Stanimir_Dimitrov_CV.pdf", _RECORDS)

    assert scope.doc_ids == ["doc-flyer", "doc-cv"]


def test_a_word_that_is_also_a_stem_does_not_scope() -> None:
    """The whole reason the extension is required.

    Bare-stem matching would narrow this question to `data.pdf` and answer from it alone,
    with nothing in the response or logs indicating that it had done so.
    """
    scope = resolve_scope("what data does the study use?", _RECORDS)

    assert scope.doc_ids == []
    assert scope.unknown == []
    assert not scope.is_scoped


def test_an_unknown_filename_is_reported_not_ignored() -> None:
    """Falling back to an unscoped search here is the dangerous behaviour: the caller asked
    about one document and would get a confident answer about a different one.
    """
    scope = resolve_scope("tell me about MISSING.pdf", _RECORDS)

    assert scope.doc_ids == []
    assert scope.unknown == ["MISSING.pdf"]
    assert scope.names_nothing_owned


def test_a_known_and_an_unknown_name_still_scopes_to_the_known_one() -> None:
    scope = resolve_scope("compare 3020072D.pdf with MISSING.pdf", _RECORDS)

    assert scope.doc_ids == ["doc-flyer"]
    assert scope.unknown == ["MISSING.pdf"]
    assert not scope.names_nothing_owned, "a partial match must not read as 'you own nothing named'"


def test_trailing_punctuation_is_not_part_of_the_name() -> None:
    assert resolve_scope("what is in 3020072D.pdf?", _RECORDS).doc_ids == ["doc-flyer"]


def test_a_longer_extension_is_not_truncated_to_a_shorter_one() -> None:
    """`report.pdf` must not match a question naming `report.pdfx` -- the word boundary."""
    assert resolve_scope("about report.pdfx", [_Record("d", "report.pdf")]).doc_ids == []


def test_another_tenants_filename_does_not_resolve() -> None:
    """The caller's rows are the only candidate set, which is what makes this safe: passing
    tenant B's records means tenant A's filename resolves to nothing, not to A's doc_id.
    """
    scope = resolve_scope("summarise 3020072D.pdf", [_Record("doc-b", "unrelated.pdf")])

    assert scope.doc_ids == []
    assert scope.names_nothing_owned


def test_duplicate_mentions_scope_once() -> None:
    scope = resolve_scope("in 3020072D.pdf, and again in 3020072D.pdf", _RECORDS)

    assert scope.doc_ids == ["doc-flyer"]


def test_pre_check_avoids_the_registry_read_for_ordinary_questions() -> None:
    """`/ask` is the hot path; the pre-check is what stops it querying Postgres per request."""
    assert not mentions_a_filename("what cathode materials show the highest cycling stability?")
    assert mentions_a_filename("what is in 3020072D.pdf")


def test_scoped_filter_keeps_the_tenant_condition() -> None:
    """The doc_id condition is ANDed with the tenant condition, never substituted for it.

    A scoped filter that dropped tenant scoping would return any tenant's chunks for a
    content-hash id -- and `doc_id` is a content hash, so two tenants uploading the same file
    share one. Asserted on the built filter because a wrong filter here returns data rather
    than raising.
    """
    keys = _condition_keys(_build_filter(None, "tenant-a", ["doc-flyer"]))

    assert "metadata.tenant_id" in keys
    assert "metadata.doc_id" in keys


def test_unscoped_filter_is_unchanged() -> None:
    """No doc_ids must produce exactly the filter that shipped before scoping existed."""
    assert _condition_keys(_build_filter(None, "tenant-a")) == ["metadata.tenant_id"]
