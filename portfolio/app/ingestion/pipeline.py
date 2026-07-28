"""Orchestrates parse -> figure-caption -> chunk -> embed -> store for one document."""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING

import structlog

from app.config import get_settings
from app.db import get_session, init_db
from app.ingestion.chunker import chunk_document
from app.ingestion.figure_extractor import extract_figures
from app.ingestion.models import GLOBAL_TENANT
from app.ingestion.parser import load_parsed_document, parse_document, save_parsed_document
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

    chunks = chunk_document(document, doc_id=doc_id, figures=figures, tenant_id=tenant_id)
    log.info("ingestion.chunked", doc_id=doc_id, tenant_id=tenant_id, count=len(chunks))

    content_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()[:16]
    return chunks, content_hash, file_path.stat().st_size


async def ingest_document(doc_id: str, file_path: Path, store: QdrantStore, tenant_id: str = GLOBAL_TENANT) -> int:
    """Ingest a single document end-to-end. Returns the number of chunks written."""
    chunks, content_hash, file_size_bytes = await asyncio.to_thread(_parse_and_chunk, doc_id, file_path, tenant_id)

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
