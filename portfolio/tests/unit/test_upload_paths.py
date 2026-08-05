"""Filesystem hardening on the upload path.

Client-supplied filenames were joined straight onto a directory, so `../../evil.py` wrote
outside the upload root -- an arbitrary file write. These helpers live in
`ingestion/uploads.py` rather than the router because the Streamlit UI writes to disk in
process too and needs the identical checks.
"""

from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from app.config import get_settings
from app.ingestion import pipeline
from app.ingestion.pipeline import ContentMismatchError
from app.ingestion.uploads import (
    content_digest,
    document_upload_path,
    safe_filename,
    tenant_upload_dir,
    upload_doc_id,
    write_upload,
)

if TYPE_CHECKING:
    from app.vectorstore.qdrant_store import QdrantStore

_VALID_TENANT = "a" * 32
_OTHER_TENANT = "b" * 32


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("paper.pdf", "paper.pdf"),
        ("../../../etc/passwd", "passwd"),
        ("../../evil.py", "evil.py"),
        ("subdir/paper.pdf", "paper.pdf"),
        ("/absolute/paper.pdf", "paper.pdf"),
    ],
)
def test_directory_components_are_stripped(supplied: str, expected: str) -> None:
    assert safe_filename(supplied) == expected


@pytest.mark.parametrize("supplied", [None, "", "..", ".", "/", ".hidden", "../"])
def test_unusable_filenames_are_refused(supplied: str | None) -> None:
    """`..` and `/` reduce to an empty or dot-only name -- refuse rather than invent one."""
    with pytest.raises(ValueError, match="filename"):
        safe_filename(supplied)


def test_upload_dir_is_inside_the_configured_root() -> None:
    root = get_settings().upload_dir.resolve()

    assert tenant_upload_dir(root, _VALID_TENANT).is_relative_to(root)


@pytest.mark.parametrize(
    "tenant_id",
    ["../escape", "..", "a" * 31, "a" * 33, "A" * 32, "g" * 32, "", "a/b", "a" * 16 + "/" + "b" * 15],
)
def test_malformed_tenant_ids_never_become_paths(tenant_id: str) -> None:
    """Tenant ids are server-issued, so this should be unreachable -- which is the point.
    If it ever becomes reachable, it fails loudly here instead of escaping the upload root.
    """
    with pytest.raises(ValueError, match="tenant id"):
        tenant_upload_dir(get_settings().upload_dir, tenant_id)


def test_the_content_digest_is_unsalted_and_shorter_than_the_doc_id() -> None:
    """`content_hash` had two incompatible meanings in one column.

    The router stored the tenant-salted 32-char `doc_id` on the pending row; `ingest_document`
    overwrote it with a plain 16-char sha256 on the terminal write. Same column, two values of
    different lengths and different meanings, reconciled only by whichever write happened last.
    Harmless while nothing reads the field -- which is exactly the state in which a column
    quietly becomes unusable, because the first reader inherits both conventions.

    One function now, called by both. Asserting it is *not* the doc_id is the load-bearing half:
    that is the value the bug wrote.
    """
    payload = b"%PDF-1.4 the same bytes"

    digest = content_digest(payload)

    assert digest == content_digest(payload), "deterministic"
    assert digest != upload_doc_id(_VALID_TENANT, payload), "the id is salted; this is not"
    # Length is the load-bearing part of the L4 story: the bug stored the 65-char `doc_id` in a
    # column the other writer filled with a 16-char digest.
    assert len(digest) == 16
    assert len(upload_doc_id(_VALID_TENANT, payload)) == 65


def test_two_tenants_uploading_the_same_bytes_share_a_content_digest_but_not_an_id() -> None:
    """The two fields answer different questions, and this is the difference.

    `doc_id` is identity *and* isolation -- salted, so tenant A's id is unguessable from the file.
    `content_hash` answers the one thing the id cannot: did the bytes change while the id stayed
    the same? That happens on a revised arXiv paper, where `doc_id` is the arXiv id rather than a
    hash of the content.
    """
    payload = b"%PDF-1.4 identical"

    assert content_digest(payload) == content_digest(payload)
    assert upload_doc_id(_VALID_TENANT, payload) != upload_doc_id(_OTHER_TENANT, payload)


# --- Two documents, one filename: the content-swap defect (found in review, 2026-08-05) ---
#
# The path was `<root>/<tenant>/<filename>`, so two different documents named `report.pdf`
# shared one path. The worker for A read whatever was there and filed B's content under A's
# doc_id, recording B's hash as A's -- so nothing afterwards looked wrong. These pin the two
# halves of the fix: an immutable path, and a fail-closed digest check.


