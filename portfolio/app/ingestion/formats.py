"""Curated subset of Docling's natively-supported input formats accepted for user uploads.

Docling supports many more formats than this (audio/video transcription, XML variants, EPUB,
email, ...) -- see `docling.datamodel.base_models.InputFormat` -- but this project only exposes
the formats a "document Q&A" upload feature is actually meant to cover.

**Deliberately imports nothing from Docling.** An earlier version derived this list at import
time from Docling's own `FormatToExtensions` mapping, which reads as the more rigorous choice
and quietly made the api process import the whole ingestion stack to validate a filename
extension -- defeating the point of moving ingestion to a worker at all.

Measured, `import app.api.main` with and without this import: **8.74s / 830MB -> 6.78s / 673MB**,
so ~2s of startup and ~157MB of RSS per api process. (The remainder is torch and transformers,
which arrive via `langchain_core.language_models.base` -- LangChain's own import, reached through
ChatAnthropic, which `/ask` genuinely needs. Not attributable to this and not fixable here.)

The list below is therefore pinned, and `tests/unit/test_upload_formats.py` compares it against
Docling's real mapping -- so drift is caught in CI (where importing Docling is free) rather than
either going unnoticed or being paid for on every api start.

Pinning is also the better posture for what this actually is: an upload allowlist. Deriving it
dynamically means a routine dependency bump can silently widen what the public endpoint accepts.
Widening it should be a deliberate edit.
"""

# Extension sets as of docling 2.x, one tuple per InputFormat we accept. Grouped by format
# rather than flattened so the test can compare them format-by-format and name which one drifted.
UPLOAD_EXTENSIONS_BY_FORMAT: dict[str, frozenset[str]] = {
    "PDF": frozenset({"pdf"}),
    "DOCX": frozenset({"docm", "docx", "dotm", "dotx"}),
    "PPTX": frozenset({"potm", "potx", "ppsm", "ppsx", "pptm", "pptx"}),
    "HTML": frozenset({"htm", "html", "xhtml"}),
    "MD": frozenset({"Rmd", "md", "qmd", "rmd", "text", "txt"}),
    "XLSX": frozenset({"xlsm", "xlsx"}),
    "CSV": frozenset({"csv"}),
    "IMAGE": frozenset({"bmp", "jpeg", "jpg", "png", "tif", "tiff", "webp"}),
}

SUPPORTED_UPLOAD_EXTENSIONS: frozenset[str] = frozenset(
    ext.lower() for extensions in UPLOAD_EXTENSIONS_BY_FORMAT.values() for ext in extensions
)


def is_supported_upload(filename: str) -> bool:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return suffix in SUPPORTED_UPLOAD_EXTENSIONS
