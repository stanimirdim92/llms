"""Flat table recording every ingested document (curated corpus and user uploads
alike), kept intentionally free of graph-shaped columns -- this is groundwork for an
eventual Neo4j sync job, not a graph model itself. See README.md's Document Registry
row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, func
from sqlmodel import Field, SQLModel

if TYPE_CHECKING:
    from datetime import datetime


class DocumentRecord(SQLModel, table=True):
    doc_id: str = Field(primary_key=True)
    tenant_id: str = Field(index=True)
    """`"global"` for the curated corpus, a real session id for uploads."""
    filename: str
    content_hash: str
    file_extension: str
    file_size_bytes: int
    chunk_count: int
    status: str = Field(default="ingested")
    uploaded_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    """Left unset on the Python side -- the DB's `server_default=now()` fills it in on
    first insert. Deliberately excluded from the upsert's UPDATE clause (see
    `db.save_document_record`) so a re-ingested document keeps its original ingestion
    timestamp rather than looking freshly created every time.
    """
