"""Pins filename- and doc_id-based question scoping.

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
from app.retrieval.document_scope import mentions_a_document, resolve_scope
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
    assert not mentions_a_document("what cathode materials show the highest cycling stability?")
    assert mentions_a_document("what is in 3020072D.pdf")


# --- doc_ids ---------------------------------------------------------------------------
#
# A regression suite before it is a feature suite. Asked for structured output "for document
# with id ... doc_id=019fb3eb...", the pre-check saw no filename, returned False, and the
# search ran unscoped: four of the five chunks that won reranking came from the tenant's CV
# rather than the named advertisement. Nothing errored -- the question was mostly Pydantic
# field descriptions, which embed closer to a CV's contact and profile sections than to a
# sparse one-page flyer.

_REAL_DOC_ID = "019fb3ebbd2370d08626ac2aa1a23c14-64a6d182c9e2359e66ba6ffc3c339cd7"
_ID_RECORDS = [_Record(_REAL_DOC_ID, "24383456-639402.pdf"), _Record("doc-cv", "Stanimir_Dimitrov_CV.pdf")]


def test_the_question_that_shipped_unscoped_now_scopes() -> None:
    """Verbatim shape of the real request, kept as the regression anchor."""
    question = (
        "This is the structured output i need for document with id class CompanyOutput(BaseModel): "
        'name: str = Field(description="The name of the company or entity") '
        f"doc_id={_REAL_DOC_ID}"
    )

    assert mentions_a_document(question), "the pre-check gates the registry read; False here means never scoped"
    scope = resolve_scope(question, _ID_RECORDS)
    assert scope.doc_ids == [_REAL_DOC_ID]
    assert scope.filenames == ["24383456-639402.pdf"], "scoped_to reports the name, not the id back"


def test_a_bare_doc_id_scopes_without_the_marker() -> None:
    """Pasted straight out of `GET /v1/documents`, which reports the id with no `doc_id=`."""
    assert resolve_scope(f"summarise {_REAL_DOC_ID}", _ID_RECORDS).doc_ids == [_REAL_DOC_ID]


def test_the_marker_accepts_the_spellings_people_type() -> None:
    for written in (f"doc_id={_REAL_DOC_ID}", f"doc id: {_REAL_DOC_ID}", f"docid = {_REAL_DOC_ID}"):
        assert resolve_scope(f"contents of {written}", _ID_RECORDS).doc_ids == [_REAL_DOC_ID], written


def test_the_marker_carries_an_id_shape_no_regex_could_find() -> None:
    """The curated corpus uses bare arXiv ids. `2008.10896` is indistinguishable from a
    decimal number in prose, so it only ever resolves behind an explicit marker -- which is
    the whole reason the marker exists alongside the shape pattern.
    """
    records = [_Record("2008.10896", "2008.10896.pdf")]

    assert resolve_scope("what does doc_id=2008.10896 conclude?", records).doc_ids == ["2008.10896"]
    assert not mentions_a_document("the cell retained 2008.10896 mAh/g"), "a bare decimal must not scope"


def test_an_unknown_doc_id_is_a_refusal_not_an_unscoped_search() -> None:
    """Same contract as an unknown filename: the caller named one document, so answering from
    a different one is worse than refusing.
    """
    scope = resolve_scope("doc_id=deadbeef" + "0" * 24 + "-" + "f" * 32, _ID_RECORDS)

    assert scope.doc_ids == []
    assert scope.names_nothing_owned


def test_another_tenants_doc_id_does_not_resolve() -> None:
    """The reason accepting a client-supplied id is safe. A `doc_id` embeds a tenant prefix and
    so looks authoritative, but it is matched against this caller's rows only -- passing tenant
    B's records means A's id resolves to nothing rather than to A's document.
    """
    scope = resolve_scope(f"doc_id={_REAL_DOC_ID}", [_Record("doc-b", "unrelated.pdf")])

    assert scope.doc_ids == []
    assert scope.names_nothing_owned


def test_a_filename_and_an_id_naming_one_document_scope_once() -> None:
    question = f"compare 24383456-639402.pdf with doc_id={_REAL_DOC_ID}"

    assert resolve_scope(question, _ID_RECORDS).doc_ids == [_REAL_DOC_ID]


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
