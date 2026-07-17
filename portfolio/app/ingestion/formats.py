"""Curated subset of Docling's natively-supported input formats accepted for user uploads.

Docling supports many more formats than this (audio/video transcription, XML variants,
EPUB, email, ...) -- see `docling.datamodel.base_models.InputFormat` -- but this project
only exposes the formats a "document Q&A" upload feature is actually meant to cover.
Extensions are pulled from Docling's own `FormatToExtensions` mapping rather than
hand-guessed, so this stays correct if Docling adds/renames extensions for a format.
"""

from docling.datamodel.base_models import FormatToExtensions, InputFormat

_UPLOAD_FORMATS = (
    InputFormat.PDF,
    InputFormat.DOCX,
    InputFormat.PPTX,
    InputFormat.HTML,
    InputFormat.MD,
    InputFormat.XLSX,
    InputFormat.CSV,
    InputFormat.IMAGE,
)

SUPPORTED_UPLOAD_EXTENSIONS: frozenset[str] = frozenset(
    ext.lower() for fmt in _UPLOAD_FORMATS for ext in FormatToExtensions[fmt]
)


def is_supported_upload(filename: str) -> bool:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return suffix in SUPPORTED_UPLOAD_EXTENSIONS
