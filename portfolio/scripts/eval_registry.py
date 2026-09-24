"""Export the eval tenant's registry rows from a seeded database, or load them into an empty one.

    uv run python scripts/eval_registry.py export   # after seed_eval_corpus.py: write the fixture
    uv run python scripts/eval_registry.py load     # before run_eval.py --gate on a fresh database

Why this exists: the eval pipeline reads Postgres on every question. `list_active_versions`
decides which documents are searchable and at which generation, and metadata answers list the
documents. Recorded HTTP replay covers Anthropic, Voyage and Qdrant, but not a database. So a
CI gate needs these rows present, and they come from this committed fixture
(`data/eval/registry_fixture.json`).

Export after every re-seed, together with the baseline: `ingestion_version` changes on each
ingest, and the Qdrant queries recorded for replay filter on it.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth.models import Tenant
from app.db import get_session, init_db
from app.eval.golden import EVAL_DIR, seed_tenant_id
from app.registry.db import list_document_records, save_document_record
from app.registry.models import DocumentRecord

FIXTURE_PATH = EVAL_DIR / "registry_fixture.json"

_FIELDS = (
    "doc_id",
    "tenant_id",
    "filename",
    "content_hash",
    "file_extension",
    "file_size_bytes",
    "chunk_count",
    "ingestion_version",
    "status",
)
"""What retrieval and the metadata answer read. Timestamps are left out: they change on every
seed and would make the fixture diff noisily for no behavioural reason."""


async def _export() -> int:
    tenant_id = seed_tenant_id()
    await init_db()
    async with get_session() as session:
        tenant = await session.get(Tenant, tenant_id)
        # Through the registry helper, not a bare select: `get_session` is the app role, which
        # row-level security filters by tenant, and the helper sets that context. A bare select
        # would see zero rows and report an unseeded database that isn't.
        records = sorted(
            await list_document_records(session, tenant_id=tenant_id, limit=10_000), key=lambda r: r.doc_id
        )
    if tenant is None or not records:
        # An empty fixture would load "successfully" and every retrieval metric would read 0,
        # which looks like a retrieval regression rather than an unseeded database.
        print(f"no seeded eval tenant {tenant_id} here -- run seed_eval_corpus.py first", file=sys.stderr)
        return 1
    payload = {
        "tenant": {"id": tenant.id, "name": tenant.name},
        "documents": [{field: getattr(record, field) for field in _FIELDS} for record in records],
    }
    FIXTURE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE_PATH}: {len(records)} documents")
    return 0


async def _load() -> int:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if payload["tenant"]["id"] != seed_tenant_id():
        # The chunk ids in the golden set are a function of the pinned tenant id.
        print("fixture tenant does not match corpus_manifest.json's seed_tenant_id", file=sys.stderr)
        return 1
    await init_db()
    tenant_id = payload["tenant"]["id"]
    async with get_session() as session:
        if await session.get(Tenant, tenant_id) is None:
            session.add(Tenant(**payload["tenant"]))
            await session.commit()
        present = {r.doc_id for r in await list_document_records(session, tenant_id=tenant_id, limit=10_000)}
        added = 0
        for document in payload["documents"]:
            if document["doc_id"] in present:
                continue  # loading twice is a no-op, not a primary-key error
            # The registry helper sets the row-level-security tenant context the insert needs.
            await save_document_record(session, DocumentRecord(**document))
            added += 1
    print(f"loaded {added} documents for tenant {tenant_id} ({len(present)} already present)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "load"])
    args = parser.parse_args()
    return asyncio.run(_export() if args.action == "export" else _load())


if __name__ == "__main__":
    raise SystemExit(main())
