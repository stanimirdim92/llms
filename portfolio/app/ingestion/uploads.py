"""Pure helpers for user-uploaded documents, kept dependency-free (no docling, no fastapi)
so they're testable without the heavy parsing stack -- same reasoning as `models.py`.

The path helpers live here rather than in `api/routers/documents.py` because the Streamlit
UI needs the identical checks: it calls the pipeline in process, so it builds an upload path
itself. Two copies of a containment check is one copy too many. They raise `ValueError`, not
`APIError`, so this module stays HTTP-agnostic and the router translates.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.auth.models import TENANT_ID_PATTERN

_TENANT_ID_RE = re.compile(TENANT_ID_PATTERN)

_DOC_ID_HASH_LENGTH = 32
"""128 bits of the digest. Collisions would have to occur *within one tenant* to matter, so
this is far past sufficient; it is short only to keep ids readable in logs and citations."""


def upload_doc_id(tenant_id: str, file_bytes: bytes) -> str:
    """A deterministic document id scoped to one tenant.

    Re-uploading identical content under the same tenant yields the same id, which is what
    makes ingestion an update rather than a duplicate. The same file uploaded by a different
    tenant yields a different id, so tenants never share a document row or point set.

    `tenant_id` is hashed *in addition to* being the id's prefix. The prefix alone already
    separates tenants; including it in the digest means two tenants' ids for identical
    content share no common suffix either, so comparing ids cannot reveal that they uploaded
    the same file. A NUL byte separates the two inputs so that no (tenant, content) pair can
    be reinterpreted as a different pair with the same concatenation.

    This id is for identity and deduplication only -- it is **not** an authorization
    boundary. Retrieval is scoped by the `tenant_id` metadata field on each chunk (see
    `vectorstore/qdrant_store.py::_build_filter`), never by parsing it back out of a doc_id.
    """
    if not tenant_id:
        msg = "tenant_id must not be empty"
        raise ValueError(msg)

    hasher = hashlib.sha256()
    hasher.update(tenant_id.encode("utf-8"))
    hasher.update(b"\x00")
    hasher.update(file_bytes)
    return f"{tenant_id}-{hasher.hexdigest()[:_DOC_ID_HASH_LENGTH]}"


_CONTENT_HASH_LENGTH = 16
"""64 bits of the digest, for change detection only -- not identity, which is `upload_doc_id`."""


def content_digest(file_bytes: bytes) -> str:
    """A digest of the bytes themselves, with no tenant salt.

    Deliberately *not* `upload_doc_id`, and this column had been written both ways: the router
    stored the tenant-salted 65-character `doc_id` (a 32-char tenant id, a hyphen, and 32 hex of
    digest) on the pending row and `ingest_document` overwrote it with a plain 16-char sha256 on
    the terminal write. Same column, two values with different
    meanings and different lengths, reconciled only by whichever write happened last. Harmless
    while nothing reads the field -- and that is exactly the state in which a column quietly
    becomes unusable, because the first reader inherits both conventions.

    Unsalted on purpose: `doc_id` already carries identity and isolation (see `upload_doc_id`),
    so what is left for this field is the one question the id cannot answer -- did the bytes
    change while the id stayed the same?

    **Corrected 2026-08-05: this field is load-bearing, and the note here previously said it was
    write-only.** That note reasoned that since `doc_id` is `f"{tenant_id}-{sha256(tenant_id,
    bytes)}"`, different bytes always mean a different id, so bytes can never change under a fixed
    id. True of the *id* and false of the *file*: uploads were stored at
    `<tenant>/<filename>`, so two documents sharing a filename shared a path and each overwrote the
    other's bytes under a different id. The reasoning was about id collisions and the defect was a
    path collision.

    So this digest is now what the upload hands the worker as `expected_digest`, and
    `pipeline._parse_and_chunk` refuses to parse when it does not match what is on disk. It is read
    on every ingest rather than never. `document_upload_path` closes the path collision itself; the
    digest is the second line, for anything else that can rewrite a file between acceptance and
    ingestion -- a retry after a manual disk edit, a restored backup, a future shared object store.
    """
    return hashlib.sha256(file_bytes).hexdigest()[:_CONTENT_HASH_LENGTH]


def safe_filename(filename: str | None) -> str:
    """Reduce a client-supplied filename to a bare name safe to join onto a directory.

    Filenames arrive from whatever the client sent, so they may contain path separators or
    `..`. Joined naively, `../../evil.py` escapes the upload directory and the write lands
    wherever the client chose -- an arbitrary file write. `Path(...).name` discards any
    directory portion; the remaining checks reject what is still unusable.
    """
    candidate = Path(filename or "").name
    if not candidate or candidate.startswith("."):
        msg = "File must have a usable, non-hidden filename"
        raise ValueError(msg)
    return candidate


def tenant_upload_dir(upload_root: Path, tenant_id: str) -> Path:
    """The tenant's own upload directory, verified to sit inside `upload_root`.

    `tenant_id` is server-issued (`uuid7().hex`), so the format check should be unreachable
    -- which is the point of having it. A path built from an identifier should not depend on
    that guarantee holding forever, and the containment check catches any future mistake in
    how this path is composed rather than trusting it.
    """
    if not _TENANT_ID_RE.fullmatch(tenant_id):
        msg = "tenant id has an unexpected format"
        raise ValueError(msg)

    root = upload_root.resolve()
    directory = (root / tenant_id).resolve()
    if not directory.is_relative_to(root):
        msg = "refusing to write outside the upload directory"
        raise ValueError(msg)
    return directory


def document_upload_path(upload_root: Path, tenant_id: str, doc_id: str, filename: str) -> Path:
    """Where one document's bytes live: `<root>/<tenant_id>/<doc_id>/<safe filename>`.

    **`doc_id` is in the path because the filename alone is not an identity.** It used to be
    `<root>/<tenant_id>/<filename>`, and two different documents sharing a filename then shared a
    path. The failure is not a lost file, it is a *silent content swap* between two identities:

    1. Upload A as `report.pdf` -> `doc_id=A`, bytes written to `tenant/report.pdf`.
    2. Upload B, different bytes, also `report.pdf` -> `doc_id=B`, overwrites `tenant/report.pdf`.
    3. Worker A dequeues, reads the path it was given, and gets **B's bytes**.
    4. B's content is parsed, chunked, embedded and stored under **A's** `doc_id`, and A's
       registry row records B's `content_hash` -- so nothing afterwards looks wrong.

    The damage was sticky rather than transient, which is what made it worth the path change
    rather than a lock: `pipeline._parse_and_chunk` caches the parse at
    `processed_dir/<doc_id>.json` and figures under `processed_dir/<doc_id>/figures`, so B's parsed
    output and captions persisted under A's identity and a later correct re-ingest of A would hit
    that cache and read B again.

    `doc_id` is `f"{tenant_id}-{32 hex}"` (see `upload_doc_id`), so it cannot contain a separator
    -- but this is a path built from an identifier, and the containment check below is here for the
    same reason `tenant_upload_dir`'s is: not because the format guarantee is doubted today.

    The filename is kept as the leaf rather than folded into the directory name, and that is
    load-bearing in two places: `chunk_document` stores `file_path.name` as the chunk's `filename`
    metadata, which is what `retrieval/document_scope.py` matches a question against, and
    `EmptyDocumentError`'s message names the file back to the user. A `<doc_id>.pdf` leaf would
    make document-name scoping match on a content hash.
    """
    directory = tenant_upload_dir(upload_root, tenant_id) / doc_id
    leaf = safe_filename(filename)
    path = (directory / leaf).resolve()
    if not path.is_relative_to(directory.resolve()):
        msg = "refusing to write outside the document directory"
        raise ValueError(msg)
    return path


def write_upload(path: Path, file_bytes: bytes) -> None:
    """Write the bytes so a reader never sees a partial file.

    Blocking; call it through `asyncio.to_thread` from async code.

    **The rename is the point.** A plain `write_bytes` to the final path is visible to the worker
    the moment the first block lands, so a worker that dequeues mid-write parses a truncated
    document and records the truncation as the document. `os.replace` within the same directory is
    atomic on POSIX, so the final path either does not exist or holds every byte.

    The temporary name is prefixed `.` and suffixed `.partial` so a crashed write leaves something
    obviously incomplete rather than a plausible-looking document -- and `safe_filename` rejects
    leading dots, so a leftover can never be mistaken for an upload.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.partial")
    staging.write_bytes(file_bytes)
    staging.replace(path)
