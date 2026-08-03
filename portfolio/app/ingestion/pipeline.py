"""Orchestrates parse -> figure-caption -> chunk -> embed -> store for one document."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from app.config import get_settings
from app.db import get_session, init_db
from app.ingestion.chunker import chunk_document
from app.ingestion.figure_extractor import extract_figures
from app.ingestion.models import GLOBAL_TENANT
from app.ingestion.parser import load_parsed_document, parse_document, save_parsed_document
from app.ingestion.uploads import content_digest
from app.registry.db import save_document_record
from app.registry.models import DocumentRecord

if TYPE_CHECKING:
    from pathlib import Path

    from app.ingestion.models import Chunk
    from app.vectorstore.qdrant_store import QdrantStore

log = structlog.get_logger(__name__)


def _parse_and_chunk(doc_id: str, file_path: Path, tenant_id: str) -> tuple[list[Chunk], str, int]:
    """Everything here is synchronous, CPU-bound work (Docling parsing, chunking) or
    local disk I/O -- run via `asyncio.to_thread` from `ingest_document` so it doesn't
    block the event loop while other requests (e.g. concurrent uploads) are in flight.
    """
    settings = get_settings()
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

    content_hash = content_digest(file_path.read_bytes())
    return chunks, content_hash, file_path.stat().st_size


class EmptyDocumentError(Exception):
    """A document produced nothing searchable."""


async def ingest_document(doc_id: str, file_path: Path, store: QdrantStore, tenant_id: str = GLOBAL_TENANT) -> int:
    """Ingest a single document end-to-end. Returns the number of chunks written."""
    chunks, content_hash, file_size_bytes = await asyncio.to_thread(_parse_and_chunk, doc_id, file_path, tenant_id)

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

    # `QdrantStore.upsert` has no native async client (see qdrant_store.py's own note on
    # `query`) -- offload it the same way as the parse/chunk work above rather than
    # blocking the event loop on network I/O.
    await asyncio.to_thread(store.upsert, chunks)
    log.info("ingestion.stored", doc_id=doc_id, count=len(chunks))

    await init_db()
    record = DocumentRecord(
        doc_id=doc_id,
        tenant_id=tenant_id,
        filename=file_path.name,
        content_hash=content_hash,
        file_extension=file_path.suffix,
        file_size_bytes=file_size_bytes,
        chunk_count=len(chunks),
    )
    async with get_session() as session:
        await save_document_record(session, record)
    log.info("ingestion.registered", doc_id=doc_id, tenant_id=tenant_id)

    return len(chunks)
