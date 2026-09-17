"""Reconstructs a document from its own indexed chunks, for viewing rather than answering.

Shared by `app/api/routers/documents.py` (`GET /v1/documents/{doc_id}/content`) and
`streamlit_app/Home.py`, the same way `AnswerService` and `QdrantStore` already are -- core
logic lives here, not in the router, so the two callers cannot quietly drift into two different
renderings of the same document the way `list_scope_candidates` once drifted from
`list_document_records` (see `docs/EPIC_2_PLAN.md`'s history of that).
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from langchain_core.documents import Document

log = structlog.get_logger(__name__)


def _figure_markdown(image_path: str | None, caption: str) -> str:
    """One figure, as Markdown: an embedded image (if its file is still readable) plus its
    caption. A missing file degrades to the caption alone rather than failing the whole
    document's view -- one figure's image going missing is not a reason to hide the rest of it.
    """
    if not image_path:
        return caption
    try:
        encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    except OSError:
        log.warning("document_view.figure_image_missing", image_path=image_path)
        return caption
    return f"![figure](data:image/png;base64,{encoded})\n\n*{caption}*"


def render_document(chunks: list[Document]) -> str:
    """Reconstructs a document from its chunks, in the order the caller already sorted them
    into (`Chunk.order_index` -- true reading order, not the grouped-by-kind order
    `chunk_document` returns; see that module's docstring).

    Deliberately renders what `/ask` can already see and cite, not a second parse of the
    original file: a table renders from the same `markdown` metadata the answer path embeds
    (not `page_content`, which may carry a caption prepended onto it -- see `chunker.py`), and a
    figure the vision pass dropped as unusable is simply absent here too, the same way it is
    absent from retrieval.
    """
    blocks: list[str] = []
    for chunk in chunks:
        metadata = chunk.metadata
        chunk_type = metadata.get("chunk_type", "text")
        if chunk_type == "table":
            blocks.append(metadata.get("markdown") or chunk.page_content)
        elif chunk_type == "figure":
            blocks.append(_figure_markdown(metadata.get("image_path"), chunk.page_content))
        else:
            blocks.append(chunk.page_content)
    return "\n\n".join(block for block in blocks if block)
