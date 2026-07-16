from app.ingestion.models import Chunk
from app.vectorstore.chroma_store import _chunk_metadata


def test_text_chunk_metadata_has_no_page_when_unknown() -> None:
    chunk = Chunk(chunk_id="doc-text-0000", doc_id="doc", chunk_type="text", text="hello", page_no=None)

    metadata = _chunk_metadata(chunk)

    assert metadata["doc_id"] == "doc"
    assert metadata["chunk_type"] == "text"
    assert "page_no" not in metadata


def test_table_chunk_metadata_includes_page_and_markdown() -> None:
    chunk = Chunk(
        chunk_id="doc-table-0000",
        doc_id="doc",
        chunk_type="table",
        text="| a | b |\n|---|---|\n| 1 | 2 |",
        page_no=3,
        metadata={"markdown": "| a | b |\n|---|---|\n| 1 | 2 |"},
    )

    metadata = _chunk_metadata(chunk)

    assert metadata["page_no"] == 3
    assert metadata["chunk_type"] == "table"
    assert "markdown" in metadata


def test_figure_chunk_metadata_includes_image_path() -> None:
    chunk = Chunk(
        chunk_id="doc-fig-001-00",
        doc_id="doc",
        chunk_type="figure",
        text="A plot of capacity retention vs cycle number.",
        page_no=5,
        metadata={"image_path": "/tmp/doc/figures/fig-005-00.png"},
    )

    metadata = _chunk_metadata(chunk)

    assert metadata["chunk_type"] == "figure"
    assert metadata["image_path"] == "/tmp/doc/figures/fig-005-00.png"
