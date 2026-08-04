"""Structure-aware chunking: prose via Docling's HybridChunker, tables and figures as atomic chunks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from docling.chunking import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.types.doc.document import DoclingDocument, TableItem

from app.config import get_settings
from app.ingestion.models import Chunk

if TYPE_CHECKING:
    from app.ingestion.figure_extractor import ExtractedFigure

_EMBEDDING_TOKENIZER_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _table_to_markdown(table: TableItem, document: DoclingDocument) -> str:
    return table.export_to_markdown(document)


def _base_metadata(filename: str) -> dict:
    """Metadata every chunk kind carries. Empty when no filename is known (the corpus
    script passes one; a caller that does not simply gets the old doc_id-only behaviour)
    rather than storing an empty string that would render as a blank title.
    """
    return {"filename": filename} if filename else {}


def chunk_document(
    document: DoclingDocument,
    doc_id: str,
    figures: list[ExtractedFigure],
    tenant_id: str,
    filename: str = "",
) -> list[Chunk]:
    """Produce text, table, and figure chunks for one parsed document.

    Tables are always kept as a single atomic chunk (never split mid-row) and figures
    are represented by their Claude-generated caption so they are retrievable by
    semantic search alongside prose, not just embedded as opaque images.

    `filename` is stamped onto every chunk's metadata, which is what carries it into the
    Qdrant payload and from there into the title of each document block the model sees.
    Without it the only label on a retrieved chunk is the 65-character `doc_id`, so a
    question naming a file ("tell me about 24383456-639402.pdf") cannot be answered even
    when the right chunk was retrieved -- the model correctly reports it has no document by
    that name while summarising that document's content. Observed in production.
    """
    settings = get_settings()
    chunks: list[Chunk] = []

    tokenizer = HuggingFaceTokenizer.from_pretrained(
        model_name=_EMBEDDING_TOKENIZER_MODEL, max_tokens=settings.chunk_max_tokens
    )
    chunker = HybridChunker(tokenizer=tokenizer)
    text_chunk_index = 0
    for docling_chunk in chunker.chunk(document):
        text = chunker.contextualize(chunk=docling_chunk)
        if not text.strip():
            continue
        doc_items = getattr(docling_chunk.meta, "doc_items", [])
        if any(isinstance(item, TableItem) for item in doc_items):
            # Tables are handled separately below so they stay atomic; skip here.
            continue
        page_no = doc_items[0].prov[0].page_no if doc_items and doc_items[0].prov else None
        headings = getattr(docling_chunk.meta, "headings", None) or []
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}-text-{text_chunk_index:04d}",
                doc_id=doc_id,
                chunk_type="text",
                text=text,
                page_no=page_no,
                section_path=" > ".join(headings),
                metadata=_base_metadata(filename),
                tenant_id=tenant_id,
            )
        )
        text_chunk_index += 1

    for table_index, (item, _level) in enumerate(
        (i, level) for i, level in document.iterate_items() if isinstance(i, TableItem)
    ):
        page_no = item.prov[0].page_no if item.prov else None
        markdown = _table_to_markdown(item, document)
        caption = item.caption_text(document)
        # Prepended only when the markdown does not already carry a caption. It usually does:
        # `TableItem.export_to_markdown(doc)` delegates to docling-core's `MarkdownDocSerializer`,
        # which emits the caption above the grid. Prepending unconditionally embedded every
        # captioned table's caption *twice* -- harmless-looking, but the caption is the wording a
        # question actually matches, so duplicating it skews the chunk's embedding toward the
        # heading and away from the data.
        #
        # The test is **structural**, not `caption in markdown`. That substring test was the first
        # attempt and it fails on any caption the serializer escapes -- measured against
        # docling-core: `F_1` is emitted as `F\_1`, and `&`/`<`/`>` are HTML-escaped, so
        # "Table 2: capacity (mAh g-1) & efficiency (%)" does not appear in its own markdown and
        # got prepended anyway. Three of six realistic scientific captions doubled that way, in two
        # differently-escaped copies. Anything before the first table row is a caption line,
        # whatever escaping it carries; an empty head means the serializer emitted none.
        head, _, _ = markdown.partition("\n|")
        text = markdown if not caption or head.strip() else f"{caption}\n\n{markdown}".strip()
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}-table-{table_index:04d}",
                doc_id=doc_id,
                chunk_type="table",
                text=text,
                page_no=page_no,
                metadata=_base_metadata(filename) | {"markdown": markdown},
                tenant_id=tenant_id,
            )
        )

    for figure in figures:
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}-{figure.figure_id}",
                doc_id=doc_id,
                chunk_type="figure",
                text=figure.caption,
                page_no=figure.page_no,
                metadata=_base_metadata(filename) | {"image_path": str(figure.image_path)},
                tenant_id=tenant_id,
            )
        )

    return chunks
