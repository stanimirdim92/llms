"""Pins the filename onto chunk metadata and into the model-visible block title.

Both halves matter and they fail independently. If the chunker stops stamping `filename`,
the Qdrant payload loses it silently and retrieval still works -- so nothing errors, and the
only symptom is that the model can no longer answer a question that names a file. If
`_chunk_title` stops rendering it, the payload is fine and the model still cannot see it.

The production symptom was a correct-but-useless answer: asked "tell me about
24383456-639402.pdf", the model summarised that exact document's contents while stating it
had no document by that name -- because the only label it was given was a 65-character
content-hash `doc_id`.
"""

from __future__ import annotations

from langchain_core.documents import Document

from app.generation.answer_service import _chunk_title
from app.ingestion.chunker import _base_metadata


def test_filename_is_stamped_when_known() -> None:
    assert _base_metadata("report.pdf") == {"filename": "report.pdf"}


def test_no_filename_stores_nothing_rather_than_an_empty_string() -> None:
    """An empty string would reach the payload and render as a blank title, which is worse
    than falling back to the doc_id.
    """
    assert _base_metadata("") == {}


def test_title_leads_with_the_filename() -> None:
    document = Document(
        page_content="...",
        metadata={"doc_id": "abc123", "filename": "24383456-639402.pdf", "chunk_type": "text", "page_no": 1},
    )

    title = _chunk_title(document)

    assert title.startswith("24383456-639402.pdf")
    assert "abc123" in title, "doc_id must stay in the title so citations remain traceable"


def test_title_falls_back_to_doc_id_for_chunks_ingested_before_filenames() -> None:
    """Points written before this change carry no `filename`, and must still render."""
    document = Document(page_content="...", metadata={"doc_id": "abc123", "chunk_type": "table"})

    title = _chunk_title(document)

    assert title.startswith("abc123")
    assert "None" not in title, "a missing filename must not leak a literal None into the title"


def test_title_survives_metadata_with_nothing_in_it() -> None:
    assert "unknown" in _chunk_title(Document(page_content="...", metadata={}))
