"""composite indexes for the two per-tenant hot-path queries

Revision ID: c7e2a9f13b58
Revises: a4f8c1d92e07
Create Date: 2026-08-07 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c7e2a9f13b58"
down_revision: str | None = "a4f8c1d92e07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Measured against a real Postgres, not assumed (rule 14) -- seeded 10,000 tenants x 10
    # documents (this project's own scale target, docs/MEMORY.md § Standing directives) plus one
    # deliberate 20,000-document "whale" tenant, since the target's *average* is already too small
    # for either query to notice a missing index (both run in well under 1ms against a 10-document
    # tenant on the existing single-column `tenant_id` index alone). The whale is what a real
    # customer base looks like once usage is uneven, which is the case that actually matters once
    # monetization means real, unevenly-sized tenants.
    #
    # `list_active_versions` (app/registry/db.py), read on *every* `/ask` request: baseline 6.06ms
    # against the whale tenant, `Bitmap Heap Scan` pulling all 20,000 of its rows off the heap and
    # filtering ~80% of them out in memory. A partial, covering index matching this query's exact
    # predicate turns it into an `Index Only Scan` with zero heap fetches -- 2.2-3.9ms warmed up
    # (repeated runs, not the first cold one -- rule 14). The win is smaller than the other index
    # below because this query has no LIMIT: it must still return every active document a tenant
    # has, so the remaining time is proportional to that count regardless of indexing. At true
    # scale that is itself worth watching -- a tenant with tens of thousands of active documents
    # makes every /ask pay for materialising all of their ids, which no index removes.
    op.execute("""
        CREATE INDEX ix_documentrecord_tenant_active_version
        ON documentrecord (tenant_id)
        INCLUDE (doc_id, ingestion_version)
        WHERE status = 'ingested' AND ingestion_version IS NOT NULL
    """)

    # `list_document_records` (app/registry/db.py), `GET /v1/documents` and /ask's document-name
    # scoping: baseline 6.04ms against the whale tenant, `Bitmap Heap Scan` over all 20,000 rows
    # followed by an in-memory sort to find the newest 100. `LIMIT` is what makes this one's win
    # dramatic rather than modest: with `(tenant_id, uploaded_at DESC)` as a plain composite (not
    # partial -- every status needs to be listable), Postgres walks the index in the exact output
    # order and stops after 100 rows without ever sorting or reading the other 19,900. Warmed-up
    # execution time: 6.04ms -> 0.39-0.56ms, roughly 11-15x. Confirmed the existing average-case
    # tenant (10 documents) is not regressed -- both queries stay under 0.25ms there, using
    # whichever index the planner judges cheaper for that row count.
    op.execute("CREATE INDEX ix_documentrecord_tenant_uploaded_at ON documentrecord (tenant_id, uploaded_at DESC)")

    # Both indexes are plain `CREATE INDEX`, not `CREATE INDEX CONCURRENTLY`, and that is a real
    # tradeoff rather than an oversight: a regular `CREATE INDEX` takes `ShareLock` and blocks
    # writes to `documentrecord` for the build's duration, while `CONCURRENTLY` does not -- but
    # `CONCURRENTLY` is disallowed inside a transaction, and `init_db()` runs the entire migration
    # chain inside one transaction on purpose (the `pg_advisory_xact_lock` that serializes
    # concurrent first boots has to cover the whole chain atomically). Harmless today -- this
    # project has no production data yet (docs/MEMORY.md § Standing directives) -- but the day a
    # real deployment carries live traffic, adding a table-blocking index to it needs
    # `CREATE INDEX CONCURRENTLY` run outside this chain (a one-off `psql` session, or a dedicated
    # migration on a connection that isn't nested inside `init_db`'s transaction), not a migration
    # that runs unattended at boot.


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documentrecord_tenant_uploaded_at")
    op.execute("DROP INDEX IF EXISTS ix_documentrecord_tenant_active_version")
