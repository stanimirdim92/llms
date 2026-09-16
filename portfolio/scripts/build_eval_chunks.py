"""Parse and chunk the eval corpus, and write the chunk ids the golden set is allowed to reference.

    uv run python scripts/fetch_eval_corpus.py             # first: the PDFs
    uv run python scripts/build_eval_chunks.py             # writes data/eval/chunk_manifest.json
    uv run python scripts/build_eval_chunks.py --check     # fails if today's chunking differs

`data/eval/chunk_manifest.json` is committed and is the contract `qa_dataset.jsonl` is written
against: a golden pair names chunk ids, and a chunk id only means something if the same bytes
still split the same way.

**Why a manifest at all, rather than reading the ids out of Qdrant.** Chunk ids are derived, not
assigned -- `f"{doc_id}-text-{index:04d}"`, where `doc_id` is the tenant-salted digest of the
file and `index` is the chunker's output position. Every input to that is a moving part: the
document's bytes, `chunk_max_tokens`, the HybridChunker, the tokenizer, and the Docling release
that produced the layout. A dependency bump can renumber every chunk in the corpus, and nothing
would fail -- the golden ids would simply point at different passages and recall@k would drop,
which reads exactly like a retrieval regression. `--check` turns that into an error that names
the document.

**Figures are deliberately not in here.** A figure chunk's id is `f"{doc_id}-{figure_id}"`, and
whether it exists at all depends on a vision-model caption that `figure_extractor` may reject as
unusable -- so figure chunks are not reproducible from the bytes alone and cannot be a fixture.
Text and table chunk ids are unaffected by their absence: the three kinds are numbered in
separate passes (see `chunker.chunk_document`), so `-text-0007` is `-text-0007` whether or not
the document's figures were captioned. Figure-grounded golden questions therefore need a
different anchor than a chunk id, and that is an open question on Phase 2.1, not something this
script papers over.

This script does **not** embed, store, or touch Postgres, Qdrant or Voyage. Parse and chunk are
the whole deterministic half of ingestion, and they are the half the golden set depends on.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from importlib.metadata import version

from app.config import get_settings
from app.ingestion.chunker import chunk_document
from app.ingestion.parser import DocumentParseError, parse_document
from app.ingestion.uploads import upload_doc_id

EVAL_DIR = Path(__file__).resolve().parent.parent / "data" / "eval"
MANIFEST_PATH = EVAL_DIR / "corpus_manifest.json"
CHUNK_MANIFEST_PATH = EVAL_DIR / "chunk_manifest.json"
CORPUS_DIR = EVAL_DIR / "corpus"
CHUNK_TEXT_DIR = EVAL_DIR / "chunk_text"
"""Full chunk text, one JSON file per document. Not committed -- it is a derivable copy of the
corpus, and committing it would be committing the papers. It exists because writing grounded
Q&A pairs means reading the passages, and the excerpt in the manifest is too short for that.
"""

_EXCERPT_CHARS = 240


def _text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build() -> dict:
    settings = get_settings()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    tenant_id = manifest["seed_tenant_id"]

    documents: list[dict] = []
    skipped: list[dict] = []
    CHUNK_TEXT_DIR.mkdir(parents=True, exist_ok=True)

    for paper in manifest["papers"]:
        path = CORPUS_DIR / paper["filename"]
        if not path.exists():
            msg = f"{path} is missing. Run scripts/fetch_eval_corpus.py first."
            raise FileNotFoundError(msg)

        file_bytes = path.read_bytes()
        doc_id = upload_doc_id(tenant_id, file_bytes)
        started = time.monotonic()
        try:
            document = parse_document(path)
        except DocumentParseError as exc:
            # Not fatal, and not silent. A document this system cannot parse under its own
            # production settings has no business in a fixture that is supposed to represent
            # what the system does -- but which documents those are is a finding, so it is
            # recorded in the manifest rather than dropped on the floor.
            elapsed = round(time.monotonic() - started, 1)
            skipped.append({"arxiv_id": paper["arxiv_id"], "reason": str(exc), "elapsed_s": elapsed})
            print(f"SKIPPED  {paper['arxiv_id']}  after {elapsed}s: {exc}")
            continue
        parse_seconds = round(time.monotonic() - started, 1)

        chunks = chunk_document(document, doc_id=doc_id, figures=[], tenant_id=tenant_id, filename=paper["filename"])
        entries = [
            {
                "chunk_id": chunk.chunk_id,
                "chunk_type": chunk.chunk_type,
                "page_no": chunk.page_no,
                "section_path": chunk.section_path,
                "order_index": chunk.order_index,
                "chars": len(chunk.text),
                "text_sha256": _text_digest(chunk.text),
                "excerpt": " ".join(chunk.text.split())[:_EXCERPT_CHARS],
            }
            for chunk in chunks
        ]
        documents.append(
            {
                "arxiv_id": paper["arxiv_id"],
                "filename": paper["filename"],
                "doc_id": doc_id,
                "pages": len(document.pages),
                "parse_seconds": parse_seconds,
                "text_chunks": sum(1 for c in chunks if c.chunk_type == "text"),
                "table_chunks": sum(1 for c in chunks if c.chunk_type == "table"),
                "chunks": entries,
            }
        )
        (CHUNK_TEXT_DIR / f"{paper['arxiv_id']}.json").write_text(
            json.dumps(
                [
                    {
                        "chunk_id": c.chunk_id,
                        "chunk_type": c.chunk_type,
                        "page_no": c.page_no,
                        "section_path": c.section_path,
                        "text": c.text,
                    }
                    for c in chunks
                ],
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"ok       {paper['arxiv_id']}  {len(document.pages)}p  {parse_seconds}s  {len(entries)} chunks")

    return {
        "note": (
            "Generated by scripts/build_eval_chunks.py. Figure chunks are deliberately absent -- "
            "see that script's docstring. Do not hand-edit: --check compares against a rebuild."
        ),
        "seed_tenant_id": tenant_id,
        "produced_by": {
            "docling": version("docling"),
            "docling_core": version("docling-core"),
            "tokenizer_model": "sentence-transformers/all-MiniLM-L6-v2",
            "chunk_max_tokens": settings.chunk_max_tokens,
        },
        "skipped": skipped,
        "documents": documents,
    }


def _comparable(built: dict) -> dict:
    """Everything a golden reference depends on, with the machine-dependent parts dropped.

    `parse_seconds` moves with the hardware and `produced_by` is recorded to explain a drift,
    not to cause one -- a Docling bump that changes no chunk is not a failure. What must not
    move is the set of chunk ids and the text behind each.
    """
    return {
        doc["arxiv_id"]: {
            "doc_id": doc["doc_id"],
            "chunks": {c["chunk_id"]: c["text_sha256"] for c in doc["chunks"]},
        }
        for doc in built["documents"]
    }


def _report_drift(old: dict, new: dict) -> int:
    drifted = 0
    for arxiv_id in sorted(set(old) | set(new)):
        if arxiv_id not in new:
            print(f"DRIFT {arxiv_id}: in the committed manifest, absent from this build")
            drifted += 1
            continue
        if arxiv_id not in old:
            print(f"DRIFT {arxiv_id}: built now, absent from the committed manifest")
            drifted += 1
            continue
        before, after = old[arxiv_id], new[arxiv_id]
        if before["doc_id"] != after["doc_id"]:
            print(f"DRIFT {arxiv_id}: doc_id changed -- the bytes or the seed tenant id moved")
            drifted += 1
            continue
        added = sorted(set(after["chunks"]) - set(before["chunks"]))
        removed = sorted(set(before["chunks"]) - set(after["chunks"]))
        retexted = sorted(
            chunk_id
            for chunk_id in set(before["chunks"]) & set(after["chunks"])
            if before["chunks"][chunk_id] != after["chunks"][chunk_id]
        )
        if added or removed or retexted:
            drifted += 1
            print(f"DRIFT {arxiv_id}: {len(added)} new, {len(removed)} gone, {len(retexted)} same id different text")
            for chunk_id in added[:3] + removed[:3] + retexted[:3]:
                print(f"        {chunk_id}")
    return drifted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="rebuild and compare against the committed manifest instead of overwriting it",
    )
    check = parser.parse_args().check

    built = _build()

    if not check:
        CHUNK_MANIFEST_PATH.write_text(json.dumps(built, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        total = sum(len(doc["chunks"]) for doc in built["documents"])
        print(f"\nwrote {CHUNK_MANIFEST_PATH}: {len(built['documents'])} documents, {total} chunks")
        return 0

    if not CHUNK_MANIFEST_PATH.exists():
        print(f"{CHUNK_MANIFEST_PATH} does not exist -- run without --check first.", file=sys.stderr)
        return 1
    committed = json.loads(CHUNK_MANIFEST_PATH.read_text(encoding="utf-8"))
    drifted = _report_drift(_comparable(committed), _comparable(built))
    if drifted:
        print(
            f"\n{drifted} document(s) chunk differently than the committed manifest. Every golden "
            f"chunk id pointing into them now points somewhere else. Rebuild the manifest and "
            f"re-check the affected pairs in qa_dataset.jsonl -- do not just re-record.",
            file=sys.stderr,
        )
        return 1
    print(f"\nchunking matches the committed manifest ({len(built['documents'])} documents)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
