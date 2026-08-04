"""`chunk_document`'s id accounting and the three chunk kinds it emits.

Untested until now, and it is the one function whose output *is* the index: `chunk_id` feeds
the Qdrant point id (`uuid5` of it), so a change in how these strings are built rewrites every
point for every document. `test_figure_ids.py` pins the figure half of that scheme; this pins
the text and table halves, plus the two skips that keep a table from being stored twice.

Docling's `HybridChunker` is stubbed, deliberately. It is not the thing under test -- the
accounting around it is -- and constructing a real one calls
`HuggingFaceTokenizer.from_pretrained`, which reaches out to huggingface.co: a unit test that
either takes a network round trip or fails on whatever the hub does today. (An earlier version
of this docstring claimed that call "hangs with no timeout rather than failing". That is wrong
and was withdrawn: `huggingface_hub` sets `DEFAULT_ETAG_TIMEOUT = 10`, and with the hub
unreachable it raises `OSError` in single-digit seconds. What was actually observed was one
120-second probe that did not finish -- a slow or stalled proxy, over-read as an absent
timeout. Rule 13: resolve it, do not remember it.)

The stub keeps the real class's *calling convention* -- keyword-only `tokenizer` -- because
`HybridChunker` is a pydantic `BaseModel` and rejects positional arguments. A permissive stub
made `HybridChunker(tokenizer)` pass here while raising `TypeError` in production.
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
    RefItem,
    TableCell,
    TableData,
    TableItem,
    TextItem,
)
from docling_core.types.doc.labels import DocItemLabel

from app.ingestion import chunker as chunker_module
from app.ingestion.chunker import chunk_document
from app.ingestion.figure_extractor import ExtractedFigure

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path


def _table(page_no: int = 4, index: int = 0, caption: str = "") -> TableItem:
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
    captions = [RefItem(cref=f"#/texts/{index}")] if caption else []
    return TableItem(self_ref=f"#/tables/{index}", data=data, prov=[prov], captions=captions)


TENANT = "a" * 32
"""These tests do not care *which* tenant, only that one is named. `chunk_document` requires it
since the shared corpus was removed -- there is no longer a default tenant a chunk could
silently belong to."""


def _document(items: Sequence[NodeItem], captions: Sequence[str] = ()) -> DoclingDocument:
    """A document whose `iterate_items` yields exactly `items`.

    Subclassed rather than monkeypatched, for the same reason as `test_figure_ids.py`:
    `DoclingDocument` is a pydantic model, so assigning a method onto an instance raises
    "object has no field".

    `captions` populates `texts`, because `TableItem.caption_text(document)` resolves a
    `RefItem` -- `#/texts/N` -- against the document it is handed. A table built with a caption
    ref but dropped into a document with no `texts` silently reports no caption, which is how
    the caption branch of `chunk_document` stayed uncovered.
    """

    class _StubDocument(DoclingDocument):
        def iterate_items(self, *_args: object, **_kwargs: object) -> Iterator[tuple[NodeItem, int]]:
            return ((item, 0) for item in items)

    return _StubDocument(
        name="test",
        texts=[
            TextItem(self_ref=f"#/texts/{index}", label=DocItemLabel.CAPTION, text=text, orig=text)
            for index, text in enumerate(captions)
        ],
    )


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
        def __init__(self, *, tokenizer: object) -> None:
            # Keyword-only, matching the real `HybridChunker`: it is a pydantic `BaseModel`, so
            # `HybridChunker(tokenizer)` raises "takes 1 positional argument but 2 were given".
            # A stub accepting positional args left that mutation green here and broken in
            # production -- nothing else calls `chunk_document`, so nothing else caught it.
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

    chunks = chunk_document(tenant_id=TENANT, document=_document([]), doc_id="doc", figures=[])

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

    chunks = chunk_document(tenant_id=TENANT, document=_document([]), doc_id="doc", figures=[])

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

    chunks = chunk_document(tenant_id=TENANT, document=_document([]), doc_id="doc", figures=[])

    assert [chunk.chunk_type for chunk in chunks] == ["text"]


def test_headings_become_the_section_path() -> None:
    _chunks.append(_docling_chunk("body", headings=["Results", "Ablations"]))

    chunks = chunk_document(tenant_id=TENANT, document=_document([]), doc_id="doc", figures=[])

    assert chunks[0].section_path == "Results > Ablations"


def test_a_text_chunk_with_no_provenance_has_no_page() -> None:
    """`page_no=None` has to survive to the payload as *absent*, not as 0 -- page 0 does not
    exist, and a citation rendering "p. 0" is worse than one rendering no page at all.
    """
    _chunks.append(_docling_chunk("body"))

    chunks = chunk_document(tenant_id=TENANT, document=_document([]), doc_id="doc", figures=[])

    assert chunks[0].page_no is None


def test_tables_are_numbered_separately_from_text() -> None:
    """Two independent counters, so adding a paragraph cannot renumber a table."""
    _chunks.append(_docling_chunk("prose"))

    chunks = chunk_document(
        tenant_id=TENANT, document=_document([_table(index=0), _table(index=1)]), doc_id="doc", figures=[]
    )

    assert [chunk.chunk_id for chunk in chunks] == ["doc-text-0000", "doc-table-0000", "doc-table-0001"]


def test_a_table_carries_its_markdown_in_metadata_as_well_as_its_text() -> None:
    """The text is what gets embedded; the metadata copy is what a client can re-render. On an
    uncaptioned table they coincide, which is what this asserts; the next test covers the case
    where they must differ.
    """
    chunks = chunk_document(tenant_id=TENANT, document=_document([_table()]), doc_id="doc", figures=[])

    assert chunks[0].chunk_type == "table"
    assert chunks[0].page_no == 4
    assert chunks[0].metadata["markdown"].startswith("| a")
    assert chunks[0].text == chunks[0].metadata["markdown"], "this fixture has no caption, so they coincide"


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

    chunks = chunk_document(tenant_id=TENANT, document=_document([]), doc_id="doc", figures=[figure])

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
        document=_document([_table()]),
        doc_id="doc",
        figures=[figure],
        tenant_id="tenant-a",
        filename="report.pdf",
    )

    assert {chunk.chunk_type for chunk in chunks} == {"text", "table", "figure"}
    assert all(chunk.tenant_id == "tenant-a" for chunk in chunks)
    assert all(chunk.metadata["filename"] == "report.pdf" for chunk in chunks)


@pytest.mark.parametrize(
    "caption",
    [
        "Table 1: discharge capacity by cathode material.",
        # The three the first version of this fix got wrong, and this test could not see. The
        # serializer escapes `_` as `\\_` and HTML-escapes `&`, `<`, `>`, so a substring test
        # against the emitted markdown fails and the caption was prepended a second time.
        "Table 2: F_1 scores for multi_head attention.",
        "Table 3: capacity (mAh g-1) & efficiency (%).",
        "Table 4: the x < 0.5 regime.",
    ],
)
def test_a_captioned_table_embeds_its_caption_exactly_once(caption: str) -> None:
    """Writing this test is what found the duplication.

    The caption matters: "Table 3: capacity retention by cathode" is often the only wording a
    question will match, since the grid itself is numbers. But docling's markdown serializer
    already emits it above the table, and `chunk_document` prepended it as well -- so every
    captioned table was embedded with its caption twice, skewing the chunk toward the heading
    and away from the data. Nothing raised; the chunk simply read slightly wrong to the
    embedding model.
    """
    chunks = chunk_document(
        tenant_id=TENANT, document=_document([_table(caption=caption)], captions=[caption]), doc_id="doc", figures=[]
    )

    # Not `count(caption) == 1`, which was the first version and passes with the bug present: the
    # duplicate copy is *escaped*, so it does not match the raw caption and the count stays 1.
    # Count the lines before the grid instead -- one caption line, whatever escaping it carries.
    head, _, grid = chunks[0].text.partition("\n|")
    assert grid, "the markdown grid must survive"
    assert len([line for line in head.splitlines() if line.strip()]) == 1, f"caption doubled: {head!r}"
