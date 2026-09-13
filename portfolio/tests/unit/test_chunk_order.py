"""`Chunk.order_index`: the fix for `chunk_document`'s output not being document reading order.

`chunk_document` returns every text chunk, then every table chunk, then every figure chunk --
see that module's docstring for why the three cannot share one loop. A table appearing on
page 3 therefore lands after every text chunk in the whole document in the returned *list*,
which is fine for retrieval (nothing there cares about list order) and wrong for reconstructing
a document to view. `order_index` is computed once, from a single traversal that walks every
item type together, and this file is the only place that would notice it silently going back
to always-zero -- which would make a table or figure sort no differently from the position it
happened to occupy in `chunk_document`'s own grouped list, exactly the bug this exists to catch.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from docling_core.types.doc.base import BoundingBox, CoordOrigin
from docling_core.types.doc.document import (
    DoclingDocument,
    NodeItem,
    PictureItem,
    ProvenanceItem,
    TableCell,
    TableData,
    TableItem,
    TextItem,
)
from docling_core.types.doc.labels import DocItemLabel
from PIL import Image

from app.ingestion import chunker as chunker_module, figure_extractor
from app.ingestion.chunker import chunk_document
from app.ingestion.document_order import document_order_map
from app.ingestion.figure_extractor import ExtractedFigure, extract_figures

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

TENANT = "a" * 32


def _document(items: Sequence[NodeItem]) -> DoclingDocument:
    """A document whose `iterate_items` yields exactly `items`, in the order given -- standing
    in for Docling's own true reading-order traversal. Same pattern as `test_chunk_ids.py`.
    """

    class _StubDocument(DoclingDocument):
        def iterate_items(self, *_args: object, **_kwargs: object) -> Iterator[tuple[NodeItem, int]]:
            return ((item, 0) for item in items)

    return _StubDocument(name="test")


def _text_item(ref: str) -> TextItem:
    return TextItem(self_ref=ref, label=DocItemLabel.TEXT, text=ref, orig=ref)


def _table_item(ref: str, page_no: int = 1) -> TableItem:
    prov = ProvenanceItem(
        page_no=page_no, bbox=BoundingBox(l=0, t=0, r=1, b=1, coord_origin=CoordOrigin.TOPLEFT), charspan=(0, 0)
    )
    cell = TableCell(
        text="x", start_row_offset_idx=0, end_row_offset_idx=1, start_col_offset_idx=0, end_col_offset_idx=1
    )
    data = TableData(num_rows=1, num_cols=1, table_cells=[cell])
    return TableItem(self_ref=ref, data=data, prov=[prov])


def _docling_chunk(text: str, doc_items: Sequence[NodeItem]) -> SimpleNamespace:
    return SimpleNamespace(text=text, meta=SimpleNamespace(doc_items=list(doc_items), headings=[]))


class _Renderable(PictureItem):
    """A picture Docling could rasterize -- same stand-in as `test_figure_ids.py`."""

    def get_image(self, *_args: object, **_kwargs: object) -> Image.Image:
        return Image.new("RGB", (128, 128), "white")


@pytest.fixture(autouse=True)
def _stub_chunker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same stub as `test_chunk_ids.py`: neutralises the tokenizer download and hands
    `chunk_document` whatever `_chunks` holds, keyed off each fake chunk's own `doc_items`.
    """
    monkeypatch.setattr(
        chunker_module.HuggingFaceTokenizer, "from_pretrained", classmethod(lambda _cls, **_kwargs: object())
    )

    class _StubChunker:
        def __init__(self, *, tokenizer: object) -> None:
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


def test_document_order_map_numbers_items_by_traversal_position() -> None:
    a, b, c = _text_item("#/texts/0"), _table_item("#/tables/0"), _text_item("#/texts/1")

    order = document_order_map(_document([a, b, c]))

    assert order == {"#/texts/0": 0, "#/tables/0": 1, "#/texts/1": 2}


