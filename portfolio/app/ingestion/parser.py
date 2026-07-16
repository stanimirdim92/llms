"""Parse a PDF into a structured Docling document, preserving tables and figure regions."""

from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling_core.types.doc.document import DoclingDocument

_PIPELINE_OPTIONS = PdfPipelineOptions(generate_picture_images=True, images_scale=2.0)

_converter = DocumentConverter(
    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=_PIPELINE_OPTIONS)}
)


def parse_pdf(pdf_path: Path) -> DoclingDocument:
    """Convert a PDF into a Docling document with layout-aware text, tables, and figure regions."""
    result = _converter.convert(str(pdf_path))
    return result.document


def save_parsed_document(document: DoclingDocument, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document.model_dump_json(indent=2), encoding="utf-8")


def load_parsed_document(input_path: Path) -> DoclingDocument:
    return DoclingDocument.model_validate_json(input_path.read_text(encoding="utf-8"))
