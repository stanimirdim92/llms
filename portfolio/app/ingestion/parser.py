"""Parse a document into a structured Docling representation, preserving tables and
figure regions. Not PDF-only: Docling natively backs several formats (see
`app.ingestion.formats.SUPPORTED_UPLOAD_EXTENSIONS`), and `TableItem`/`PictureItem`/
`HybridChunker` downstream are format-agnostic over the resulting `DoclingDocument`.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.pipeline_options import AcceleratorOptions, PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc.document import DoclingDocument

from app.config import get_settings

if TYPE_CHECKING:
    from pathlib import Path

# Docling's default is num_threads=4 regardless of how many cores the host has, which
# leaves most of an 8+ core box idle during the layout and table-structure passes -- the
# CPU-bound bulk of ingestion. `device` is left at its "auto" default: Docling already
# probes for cuda/mps/xpu and falls back to cpu, so hardcoding a device here would only
# ever downgrade that. os.cpu_count() reports the *host's* cores, not a cgroup CPU limit,
# so if a CPU limit is ever added to docker-compose.yml, set DOCLING_NUM_THREADS
# explicitly rather than relying on this default.
_ACCELERATOR_OPTIONS = AcceleratorOptions(num_threads=get_settings().docling_num_threads or os.cpu_count() or 4)

# Only PDF needs an explicit pipeline-options override: it's rendered from page rasters, so
# figures must be explicitly requested (generate_picture_images=True). Other formats (DOCX,
# PPTX, HTML, images, ...) carry their figures as embedded assets already and use Docling's
# defaults, so they don't need (or support) this option the same way.
_PDF_PIPELINE_OPTIONS = PdfPipelineOptions(
    generate_picture_images=True, images_scale=1.5, accelerator_options=_ACCELERATOR_OPTIONS, document_timeout=90
)

_converter = DocumentConverter(
    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=_PDF_PIPELINE_OPTIONS)}
)


class DocumentParseError(RuntimeError):
    """Docling did not fully convert the document, so its output must not be used."""


def parse_document(file_path: Path) -> DoclingDocument:
    """Convert a document into a Docling document with layout-aware text, tables, and figures.

    Raises `DocumentParseError` unless the conversion fully succeeded. This check is not
    defensive padding -- `document_timeout` above makes a partial result a routine
    outcome, and Docling reports it by *returning* rather than raising: it logs a warning,
    appends a TIMEOUT `ErrorItem`, sets `status = PARTIAL_SUCCESS`, and stops processing
    the remaining pages (see `docling/pipeline/base_pipeline.py`). A truncated
    `DoclingDocument` is indistinguishable from a complete one at this boundary, and the
    caller's next step is to persist it to `data/processed/<doc_id>.json` -- which every
    later ingest then loads from cache. So silently accepting a partial parse doesn't just
    lose half a document once, it makes the truncation permanent and invisible.
    """
    result = _converter.convert(str(file_path))
    if result.status != ConversionStatus.SUCCESS:
        detail = "; ".join(error.error_message for error in result.errors) or "no error detail reported"
        msg = f"Docling returned status '{result.status.value}' for {file_path.name}: {detail}"
        raise DocumentParseError(msg)
    return result.document


def save_parsed_document(document: DoclingDocument, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document.model_dump_json(indent=2), encoding="utf-8")


def load_parsed_document(input_path: Path) -> DoclingDocument:
    return DoclingDocument.model_validate_json(input_path.read_text(encoding="utf-8"))
