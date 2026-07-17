"""CLI: run the full ingestion pipeline over every PDF in data/raw_pdfs/."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.ingestion.pipeline import ingest_document  # noqa: E402
from app.vectorstore.chroma_store import ChromaStore  # noqa: E402


def main() -> None:
    settings = get_settings()
    manifest = json.loads(settings.manifest_path.read_text(encoding="utf-8"))
    store = ChromaStore()

    total_chunks = 0
    for paper in manifest["papers"]:
        arxiv_id = paper["arxiv_id"]
        pdf_path = settings.raw_pdf_dir / f"{arxiv_id}.pdf"
        if not pdf_path.exists():
            print(f"missing PDF, run fetch_corpus.py first: {arxiv_id}")
            continue

        count = ingest_document(doc_id=arxiv_id, file_path=pdf_path, store=store)
        total_chunks += count
        print(f"ingested {arxiv_id}: {count} chunks")

    print(f"done: {total_chunks} chunks across {store.count()} total in collection")


if __name__ == "__main__":
    main()
