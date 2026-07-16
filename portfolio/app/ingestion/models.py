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
    page_no: int | None = None
    section_path: str = ""
    metadata: dict = field(default_factory=dict)