def test_two_documents_with_one_filename_do_not_share_a_path() -> None:
    """The defect, stated as an assertion.

    Delete `doc_id` from `document_upload_path` and this is the test that goes red -- the two
    paths become equal and the second write silently replaces the first document's bytes.
    """
    root = Path("/tmp/uploads")
    a_bytes, b_bytes = b"contents of document A", b"entirely different bytes"

    a_id = upload_doc_id(_VALID_TENANT, a_bytes)
    b_id = upload_doc_id(_VALID_TENANT, b_bytes)
    assert a_id != b_id, "different bytes must yield different ids, or the premise is wrong"

    a_path = document_upload_path(root, _VALID_TENANT, a_id, "report.pdf")
    b_path = document_upload_path(root, _VALID_TENANT, b_id, "report.pdf")

    assert a_path != b_path
    assert a_path.name == b_path.name == "report.pdf", (
        "the filename must survive as the leaf: chunk metadata stores it and "
        "retrieval/document_scope.py matches a question against it"
    )


def test_the_same_bytes_still_resolve_to_one_path() -> None:
    """The property the old layout was relied on for, which must not regress.

    Re-uploading identical content is an *update*, not a duplicate -- same `doc_id`, same path,
    overwritten in place. If this broke, every re-upload would orphan its predecessor's bytes.
    """
    payload = b"identical every time"
    doc_id = upload_doc_id(_VALID_TENANT, payload)
    first = document_upload_path(Path("/tmp/uploads"), _VALID_TENANT, doc_id, "report.pdf")
    second = document_upload_path(Path("/tmp/uploads"), _VALID_TENANT, doc_id, "report.pdf")
    assert first == second


def test_one_tenants_document_directory_cannot_escape_into_anothers() -> None:
    """`doc_id` is server-derived, but it reaches a path -- so the containment check is real."""
    payload = b"x"
    mine = document_upload_path(Path("/tmp/uploads"), _VALID_TENANT, upload_doc_id(_VALID_TENANT, payload), "a.pdf")
    theirs = document_upload_path(Path("/tmp/uploads"), _OTHER_TENANT, upload_doc_id(_OTHER_TENANT, payload), "a.pdf")
    assert _VALID_TENANT in str(mine)
    assert not str(mine).startswith(str(theirs.parent.parent))


def test_a_write_is_never_visible_half_finished(tmp_path: Path) -> None:
    """`write_upload` renames into place, so a worker never reads a partial document.

    Also asserts the staging file is cleaned up: a leftover `.name.partial` would be picked up by
    nothing (`safe_filename` refuses leading dots) but would waste disk on every upload.
    """
    path = document_upload_path(tmp_path, _VALID_TENANT, upload_doc_id(_VALID_TENANT, b"z"), "report.pdf")
    write_upload(path, b"complete contents")

    assert path.read_bytes() == b"complete contents"
    assert list(path.parent.glob(".*.partial")) == []


async def test_ingestion_refuses_bytes_that_changed_after_acceptance(tmp_path: Path) -> None:
    """Fail closed, and fail *before* parsing.

    The check has to precede the parse because `_parse_and_chunk` caches the result at
    `processed_dir/<doc_id>.json`: verifying afterwards would detect the swap and still leave the
    wrong content cached under this doc_id, so a later correct re-ingest would read it again.
    """
    accepted = b"the bytes the upload accepted"
    swapped = b"somebody else's document"
    doc_id = upload_doc_id(_VALID_TENANT, accepted)
    path = document_upload_path(tmp_path, _VALID_TENANT, doc_id, "report.pdf")
    write_upload(path, swapped)

    with pytest.raises(ContentMismatchError) as excinfo:
        await pipeline.ingest_document(
            doc_id=doc_id,
            file_path=path,
            store=cast("QdrantStore", object()),
            tenant_id=_VALID_TENANT,
            expected_digest=content_digest(accepted),
        )

    assert "changed on disk" in str(excinfo.value)
    assert not (tmp_path / f"{doc_id}.json").exists(), "refused before the parse could cache anything"


async def test_matching_bytes_pass_the_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard must not reject the ordinary case -- otherwise it is just an outage.

    Stops at the empty-chunk refusal, which is far enough to prove the digest gate was passed.
    """
    payload = b"the very same bytes"
    doc_id = upload_doc_id(_VALID_TENANT, payload)
    path = document_upload_path(tmp_path, _VALID_TENANT, doc_id, "report.pdf")
    write_upload(path, payload)

    monkeypatch.setattr(pipeline, "parse_document", lambda *_a, **_k: object())
    monkeypatch.setattr(pipeline, "save_parsed_document", lambda *_a, **_k: None)
    monkeypatch.setattr(pipeline, "extract_figures", lambda *_a, **_k: [])
    monkeypatch.setattr(pipeline, "chunk_document", lambda *_a, **_k: [])
    monkeypatch.setattr(pipeline.get_settings(), "processed_dir", tmp_path)

    with pytest.raises(pipeline.EmptyDocumentError):
        await pipeline.ingest_document(
            doc_id=doc_id,
            file_path=path,
            store=cast("QdrantStore", object()),
            tenant_id=_VALID_TENANT,
            expected_digest=content_digest(payload),
        )
