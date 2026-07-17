"""Save figure images from a parsed document and caption them with Claude vision so they
become searchable chunks.

Docling itself renders each PictureItem's image during parsing (when
`generate_picture_images=True`, set in `parser.py`) and exposes it via
`PictureItem.get_image(document)` -- so this does NOT re-open/re-crop the original PDF
with a second library. An earlier version of this file used PyMuPDF for that, which was
both an unnecessary dependency and required manually flipping Docling's bbox coordinate
origin to match PyMuPDF's, a needless source of bugs Docling already solves internally.
"""

import base64
import io
from dataclasses import dataclass
from pathlib import Path

from docling_core.types.doc.document import DoclingDocument, PictureItem
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from app.config import get_settings

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


def _caption_with_claude(image_bytes: bytes) -> str:
    settings = get_settings()
    llm = ChatAnthropic(
        model=settings.figure_caption_model,
        api_key=settings.anthropic_api_key,
        max_tokens=300,
        thinking={"type": "disabled"},
    )
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    message = HumanMessage(
        content=[
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
            },
            {"type": "text", "text": _CAPTION_PROMPT},
        ]
    )
    response = llm.invoke([message])
    content = response.content
    if isinstance(content, str):
        return content.strip()
    return "".join(block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text").strip()


def extract_figures(document: DoclingDocument, output_dir: Path) -> list[ExtractedFigure]:
    """Save every picture region already rendered in `document` to a PNG and caption it."""
    figures: list[ExtractedFigure] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    picture_items = [item for item, _level in document.iterate_items() if isinstance(item, PictureItem)]

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
        caption = _caption_with_claude(buffer.getvalue())
        figures.append(ExtractedFigure(figure_id=figure_id, page_no=page_no, image_path=image_path, caption=caption))

    return figures