def test_a_table_between_two_paragraphs_sorts_between_them_not_after_both() -> None:
    """The money test. `chunk_document`'s own returned *list* is grouped by kind -- text, then
    table -- so asserting on the list itself would prove nothing about reconstruction order.
    Sorting by `order_index` is what has to recover "text, table, text".
    """
    first, table, second = _text_item("#/texts/0"), _table_item("#/tables/0", page_no=1), _text_item("#/texts/1")
    document = _document([first, table, second])
    _chunks.append(_docling_chunk("first paragraph", doc_items=[first]))
    _chunks.append(_docling_chunk("second paragraph", doc_items=[second]))

    chunks = chunk_document(tenant_id=TENANT, document=document, doc_id="doc", figures=[])

    # The bug this fixes: list order is grouped by kind, not by position in the document.
    assert [chunk.chunk_type for chunk in chunks] == ["text", "text", "table"]

    reconstructed = sorted(chunks, key=lambda chunk: chunk.order_index)
    assert [chunk.chunk_type for chunk in reconstructed] == ["text", "table", "text"]
    assert reconstructed[0].text == "first paragraph"
    assert reconstructed[2].text == "second paragraph"


def test_a_figure_between_two_paragraphs_also_sorts_correctly(tmp_path: Path) -> None:
    """The same fix, exercised for the third kind. `ExtractedFigure.order_index` is computed in
    `extract_figures`, from its own call to `document_order_map` over the same document -- this
    asserts the two never disagree about where the picture actually sits.
    """
    first, picture, second = _text_item("#/texts/0"), PictureItem(self_ref="#/pictures/0"), _text_item("#/texts/1")
    document = _document([first, picture, second])
    _chunks.append(_docling_chunk("first paragraph", doc_items=[first]))
    _chunks.append(_docling_chunk("second paragraph", doc_items=[second]))
    figure = ExtractedFigure(
        figure_id="fig-001-00",
        page_no=1,
        image_path=tmp_path / "unused.png",  # chunk_document only stores the path, never reads it
        caption="A schematic.",
        order_index=document_order_map(document)[picture.self_ref],
    )

    chunks = chunk_document(tenant_id=TENANT, document=document, doc_id="doc", figures=[figure])
    reconstructed = sorted(chunks, key=lambda chunk: chunk.order_index)

    assert [chunk.chunk_type for chunk in reconstructed] == ["text", "figure", "text"]


def test_a_merged_text_chunk_orders_by_its_earliest_item() -> None:
    """`HybridChunker` can merge several underlying items into one semantic window. The chunk
    must sort where it *starts*, not where it ends -- otherwise a long paragraph that absorbed
    a later sentence would appear to come after content it actually precedes.
    """
    early, late, table = _text_item("#/texts/0"), _text_item("#/texts/1"), _table_item("#/tables/0")
    document = _document([early, late, table])
    _chunks.append(_docling_chunk("merged window", doc_items=[early, late]))

    chunks = chunk_document(tenant_id=TENANT, document=document, doc_id="doc", figures=[])

    text_chunk = next(chunk for chunk in chunks if chunk.chunk_type == "text")
    table_chunk = next(chunk for chunk in chunks if chunk.chunk_type == "table")
    assert text_chunk.order_index == 0, "must use the earliest doc_item, not the latest"
    assert text_chunk.order_index < table_chunk.order_index


def test_an_item_the_traversal_does_not_yield_sorts_last_rather_than_raising() -> None:
    """A `doc_item` absent from `document.iterate_items()`'s traversal (a content layer or group
    it excludes) must not crash an otherwise-good ingest over an ordering nicety -- it sorts
    after everything the map does resolve, which is a cosmetic miss, not a failure.
    """
    known = _text_item("#/texts/0")
    unknown = _text_item("#/texts/99")  # never appears in the document passed to chunk_document
    document = _document([known])
    _chunks.append(_docling_chunk("orphaned window", doc_items=[unknown]))

    chunks = chunk_document(tenant_id=TENANT, document=document, doc_id="doc", figures=[])

    assert chunks[0].order_index == 1, "one item in the map -> unresolved items sort at index 1, i.e. last"


def test_extract_figures_assigns_order_index_from_the_same_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    caption = "A line plot of discharge capacity against cycle number for three cathode materials."
    monkeypatch.setattr(figure_extractor, "_caption_all", lambda images: [caption] * len(images))
    early, picture, late = _text_item("#/texts/0"), _Renderable(self_ref="#/pictures/0"), _text_item("#/texts/1")
    document = _document([early, picture, late])

    figures = extract_figures(document, tmp_path)

    assert figures[0].order_index == 1
