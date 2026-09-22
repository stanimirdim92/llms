"""Ingest the eval corpus through the real pipeline, and record the chunk ids that actually landed.

    uv run python scripts/fetch_eval_corpus.py          # first: the PDFs
    uv run python scripts/seed_eval_corpus.py           # ingest, then write chunk_manifest.json
    uv run python scripts/seed_eval_corpus.py --check   # read Qdrant back, report drift, write nothing

Needs a live Postgres, Qdrant, `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` -- because it runs the
same `ingest_document` the worker and Streamlit run. That is the point of it.

**Why it does not parse the corpus itself.** The first version of this script was an offline
parse-and-chunk that never touched Qdrant, Voyage or Postgres, and it was wrong in a way that
would have been invisible: it called `chunk_document(..., figures=[])`, so the manifest it
produced had no figure chunks and did not describe what the system actually indexes. A fixture
that is *nearly* the real chunk set is worse than no fixture, because recall@k measured against
it reads as a property of retrieval.

So the manifest is now read back out of Qdrant after a real ingest: **what retrieval can see is
what a golden reference is allowed to name.** A chunk that the parse produced and the store never
received is not retrievable, and a golden id for it would score as a permanent miss that looks
like a retrieval bug.

One property this makes explicit rather than dodging: **figure chunks are real but not
reproducible.** A figure chunk exists only if the vision model returned a caption that
`figure_extractor` did not reject as unusable, so a re-ingest can legitimately produce a
different set of them. `--check` reports that as drift like any other, and a golden pair citing
a figure chunk has to be re-checked when it does.
"""

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from importlib.metadata import version

from app.auth.models import Tenant
from app.config import get_settings
from app.db import get_session, init_db
from app.ingestion.pipeline import ingest_document
from app.ingestion.uploads import content_digest, document_upload_path, upload_doc_id, write_upload
from app.registry.db import list_active_versions, save_document_record
from app.registry.models import STATUS_PENDING, DocumentRecord
from app.vectorstore.qdrant_store import QdrantStore

EVAL_DIR = Path(__file__).resolve().parent.parent / "data" / "eval"
MANIFEST_PATH = EVAL_DIR / "corpus_manifest.json"
CHUNK_MANIFEST_PATH = EVAL_DIR / "chunk_manifest.json"
CORPUS_DIR = EVAL_DIR / "corpus"
CHUNK_TEXT_DIR = EVAL_DIR / "chunk_text"
"""Full chunk text, one JSON file per document. Not committed -- it is a derivable copy of the
papers. It exists because writing grounded Q&A pairs means reading the passages, and the excerpt
in the manifest is far too short for that.
"""

_EXCERPT_CHARS = 240


def _text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _ensure_seed_tenant(tenant_id: str) -> None:
    """Create the fixture tenant row at its **pinned** id if it is not there.

    Not `scripts/create_tenant.py`, which mints a fresh `new_id()`: `upload_doc_id` salts the
    content digest with the tenant id, so a minted id would give the same six PDFs different
    doc_ids and therefore different chunk ids, silently invalidating every golden reference.
    Keys are still minted by that CLI -- this only guarantees the row it attaches to.
    """
    await init_db()
    async with get_session() as session:
        if await session.get(Tenant, tenant_id):
            return
        session.add(Tenant(id=tenant_id, name="eval-corpus"))
        await session.commit()
    print(f"created seed tenant {tenant_id}")


async def _ingest_one(paper: dict, tenant_id: str, store: QdrantStore) -> dict:
    """Upload and ingest one paper exactly as `streamlit_app/Home.py` does.

    Same helpers, same order: `upload_doc_id` -> `document_upload_path` -> `write_upload` ->
    commit a `pending` row -> `ingest_document`. Not re-implemented, because the two ways this
    path has been got wrong before were both from a second copy of it (a hand-joined upload path,
    and the staging writer that does not commit).
    """
    settings = get_settings()
    source = CORPUS_DIR / paper["filename"]
    file_bytes = source.read_bytes()
    doc_id = upload_doc_id(tenant_id, file_bytes)
    digest = content_digest(file_bytes)
    file_path = document_upload_path(settings.upload_dir, tenant_id, doc_id, paper["filename"])
    write_upload(file_path, file_bytes)

    async with get_session() as session:
        await save_document_record(
            session,
            DocumentRecord(
                doc_id=doc_id,
                tenant_id=tenant_id,
                filename=file_path.name,
                content_hash=digest,
                file_extension=file_path.suffix,
                file_size_bytes=len(file_bytes),
                status=STATUS_PENDING,
            ),
        )

    started = time.monotonic()
    chunk_count = await ingest_document(
        doc_id=doc_id, file_path=file_path, store=store, tenant_id=tenant_id, expected_digest=digest
    )
    elapsed = round(time.monotonic() - started, 1)
    print(f"ingested {paper['arxiv_id']}  {chunk_count} chunks  {elapsed}s")
    return {"arxiv_id": paper["arxiv_id"], "filename": paper["filename"], "doc_id": doc_id, "ingest_seconds": elapsed}


