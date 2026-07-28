"""Pure helpers for user-uploaded documents, kept dependency-free (no docling import)
so they're testable without the heavy parsing stack -- same reasoning as `models.py`.
"""

import hashlib

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
