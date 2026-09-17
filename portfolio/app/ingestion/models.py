"""Plain data types shared across ingestion, embeddings, and the vector store.

Kept dependency-free (no docling import) so downstream modules don't have to pull in
the heavy parsing stack just to reference a Chunk.
"""

from dataclasses import dataclass, field
from typing import Literal

ChunkType = Literal["text", "table", "figure"]


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    chunk_type: ChunkType
    text: str
    tenant_id: str
    """Who owns this chunk. **Required, and deliberately without a default.**

    There used to be a `GLOBAL_TENANT = "global"` sentinel here, tagging a curated corpus that
    every tenant could read, and this field defaulted to it. Both are gone: the corpus was
    removed, and with it the only value a default could sensibly have.

    Leaving the field defaulted after that would be the dangerous half of the change. A
    forgotten `tenant_id=` would then silently bind a chunk to whatever the default happened to
    be, which is one tenant's document filed under another's name -- and retrieval would return
    it, not error. Required means that mistake is a `TypeError` at the call site instead.

    Ordered before the optional fields because it is required; every construction in this
    project passes fields by keyword, so the position is not load-bearing.
    """
    page_no: int | None = None
    section_path: str = ""
    metadata: dict = field(default_factory=dict)
    order_index: int = 0
    """Position in the document's true reading order (`document_order.document_order_map`),
    not in this chunk's own type-grouped pass. `chunk_document` emits every text chunk, then
    every table chunk, then every figure chunk -- so *list* order is not *document* order, and
    a viewer reconstructing the document (`GET /v1/documents/{doc_id}/content`) sorts on this
    field instead. Defaulted rather than required: unlike `tenant_id`, a wrong or missing value
    here mis-orders a preview, it does not leak data, so the many tests constructing a bare
    `Chunk` for unrelated reasons do not all need updating for it.
    """
