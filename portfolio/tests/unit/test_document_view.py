"""`app.generation.document_view.render_document`: reconstructing a document from its chunks.

Shared by `GET /v1/documents/{doc_id}/content` and the Streamlit "View" action, which is the
whole reason this lives here rather than in the router -- see the module docstring for why a
second, drifted copy is the failure this split exists to avoid.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.documents import Document

from app.generation import document_view

if TYPE_CHECKING:
    from pathlib import Path


def test_text_chunks_render_as_plain_prose() -> None:
    chunks = [Document(page_content="First paragraph.", metadata={"chunk_type": "text"})]

    assert document_view.render_document(chunks) == "First paragraph."


def test_multiple_chunks_are_joined_in_the_order_given() -> None:
    """The caller (`QdrantStore.get_document_chunks`) already sorted by `order_index` --
    rendering must not re-sort or otherwise second-guess that order.
    """
    chunks = [
        Document(page_content="First.", metadata={"chunk_type": "text"}),
        Document(page_content="| a | b |", metadata={"chunk_type": "table", "markdown": "| a | b |"}),
        Document(page_content="Last.", metadata={"chunk_type": "text"}),
    ]

    rendered = document_view.render_document(chunks)

    assert rendered.index("First.") < rendered.index("| a | b |") < rendered.index("Last.")


def test_a_table_renders_its_markdown_not_its_possibly_captioned_page_content() -> None:
    """A table chunk's `page_content` may carry a caption prepended onto it for embedding
    quality (see `chunker.py`); the view renders the stored `markdown` field instead, or a
    captioned table would show the caption glued directly onto the grid with no separation.
    """
    chunk = Document(
        page_content="Table 1: results.\n\n| a | b |",
        metadata={"chunk_type": "table", "markdown": "| a | b |"},
    )

    assert document_view.render_document([chunk]) == "| a | b |"


def test_a_table_with_no_markdown_metadata_falls_back_to_its_page_content() -> None:
    """Defensive, not expected in practice: every table chunk `chunker.py` produces carries
    `markdown`. Falling back rather than rendering nothing keeps a malformed chunk visible
    instead of silently vanishing from the view.
    """
    chunk = Document(page_content="| a | b |", metadata={"chunk_type": "table"})

    assert document_view.render_document([chunk]) == "| a | b |"


def test_a_figure_with_a_readable_image_embeds_it_as_a_data_uri(tmp_path: Path) -> None:
    png_path = tmp_path / "fig.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    figure = Document(
        page_content="A schematic of the cell.", metadata={"chunk_type": "figure", "image_path": str(png_path)}
    )

    rendered = document_view.render_document([figure])

    assert rendered.startswith("![figure](data:image/png;base64,")
    assert "A schematic of the cell." in rendered


def test_a_figure_with_a_missing_image_falls_back_to_its_caption_alone() -> None:
    """The image file going missing (deleted disk, a bad path) must not hide the caption too --
    degrade to text, don't drop the figure from the view entirely.
    """
    figure = Document(
        page_content="A schematic of the cell.",
        metadata={"chunk_type": "figure", "image_path": "/no/such/file.png"},
    )

    rendered = document_view.render_document([figure])

    assert rendered == "A schematic of the cell."
    assert "data:image" not in rendered


def test_a_figure_with_no_image_path_at_all_renders_only_its_caption() -> None:
    """A figure chunk always carries `image_path` in practice, but the field is read with
    `.get`, so a chunk missing it must degrade the same way a missing file does, not raise.
    """
    figure = Document(page_content="A schematic of the cell.", metadata={"chunk_type": "figure"})

    assert document_view.render_document([figure]) == "A schematic of the cell."


def test_an_empty_chunk_list_renders_an_empty_string() -> None:
    assert document_view.render_document([]) == ""
