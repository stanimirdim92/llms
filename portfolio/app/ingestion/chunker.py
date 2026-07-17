"""Structure-aware chunking: prose via Docling's HybridChunker, tables and figures as atomic chunks."""

from docling.chunking import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.types.doc.document import DoclingDocument, TableItem

from app.config import get_settings
from app.ingestion.figure_extractor import ExtractedFigure
from app.ingestion.models import Chunk

_EMBEDDING_TOKENIZER_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _table_to_markdown(table: TableItem, document: DoclingDocument) -> str:
    return table.export_to_markdown(document)


def chunk_document(document: DoclingDocument, doc_id: str, figures: list[ExtractedFigure]) -> list[Chunk]:
    """Produce text, table, and figure chunks for one parsed document.

    Tables are always kept as a single atomic chunk (never split mid-row) and figures
    are represented by their Claude-generated caption so they are retrievable by
    semantic search alongside prose, not just embedded as opaque images.
    """
    settings = get_settings()
    chunks: list[Chunk] = []

    tokenizer = HuggingFaceTokenizer.from_pretrained(model_name=_EMBEDDING_TOKENIZER_MODEL, max_tokens=settings.chunk_max_tokens)
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
            )
        )
        text_chunk_index += 1

    for table_index, (item, _level) in enumerate(
        (i, level) for i, level in document.iterate_items() if isinstance(i, TableItem)
    ):
        page_no = item.prov[0].page_no if item.prov else None
        markdown = _table_to_markdown(item, document)
        caption = item.caption_text(document)
        text = f"{caption}\n\n{markdown}".strip() if caption else markdown
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}-table-{table_index:04d}",
                doc_id=doc_id,
                chunk_type="table",
                text=text,
                page_no=page_no,
                metadata={"markdown": markdown},
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
                metadata={"image_path": str(figure.image_path)},
            )
        )

    return chunks
