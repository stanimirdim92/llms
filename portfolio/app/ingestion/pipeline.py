"""Orchestrates parse -> figure-caption -> chunk -> embed -> store for one PDF."""

from pathlib import Path

import structlog

from app.config import get_settings
from app.embeddings.voyage import embed_chunks
from app.ingestion.chunker import chunk_document
from app.ingestion.figure_extractor import extract_figures
from app.ingestion.parser import load_parsed_document, parse_pdf, save_parsed_document
from app.vectorstore.chroma_store import ChromaStore

log = structlog.get_logger(__name__)


def ingest_document(doc_id: str, pdf_path: Path, store: ChromaStore) -> int:
    """Ingest a single PDF end-to-end. Returns the number of chunks written."""
    settings = get_settings()
    processed_path = settings.processed_dir / f"{doc_id}.json"

    if processed_path.exists():
        log.info("parser.cache_hit", doc_id=doc_id)
        document = load_parsed_document(processed_path)
    else:
        log.info("parser.parse_start", doc_id=doc_id)
        document = parse_pdf(pdf_path)
        save_parsed_document(document, processed_path)

    figure_dir = settings.processed_dir / doc_id / "figures"
    figures = extract_figures(document, pdf_path, figure_dir)
    log.info("ingestion.figures_extracted", doc_id=doc_id, count=len(figures))

    chunks = chunk_document(document, doc_id=doc_id, figures=figures)
    log.info("ingestion.chunked", doc_id=doc_id, count=len(chunks))

    embedded = embed_chunks(chunks)
    store.upsert(embedded)
    log.info("ingestion.stored", doc_id=doc_id, count=len(embedded))

    return len(chunks)