async def _read_back(tenant_id: str, ingested: list[dict], store: QdrantStore) -> dict:
    """The manifest, built from the points Qdrant is actually serving.

    Filtered on `list_active_versions`, the same way `Retriever.retrieve` is: Postgres decides
    what is searchable, so a generation that was upserted but never published must not appear
    here either.
    """
    async with get_session() as session:
        versions = await list_active_versions(session, tenant_id=tenant_id)

    CHUNK_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    documents: list[dict] = []
    for record in ingested:
        doc_id = record["doc_id"]
        active = versions.get(doc_id)
        if active is None:
            msg = f"{record['arxiv_id']} has no active version in the registry -- the ingest did not publish"
            raise RuntimeError(msg)
        chunks = await asyncio.to_thread(store.get_document_chunks, doc_id, tenant_id, [active])
        entries = [
            {
                "chunk_id": chunk.metadata["chunk_id"],
                "chunk_type": chunk.metadata["chunk_type"],
                "page_no": chunk.metadata.get("page_no"),
                "section_path": chunk.metadata.get("section_path", ""),
                "order_index": chunk.metadata.get("order_index", 0),
                "chars": len(chunk.page_content),
                "text_sha256": _text_digest(chunk.page_content),
                "excerpt": " ".join(chunk.page_content.split())[:_EXCERPT_CHARS],
            }
            for chunk in chunks
        ]
        kinds = Counter(str(entry["chunk_type"]) for entry in entries)
        documents.append({**record, "chunk_counts": dict(kinds), "chunks": entries})
        (CHUNK_TEXT_DIR / f"{record['arxiv_id']}.json").write_text(
            json.dumps(
                [
                    {
                        "chunk_id": chunk.metadata["chunk_id"],
                        "chunk_type": chunk.metadata["chunk_type"],
                        "page_no": chunk.metadata.get("page_no"),
                        "section_path": chunk.metadata.get("section_path", ""),
                        "text": chunk.page_content,
                    }
                    for chunk in chunks
                ],
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"read back {record['arxiv_id']}  {len(entries)} chunks  {dict(kinds)}")

    settings = get_settings()
    return {
        "note": (
            "Generated by scripts/seed_eval_corpus.py from the points Qdrant is serving after a "
            "real ingest -- not from an offline re-parse. Do not hand-edit."
        ),
        "seed_tenant_id": tenant_id,
        "produced_by": {
            "docling": version("docling"),
            "docling_core": version("docling-core"),
            "voyage_model": settings.voyage_model,
            "figure_caption_model": settings.figure_caption_model,
            "chunk_max_tokens": settings.chunk_max_tokens,
        },
        "documents": documents,
    }


def _comparable(built: dict) -> dict:
    """Everything a golden reference depends on, with the machine-dependent parts dropped.

    `ingest_seconds` moves with the hardware and `produced_by` is recorded to *explain* a drift,
    not to cause one -- a Docling bump that changes no chunk is not a failure. What must not move
    is the set of chunk ids and the text behind each.
    """
    return {
        doc["arxiv_id"]: {
            "doc_id": doc["doc_id"],
            "chunks": {chunk["chunk_id"]: chunk["text_sha256"] for chunk in doc["chunks"]},
        }
        for doc in built["documents"]
    }


def _report_drift(old: dict, new: dict) -> int:
    drifted = 0
    for arxiv_id in sorted(set(old) | set(new)):
        if arxiv_id not in new:
            print(f"DRIFT {arxiv_id}: in the committed manifest, absent from the store")
            drifted += 1
            continue
        if arxiv_id not in old:
            print(f"DRIFT {arxiv_id}: in the store, absent from the committed manifest")
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


async def _run(*, check: bool) -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    tenant_id = manifest["seed_tenant_id"]
    await _ensure_seed_tenant(tenant_id)
    store = await asyncio.to_thread(QdrantStore)

    if check:
        ingested = [
            {
                "arxiv_id": paper["arxiv_id"],
                "filename": paper["filename"],
                "doc_id": upload_doc_id(tenant_id, (CORPUS_DIR / paper["filename"]).read_bytes()),
            }
            for paper in manifest["papers"]
        ]
    else:
        ingested = [await _ingest_one(paper, tenant_id, store) for paper in manifest["papers"]]

    built = await _read_back(tenant_id, ingested, store)

    if not check:
        CHUNK_MANIFEST_PATH.write_text(json.dumps(built, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        total = sum(len(doc["chunks"]) for doc in built["documents"])
        print(f"\nwrote {CHUNK_MANIFEST_PATH}: {len(built['documents'])} documents, {total} chunks")
        return 0

    committed = json.loads(CHUNK_MANIFEST_PATH.read_text(encoding="utf-8"))
    drifted = _report_drift(_comparable(committed), _comparable(built))
    if drifted:
        print(
            f"\n{drifted} document(s) differ from the committed manifest. Every golden chunk id "
            f"pointing into them may now point somewhere else -- re-read those passages before "
            f"re-recording anything.",
            file=sys.stderr,
        )
        return 1
    print(f"\nthe store matches the committed manifest ({len(built['documents'])} documents)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="read the store back and compare against the committed manifest instead of ingesting",
    )
    return asyncio.run(_run(check=parser.parse_args().check))


if __name__ == "__main__":
    raise SystemExit(main())
