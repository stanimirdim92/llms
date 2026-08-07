"""Orchestrates parse -> figure-caption -> chunk -> embed -> store for one document."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from app.config import get_settings
from app.db import get_session, init_db
from app.ids import new_id
from app.ingestion.chunker import chunk_document
from app.ingestion.figure_extractor import extract_figures
from app.ingestion.parser import load_parsed_document, parse_document, save_parsed_document
from app.ingestion.uploads import content_digest
from app.registry.db import activate_document_version

if TYPE_CHECKING:
    from pathlib import Path

    from app.ingestion.models import Chunk
    from app.vectorstore.qdrant_store import QdrantStore

log = structlog.get_logger(__name__)


class ContentMismatchError(Exception):
    """The bytes on disk are not the bytes that were accepted for this `doc_id`.

    A distinct type rather than a bare `Exception` because the worker's retry policy has to treat
    it as **deterministic**: the file will not un-change itself, so retrying re-reads the same
    wrong bytes and burns another parse. It also names a real integrity failure worth alerting on,
    which a generic parse error does not.
    """


def _parse_and_chunk(doc_id: str, file_path: Path, tenant_id: str, expected_digest: str | None) -> list[Chunk]:
    """Everything here is synchronous, CPU-bound work (Docling parsing, chunking) or
    local disk I/O -- run via `asyncio.to_thread` from `ingest_document` so it doesn't
    block the event loop while other requests (e.g. concurrent uploads) are in flight.
    """
    settings = get_settings()

    # Hashed **before** the parse, not after, and this ordering is the whole guard. The parse is
    # cached at `processed_dir/<doc_id>.json` and figures under `processed_dir/<doc_id>/figures`,
    # so parsing the wrong bytes writes them under this `doc_id` permanently -- a later correct
    # re-ingest hits the cache and reads the wrong content again. Verifying afterwards would
    # detect the swap and leave the poisoned cache in place.
    #
    # One read, reused for the digest and returned as `content_hash`. The previous code read the
    # file at the *end* purely to recompute a hash it then stored, which is what erased the
    # evidence: on a content swap it recorded the hash of whatever it had actually read, so the
    # registry row was internally consistent and wrong.
    file_bytes = file_path.read_bytes()
    content_hash = content_digest(file_bytes)
    if expected_digest is not None and content_hash != expected_digest:
        msg = (
            f"{file_path.name} changed on disk between upload and ingestion: expected digest "
            f"{expected_digest}, found {content_hash}. Refusing to ingest, because parsing these "
            f"bytes would file another document's content under this one's id."
        )
        raise ContentMismatchError(msg)

    processed_path = settings.processed_dir / f"{doc_id}.json"

    if processed_path.exists():
        log.info("parser.cache_hit", doc_id=doc_id)
        document = load_parsed_document(processed_path)
    else:
        log.info("parser.parse_start", doc_id=doc_id)
        document = parse_document(file_path)
        save_parsed_document(document, processed_path)

    figure_dir = settings.processed_dir / doc_id / "figures"
    figures = extract_figures(document, figure_dir)
    log.info("ingestion.figures_extracted", doc_id=doc_id, count=len(figures))

    chunks = chunk_document(document, doc_id=doc_id, figures=figures, tenant_id=tenant_id, filename=file_path.name)
    log.info("ingestion.chunked", doc_id=doc_id, tenant_id=tenant_id, count=len(chunks))

    # Only the chunks. `content_hash` and `file_size_bytes` used to come back here so the terminal
    # write could store them, but that write is now an UPDATE of a row the upload already staged
    # with both -- recomputing them would be a second source for a value that is already recorded.
    return chunks


class EmptyDocumentError(Exception):
    """A document produced nothing searchable."""


async def ingest_document(
    doc_id: str, file_path: Path, store: QdrantStore, tenant_id: str, expected_digest: str | None
) -> int:
    """Ingest a single document end-to-end. Returns the number of chunks written.

    `expected_digest` is the `content_digest` the upload recorded, and it is **required rather
    than defaulted** on purpose: a default of `None` here would let a caller silently opt out of
    the integrity check by forgetting an argument, which is the failure this parameter exists to
    prevent. Pass `None` explicitly and only where there is genuinely nothing to compare against
    -- today that is a job enqueued before this parameter existed (see `worker/tasks.py`).
    """
    chunks = await asyncio.to_thread(_parse_and_chunk, doc_id, file_path, tenant_id, expected_digest)

    if not chunks:
        # Recorded as a failure rather than a zero-chunk success, because "ingested" with nothing
        # in the index is a lie the user can only discover by asking a question and getting
        # nothing. A real 2MB scanned flyer hit this: Docling extracted 30 characters
        # (`<!-- image -->` twice) with OCR off, so the document was searchable in name only.
        # The message names the likely cause, since a scanned PDF is the overwhelming reason a
        # parse succeeds and yields no text.
        # The message must not name a knob to turn. It used to say "OCR must be enabled
        # (DO_OCR)" -- there is no `DO_OCR` setting anywhere in this project, `parser.py`
        # never passes `do_ocr=`, and Docling's own default is already `True` (verified
        # against the installed package, not assumed). So the advice sent a user to change a
        # setting that does not exist, to enable something already on, and the re-upload
        # failed identically. Rule 11: refuse honestly rather than answer from the wrong
        # material -- including in an error message.
        msg = (
            f"{file_path.name} produced no searchable content. OCR is already enabled, so if this "
            f"is a scan, the page images are likely too low-resolution or too skewed to read. "
            f"Re-scan at a higher DPI, or upload a version with a real text layer."
        )
        raise EmptyDocumentError(msg)

    # A new generation per attempt. Minted here rather than by either caller (the worker and
    # Streamlit both reach this function) so one ingest is one version no matter which entered.
    ingestion_version = new_id()

    # Inserts without deleting, so the previous generation stays intact and readable until the
    # flip below. Offloaded because `QdrantStore.upsert` has no native async client.
    await asyncio.to_thread(store.upsert, chunks, ingestion_version)
    log.info("ingestion.stored", doc_id=doc_id, count=len(chunks), ingestion_version=ingestion_version)

    await init_db()
    # **The commit point.** Nothing above published anything: the new points are unreadable until
    # this row says their version is active, and if it never lands the old generation keeps serving.
    async with get_session() as session:
        await activate_document_version(
            session,
            doc_id=doc_id,
            tenant_id=tenant_id,
            ingestion_version=ingestion_version,
            chunk_count=len(chunks),
        )
    log.info("ingestion.activated", doc_id=doc_id, tenant_id=tenant_id, ingestion_version=ingestion_version)

    # Hygiene, after the flip, and deliberately not allowed to fail the ingest: the superseded
    # generation is already unreadable, so leftovers cost storage and nothing else. Failing here
    # would turn a successful publish into a reported failure.
    try:
        await asyncio.to_thread(store.delete_superseded, doc_id, tenant_id, ingestion_version)
    except Exception as exc:  # noqa: BLE001
        log.warning("ingestion.prune_failed", doc_id=doc_id, keep_version=ingestion_version, error=str(exc))

    return len(chunks)
