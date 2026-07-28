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
