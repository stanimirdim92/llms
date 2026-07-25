"""Pure helpers for user-uploaded documents, kept dependency-free (no docling import)
so they're testable without the heavy parsing stack -- same reasoning as `models.py`.
"""

import hashlib


def upload_doc_id(session_id: str, file_bytes: bytes) -> str:
    """
    Generate a deterministic document ID scoped to a session.

    Re-uploading identical content in the same session returns the same ID.
    Identical content uploaded in different sessions returns different IDs.
    """

    if not session_id:
        raise ValueError("session_id must not be empty")

    hasher = hashlib.sha256()
    hasher.update(session_id.encode("utf-8"))
    hasher.update(b"\x00")  # Prevent ambiguous concatenation.
    hasher.update(file_bytes)

    content_hash = hasher.hexdigest()[:32]  # 128-bit identifier

    """
        Keep session_id as a separate database/vector-store metadata field for authorization and retrieval filtering.
        The document ID should support identity and deduplication, but it should not replace session filtering.
    """
    return f"{session_id}-{content_hash}"
