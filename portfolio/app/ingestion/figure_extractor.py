"""Save figure images from a parsed document and caption them with Claude vision so they
become searchable chunks.

Docling itself renders each PictureItem's image during parsing (when
`generate_picture_images=True`, set in `parser.py`) and exposes it via
`PictureItem.get_image(document)` -- so this does NOT re-open/re-crop the original PDF
with a second library. An earlier version of this file used PyMuPDF for that, which was
both an unnecessary dependency and required manually flipping Docling's bbox coordinate
origin to match PyMuPDF's, a needless source of bugs Docling already solves internally.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

from docling_core.types.doc.document import DoclingDocument, PictureItem
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, HumanMessage

from app.config import get_settings

if TYPE_CHECKING:
    from pathlib import Path

_CAPTION_PROMPT = (
    "Describe this figure from a scientific paper in 2-4 sentences. "
    "State what kind of figure it is (plot, micrograph, schematic, table-like chart, etc.), "
    "the axes/quantities shown if visible, and the key trend or result it conveys. "
    "Be factual and specific — this description is the only way the figure will be found by search."
)


@dataclass(frozen=True)
class ExtractedFigure:
    figure_id: str
    page_no: int
    image_path: Path
    caption: str


def _caption_message(image_bytes: bytes) -> HumanMessage:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    return HumanMessage(
        content=[
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
            },
            {"type": "text", "text": _CAPTION_PROMPT},
        ]
    )


def _response_text(response: BaseMessage) -> str:
    content = response.content
    if isinstance(content, str):
        return content.strip()
    text_blocks = (block for block in content if isinstance(block, dict) and block.get("type") == "text")
    return "".join(block.get("text", "") for block in text_blocks).strip()


def _caption_all(images: list[bytes]) -> list[str]:
    """Caption every figure concurrently, returning captions in the same order.

    `Runnable.batch` (not a hand-rolled thread pool) so concurrency stays a LangChain
    concern and results stay positionally aligned with the input. `max_concurrency` is
    bounded deliberately -- see the `figure_caption_concurrency` note in config.py. The
    client is built once here rather than per figure, which the previous per-call
    construction did needlessly.

    A failure in any single caption still aborts the whole ingest, exactly as the
    sequential version did -- `batch` re-raises rather than returning partial results.
    Making figure captioning individually fault-tolerant would be a behavior change, not
    a speedup, so it's deliberately left alone here.
    """
    settings = get_settings()
    llm = ChatAnthropic(
        model=settings.figure_caption_model,
        api_key=settings.anthropic_api_key,
        max_tokens=300,
        thinking={"type": "disabled"},
    )
    responses = llm.batch(
        [[_caption_message(image_bytes)] for image_bytes in images],
        config={"max_concurrency": settings.figure_caption_concurrency},
    )
    return [_response_text(response) for response in responses]


def extract_figures(document: DoclingDocument, output_dir: Path) -> list[ExtractedFigure]:
    """Save every picture region already rendered in `document` to a PNG and caption it."""
    output_dir.mkdir(parents=True, exist_ok=True)
    picture_items = [item for item, _level in document.iterate_items() if isinstance(item, PictureItem)]

    # Render and save first, caption second, so all the network calls can go out together.
    # `index` still comes from enumerate over *every* picture item, so an item with no
    # renderable image keeps consuming its index: figure_id feeds chunk_id, which feeds the
    # Qdrant point id, so renumbering figures here would orphan every already-stored figure
    # chunk instead of upserting over it.
    rendered: list[tuple[str, int, Path, bytes]] = []
    for index, item in enumerate(picture_items):
        image = item.get_image(document)
        if image is None:
            continue
        provenance = item.prov[0] if item.prov else None
        page_no = provenance.page_no if provenance else 0

        figure_id = f"fig-{page_no:03d}-{index:02d}"
        image_path = output_dir / f"{figure_id}.png"
        image.save(image_path, "PNG")

        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        rendered.append((figure_id, page_no, image_path, buffer.getvalue()))

    if not rendered:
        return []

    captions = _caption_all([image_bytes for *_, image_bytes in rendered])
    return [
        ExtractedFigure(figure_id=figure_id, page_no=page_no, image_path=image_path, caption=caption)
        for (figure_id, page_no, image_path, _), caption in zip(rendered, captions, strict=True)
    ]
