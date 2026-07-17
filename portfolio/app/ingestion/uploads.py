"""Pure helpers for user-uploaded documents, kept dependency-free (no docling import)
so they're testable without the heavy parsing stack -- same reasoning as `models.py`.
"""

import hashlib


def upload_doc_id(session_id: str, file_bytes: bytes) -> str:
    """Content-hash-derived id: re-uploading the same file in the same session is an
    idempotent upsert (same id) rather than a duplicate; different sessions never collide.
    """
    content_hash = hashlib.sha256(file_bytes).hexdigest()[:16]
    return f"{session_id}-{content_hash}"
