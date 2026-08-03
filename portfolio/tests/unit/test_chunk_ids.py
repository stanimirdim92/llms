"""`chunk_document`'s id accounting and the three chunk kinds it emits.

Untested until now, and it is the one function whose output *is* the index: `chunk_id` feeds
the Qdrant point id (`uuid5` of it), so a change in how these strings are built rewrites every
point for every document. `test_figure_ids.py` pins the figure half of that scheme; this pins
the text and table halves, plus the two skips that keep a table from being stored twice.

Docling's `HybridChunker` is stubbed, deliberately. It is not the thing under test -- the
accounting around it is -- and constructing a real one calls
`HuggingFaceTokenizer.from_pretrained`, which reaches out to huggingface.co. Measured here:
with no egress to the hub that call hangs with no timeout rather than failing, so a real
chunker in a unit suite is a test that either takes a network round trip or never returns.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from docling_core.types.doc.base import BoundingBox, CoordOrigin
from docling_core.types.doc.document import (
    DoclingDocument,
    NodeItem,
    ProvenanceItem,
    TableCell,
    TableData,
    TableItem,
)

from app.ingestion import chunker as chunker_module
from app.ingestion.chunker import chunk_document
from app.ingestion.figure_extractor import ExtractedFigure

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path


def _table(page_no: int = 4, index: int = 0) -> TableItem:
    data = TableData(
        num_rows=1,
        num_cols=2,
        table_cells=[
            TableCell(
                text=text,
                start_row_offset_idx=0,
                end_row_offset_idx=1,
                start_col_offset_idx=column,
                end_col_offset_idx=column + 1,
            )
            for column, text in enumerate(("a", "b"))
        ],
    )
    prov = ProvenanceItem(
        page_no=page_no,
        bbox=BoundingBox(l=0, t=0, r=1, b=1, coord_origin=CoordOrigin.TOPLEFT),
        charspan=(0, 0),
    )
    return TableItem(self_ref=f"#/tables/{index}", data=data, prov=[prov])


def _document(items: Sequence[NodeItem]) -> DoclingDocument:
    """A document whose `iterate_items` yields exactly `items`.

    Subclassed rather than monkeypatched, for the same reason as `test_figure_ids.py`:
    `DoclingDocument` is a pydantic model, so assigning a method onto an instance raises
    "object has no field".
    """

    class _StubDocument(DoclingDocument):
        def iterate_items(self, *_args: object, **_kwargs: object) -> Iterator[tuple[NodeItem, int]]:
            return ((item, 0) for item in items)

    return _StubDocument(name="test")


def _docling_chunk(text: str, doc_items: Sequence[NodeItem] = (), headings: Sequence[str] = ()) -> SimpleNamespace:
    """Stands in for a `BaseChunk`. `chunk_document` reads only `.meta.doc_items` and
    `.meta.headings` off it, and gets the text back from `contextualize`.
    """
    return SimpleNamespace(text=text, meta=SimpleNamespace(doc_items=list(doc_items), headings=list(headings)))


@pytest.fixture(autouse=True)
def _stub_chunker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise the tokenizer download and hand `chunk_document` whatever `_chunks` holds."""
    monkeypatch.setattr(
        chunker_module.HuggingFaceTokenizer, "from_pretrained", classmethod(lambda _cls, **_kwargs: object())
    )

    class _StubChunker:
        def __init__(self, tokenizer: object) -> None:
            self._tokenizer = tokenizer

        def chunk(self, _document: DoclingDocument) -> Iterator[SimpleNamespace]:
            return iter(_chunks)

        def contextualize(self, chunk: SimpleNamespace) -> str:
            return chunk.text

    monkeypatch.setattr(chunker_module, "HybridChunker", _StubChunker)


_chunks: list[SimpleNamespace] = []


@pytest.fixture(autouse=True)
def _reset_chunks() -> Iterator[None]:
    _chunks.clear()
    yield
    _chunks.clear()


def test_text_chunks_are_numbered_from_zero_in_order() -> None:
    _chunks.extend([_docling_chunk("first"), _docling_chunk("second")])

    chunks = chunk_document(_document([]), doc_id="doc", figures=[])

    assert [chunk.chunk_id for chunk in chunks] == ["doc-text-0000", "doc-text-0001"]


