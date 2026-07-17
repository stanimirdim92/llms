"""Crop figure regions from a PDF and caption them with Claude vision so they become searchable chunks."""

import base64
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
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


def _crop_to_png(pdf_path: Path, page_no: int, bbox_pdf_coords: tuple[float, float, float, float], out_path: Path) -> None:
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_no - 1]
        rect = fitz.Rect(*bbox_pdf_coords)
        pix = page.get_pixmap(clip=rect, dpi=200)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out_path))
    finally:
        doc.close()


def _caption_with_claude(image_path: Path) -> str:
    settings = get_settings()
    llm = ChatAnthropic(model=settings.figure_caption_model, api_key=settings.anthropic_api_key, max_tokens=300)
    image_b64 = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")
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


def extract_figures(document: DoclingDocument, pdf_path: Path, output_dir: Path) -> list[ExtractedFigure]:
    """Crop every picture region in `document` to a PNG and caption it with Claude vision."""
    figures: list[ExtractedFigure] = []
    picture_items = [item for item, _level in document.iterate_items() if isinstance(item, PictureItem)]

    for index, item in enumerate(picture_items):
        provenance = item.prov[0] if item.prov else None
        if provenance is None:
            continue

        page_no = provenance.page_no
        bbox = provenance.bbox
        page_size = document.pages[page_no].size
        # Docling bboxes are bottom-left origin; PyMuPDF/fitz rects are top-left origin.
        pdf_bbox = (
            bbox.l,
            page_size.height - bbox.t,
            bbox.r,
            page_size.height - bbox.b,
        )

        figure_id = f"fig-{page_no:03d}-{index:02d}"
        image_path = output_dir / f"{figure_id}.png"
        _crop_to_png(pdf_path, page_no, pdf_bbox, image_path)
        caption = _caption_with_claude(image_path)
        figures.append(ExtractedFigure(figure_id=figure_id, page_no=page_no, image_path=image_path, caption=caption))

    return figures
