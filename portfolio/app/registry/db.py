"""Document-registry writes. The engine/session they run on lives in `app/db.py`, which
`app/auth/` shares -- see that module's docstring for why it moved out of here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.registry.models import DocumentRecord

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


async def save_document_record(session: AsyncSession, record: DocumentRecord) -> None:
    """Upsert keyed on `doc_id`, so re-ingesting a document updates its row rather than
    adding a second one.

    `uploaded_at` is excluded from both the insert values and the ON CONFLICT update --
    see the field's docstring in `models.py` for why.
    """
    values = record.model_dump(exclude={"uploaded_at"})
    stmt = pg_insert(DocumentRecord).values(**values)
    update_columns = {key: getattr(stmt.excluded, key) for key in values if key != "doc_id"}
    stmt = stmt.on_conflict_do_update(index_elements=["doc_id"], set_=update_columns)
    await session.exec(stmt)  # SQLModel's Session.exec (not the deprecated raw .execute())
    await session.commit()