def test_a_blank_chunk_is_dropped_and_does_not_consume_a_number() -> None:
    """The numbering is compacted, not sparse -- which is safe only because
    `QdrantStore.upsert` deletes every point for the doc_id before inserting. Without that
    delete, a Docling upgrade that stopped emitting one blank chunk would renumber everything
    after it and leave the old points behind, retrievable and stale. Note this is the
    *opposite* convention to `figure_id`, which deliberately keeps skipped indices; if the two
    ever have to agree, change them together and say which one won.
    """
    _chunks.extend([_docling_chunk("first"), _docling_chunk("   \n  "), _docling_chunk("third")])

    chunks = chunk_document(_document([]), doc_id="doc", figures=[])

    assert [chunk.chunk_id for chunk in chunks] == ["doc-text-0000", "doc-text-0001"]
    assert [chunk.text for chunk in chunks] == ["first", "third"]


def test_a_chunk_containing_a_table_is_not_also_stored_as_prose() -> None:
    """The chunker walks the whole document, tables included, so without this skip every table
    is embedded twice -- once as flowing text and once atomically -- and the two copies then
    compete for the same rerank slots with the prose version usually winning, which is the
    version with the row structure flattened out of it.
    """
    table = _table()
    _chunks.extend([_docling_chunk("prose"), _docling_chunk("| a | b |", doc_items=[table])])

    chunks = chunk_document(_document([]), doc_id="doc", figures=[])

    assert [chunk.chunk_type for chunk in chunks] == ["text"]


def test_headings_become_the_section_path() -> None:
    _chunks.append(_docling_chunk("body", headings=["Results", "Ablations"]))

    chunks = chunk_document(_document([]), doc_id="doc", figures=[])

    assert chunks[0].section_path == "Results > Ablations"


def test_a_text_chunk_with_no_provenance_has_no_page() -> None:
    """`page_no=None` has to survive to the payload as *absent*, not as 0 -- page 0 does not
    exist, and a citation rendering "p. 0" is worse than one rendering no page at all.
    """
    _chunks.append(_docling_chunk("body"))

    chunks = chunk_document(_document([]), doc_id="doc", figures=[])

    assert chunks[0].page_no is None


def test_tables_are_numbered_separately_from_text() -> None:
    """Two independent counters, so adding a paragraph cannot renumber a table."""
    _chunks.append(_docling_chunk("prose"))

    chunks = chunk_document(_document([_table(index=0), _table(index=1)]), doc_id="doc", figures=[])

    assert [chunk.chunk_id for chunk in chunks] == ["doc-text-0000", "doc-table-0000", "doc-table-0001"]


def test_a_table_carries_its_markdown_in_metadata_as_well_as_its_text() -> None:
    """The text is what gets embedded; the metadata copy is what a client can re-render. They
    are deliberately not the same string -- the text may have a caption prepended.
    """
    chunks = chunk_document(_document([_table()]), doc_id="doc", figures=[])

    assert chunks[0].chunk_type == "table"
    assert chunks[0].page_no == 4
    assert chunks[0].metadata["markdown"].startswith("| a")
    assert chunks[0].text == chunks[0].metadata["markdown"], "no caption on this fixture, so they match"


def test_a_figure_chunk_is_its_caption_keyed_by_figure_id(tmp_path: Path) -> None:
    """The caption is the figure's only searchable text, and `chunk_id` is `doc_id` + the
    figure's own id -- not a fresh counter -- so figure chunk ids stay stable when the prose
    around them changes.
    """
    figure = ExtractedFigure(
        figure_id="fig-005-02",
        page_no=5,
        image_path=tmp_path / "fig-005-02.png",
        caption="A line plot of capacity against cycle number.",
    )

    chunks = chunk_document(_document([]), doc_id="doc", figures=[figure])

    assert chunks[0].chunk_id == "doc-fig-005-02"
    assert chunks[0].chunk_type == "figure"
    assert chunks[0].text == figure.caption
    assert chunks[0].metadata["image_path"] == str(figure.image_path)


def test_the_filename_and_tenant_reach_every_chunk_kind(tmp_path: Path) -> None:
    """One assertion over all three kinds on purpose. `tenant_id` is what scopes retrieval, and
    a kind that dropped it would be readable by every tenant -- silently, since a missing
    filter returns results rather than raising.
    """
    _chunks.append(_docling_chunk("prose"))
    figure = ExtractedFigure(figure_id="fig-001-00", page_no=1, image_path=tmp_path / "f.png", caption="A schematic.")

    chunks = chunk_document(
        _document([_table()]), doc_id="doc", figures=[figure], tenant_id="tenant-a", filename="report.pdf"
    )

    assert {chunk.chunk_type for chunk in chunks} == {"text", "table", "figure"}
    assert all(chunk.tenant_id == "tenant-a" for chunk in chunks)
    assert all(chunk.metadata["filename"] == "report.pdf" for chunk in chunks)
