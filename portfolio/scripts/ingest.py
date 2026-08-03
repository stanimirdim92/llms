"""CLI: run the full ingestion pipeline over every PDF in data/raw_pdfs/."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.ingestion.pipeline import ingest_document
from app.vectorstore.qdrant_store import QdrantStore


async def main() -> None:
    settings = get_settings()
    manifest = json.loads(settings.manifest_path.read_text(encoding="utf-8"))
    store = QdrantStore()

    total_chunks = 0
    failed: list[str] = []
    for paper in manifest["papers"]:
        arxiv_id = paper["arxiv_id"]
        pdf_path = settings.raw_pdf_dir / f"{arxiv_id}.pdf"
        if not pdf_path.exists():
            print(f"missing PDF, run fetch_corpus.py first: {arxiv_id}")
            failed.append(arxiv_id)
            continue

        try:
            count = await ingest_document(doc_id=arxiv_id, file_path=pdf_path, store=store)
        except Exception as exc:  # noqa: BLE001 -- see below
            # Per paper, and deliberately broad. Without this, one unparseable PDF aborted the
            # whole corpus build: the papers before it were ingested, the papers after it were
            # never attempted, and the traceback named only the offender -- so the operator's
            # reasonable next move (re-run) re-parsed everything that had already succeeded
            # just to reach the next failure. The types that arrive here span Docling,
            # Anthropic, Voyage, Qdrant and psycopg, plus this project's own
            # `EmptyDocumentError` for a scan with no text layer, so there is no narrower
            # `except` that covers the cases worth surviving.
            print(f"FAILED {arxiv_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
            failed.append(arxiv_id)
            continue

        total_chunks += count
        print(f"ingested {arxiv_id}: {count} chunks")

    print(f"done: {total_chunks} chunks across {store.count()} total in collection")

    if failed:
        # Non-zero, because this script is run from a Makefile/CI step as often as by hand, and
        # a corpus that is quietly missing three of its papers is worse than a build that
        # stops: retrieval still answers, from less material than the eval set assumes.
        print(f"{len(failed)} of {len(manifest['papers'])} failed: {', '.join(failed)}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
