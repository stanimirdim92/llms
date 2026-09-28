"""Pinned Docling extension allowlist for document Q&A uploads.

Do not import Docling here: deriving the list at API startup added about 2s and 157MB per
process (8.74s/830MB vs 6.78s/673MB). The per-format drift test in
``tests/unit/test_upload_formats.py`` checks Docling's mapping in CI. Keep additions deliberate:
a dependency upgrade must not silently widen the public upload allowlist.
"""

# Docling 2.x extensions, grouped so the drift test identifies the changed format.
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
