"""Sync SQLAlchemy engine/session for the document registry -- deliberately sync,
matching `ingest_document`'s existing sync nature. This session's scope was the Qdrant
swap plus this registry, not re-asyncifying ingestion, so this stays consistent with
today's pipeline rather than introducing an async/sync split within it.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy import Engine, create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, SQLModel

from app.config import get_settings
from app.registry.models import DocumentRecord

if TYPE_CHECKING:
    from collections.abc import Iterator


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.database_url)


@lru_cache
def init_db() -> None:
    """Create tables that don't exist yet. `lru_cache` makes this a run-once-per-process
    guard, so callers (there are three: the API, Streamlit, and scripts/ingest.py) can
    call it unconditionally instead of each having to remember to call it exactly once.
    No Alembic for one table -- revisit if a second table shows up.
    """
    SQLModel.metadata.create_all(get_engine())


@contextmanager
def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def save_document_record(session: Session, record: DocumentRecord) -> None:
    """Upsert keyed on `doc_id`: re-ingesting identical content (already an idempotent
    upsert at the Qdrant layer via `upsert`-by-id) stays idempotent here too.

    `uploaded_at` is excluded from both the insert values and the ON CONFLICT update --
    see the field's docstring in `models.py` for why.
    """
    values = record.model_dump(exclude={"uploaded_at"})
    stmt = pg_insert(DocumentRecord).values(**values)
    update_columns = {key: getattr(stmt.excluded, key) for key in values if key != "doc_id"}
    stmt = stmt.on_conflict_do_update(index_elements=["doc_id"], set_=update_columns)
    session.exec(stmt)  # SQLModel's Session.exec (not the deprecated raw .execute())
    session.commit()
