"""Build the BM25 copy of a tenant's already-ingested documents, for `HYBRID_SEARCH`.

    HYBRID_SEARCH=true uv run python scripts/backfill_bm25.py                 # the eval tenant
    HYBRID_SEARCH=true uv run python scripts/backfill_bm25.py --tenant <id>   # any other tenant

New ingests write the sparse copy themselves once the flag is on. Documents ingested before that
have no sparse points, so the BM25 half of every search would silently find nothing for them and
hybrid would score as plain dense retrieval.

**Copies, never re-ingests.** It reads each document's live generation back out of the dense
collection and writes the sparse points under the same point ids. So no `ingestion_version`
changes, nothing is re-embedded with Voyage, and `registry_fixture.json` plus the recorded
cassettes stay valid. A re-seed would mint new versions and invalidate both.

Safe to re-run: same ids, so a second pass overwrites rather than duplicates.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.db import get_session, init_db
from app.eval.golden import seed_tenant_id
from app.registry.db import list_active_versions
from app.vectorstore.qdrant_store import QdrantStore, _point_id


async def _active_versions(tenant_id: str) -> dict[str, str]:
    await init_db()
    async with get_session() as session:
        return await list_active_versions(session, tenant_id=tenant_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", help="tenant to backfill (default: the pinned eval tenant)")
    args = parser.parse_args()

    if not get_settings().hybrid_search:
        # Without the flag `QdrantStore` has no sparse collection, and every write below would be a
        # silent no-op that reports success.
        print("HYBRID_SEARCH is off; set HYBRID_SEARCH=true to backfill.", file=sys.stderr)
        return 2

    tenant_id = args.tenant or seed_tenant_id()
    active = asyncio.run(_active_versions(tenant_id))
    if not active:
        print(f"tenant {tenant_id} has no ingested documents; nothing to backfill.", file=sys.stderr)
        return 1

    store = QdrantStore()
    total = 0
    for doc_id, version in sorted(active.items()):
        documents = store.get_document_chunks(doc_id, tenant_id, [version])
        ids = [_point_id(document.metadata["chunk_id"], version) for document in documents]
        store.upsert_sparse(documents, ids)
        total += len(documents)
        print(f"  {doc_id}: {len(documents)} chunks")
    print(f"backfilled {total} chunks across {len(active)} documents for tenant {tenant_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
