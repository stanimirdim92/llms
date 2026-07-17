"""Orchestrates parse -> figure-caption -> chunk -> embed -> store for one document."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from app.config import get_settings
from app.ingestion.chunker import chunk_document
from app.ingestion.figure_extractor import extract_figures
from app.ingestion.models import GLOBAL_SESSION
from app.ingestion.parser import load_parsed_document, parse_document, save_parsed_document

if TYPE_CHECKING:
    from pathlib import Path

    from app.vectorstore.chroma_store import ChromaStore

log = structlog.get_logger(__name__)


def ingest_document(doc_id: str, file_path: Path, store: ChromaStore, session_id: str = GLOBAL_SESSION) -> int:
    """Ingest a single document end-to-end. Returns the number of chunks written."""
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

    chunks = chunk_document(document, doc_id=doc_id, figures=figures, session_id=session_id)
    log.info("ingestion.chunked", doc_id=doc_id, session_id=session_id, count=len(chunks))

    store.upsert(chunks)
    log.info("ingestion.stored", doc_id=doc_id, count=len(chunks))

    return len(chunks)
