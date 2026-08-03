"""Filesystem hardening on the upload path.

Client-supplied filenames were joined straight onto a directory, so `../../evil.py` wrote
outside the upload root -- an arbitrary file write. These helpers live in
`ingestion/uploads.py` rather than the router because the Streamlit UI writes to disk in
process too and needs the identical checks.
"""

import pytest

from app.config import get_settings
from app.ingestion.uploads import content_digest, safe_filename, tenant_upload_dir, upload_doc_id

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
