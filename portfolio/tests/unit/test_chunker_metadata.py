from structlog.testing import capture_logs

from app.ingestion.models import Chunk
from app.vectorstore.qdrant_store import _chunk_metadata


def test_text_chunk_metadata_has_no_page_when_unknown() -> None:
    chunk = Chunk(chunk_id="doc-text-0000", doc_id="doc", chunk_type="text", text="hello", page_no=None)

    metadata = _chunk_metadata(chunk)

    assert metadata["doc_id"] == "doc"
    assert metadata["chunk_type"] == "text"
    assert metadata["tenant_id"] == "global"
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


def test_a_non_primitive_metadata_value_is_dropped_and_logged() -> None:
    """Qdrant payloads take primitives, so a list or dict is dropped here. That part is right --
    a caller mistake should not fail an otherwise good ingest -- but it was silent, and the
    symptom of silence is a key simply absent from the payload later, whose first reading is
    "ingestion never ran" rather than "your value was a list".
    """
    chunk = Chunk(
        chunk_id="doc-text-0000",
        doc_id="doc",
        chunk_type="text",
        text="hello",
        page_no=None,
        metadata={"filename": "report.pdf", "authors": ["a", "b"], "extra": {"nested": 1}},
    )

    # `structlog.testing.capture_logs`, not `caplog` and not `capsys`. caplog sees nothing:
    # structlog renders through its own pipeline, not the stdlib handlers. capsys worked in
    # isolation and failed in the full suite, because another module calls `configure_logging`
    # and where the output goes stops being stdout -- a test that passes alone and fails in
    # company is worse than one that never passed.
    with capture_logs() as captured:
        metadata = _chunk_metadata(chunk)

    assert metadata["filename"] == "report.pdf"
    assert "authors" not in metadata
    assert "extra" not in metadata
    events = [entry for entry in captured if entry["event"] == "qdrant.metadata_dropped"]
    assert events, "the drop must be visible; silence reads as ingestion never having run"
    assert sorted(events[0]["keys"]) == ["authors", "extra"]
