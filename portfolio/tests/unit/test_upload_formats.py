"""The upload allowlist, and the two properties that keep it honest.

`app/ingestion/formats.py` pins its extension list rather than deriving it from Docling at
import time, because that import cost the api process ~2s of startup and ~157MB of RSS for a
filename check (see that module's docstring for the measurement). Pinning trades a live source of
truth for a stale one, so the drift check moves here -- importing Docling in a test is free.

Also pins that the api's import graph stays free of the ingestion stack, which is the property
the pinning exists to protect and which any future stray import would silently undo.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from app.ingestion.formats import (
    SUPPORTED_UPLOAD_EXTENSIONS,
    UPLOAD_EXTENSIONS_BY_FORMAT,
    is_supported_upload,
)

# The ingestion stack, and only that. Deliberately does NOT include torch/transformers: those
# still land in the api process, but `langchain_core.language_models.base` imports transformers
# itself (which pulls torch), so they arrive via ChatAnthropic -- which /ask genuinely needs --
# and not through anything this project chooses. Asserting on them would be asserting on
# LangChain's internals and would fail for a reason nobody here can fix. Traced, not assumed.
INGESTION_MODULES = ("docling", "docling_core")


@pytest.mark.parametrize("format_name", sorted(UPLOAD_EXTENSIONS_BY_FORMAT))
def test_pinned_extensions_still_match_docling(format_name: str) -> None:
    """Fails if Docling adds, removes, or renames an extension for a format we accept.

    A failure here is not automatically a bug -- it's a decision. Docling widening a format's
    extensions does not mean this public upload endpoint should accept more; copy the new value
    across only if the wider set is actually wanted.

    Parametrized per format so the failure names which one drifted rather than diffing one
    large flattened set.
    """
    from docling.datamodel.base_models import FormatToExtensions, InputFormat  # noqa: PLC0415

    docling_extensions = frozenset(FormatToExtensions[getattr(InputFormat, format_name)])

    assert UPLOAD_EXTENSIONS_BY_FORMAT[format_name] == docling_extensions, (
        f"docling's extensions for {format_name} changed -- decide whether to widen the "
        f"allowlist, then update UPLOAD_EXTENSIONS_BY_FORMAT"
    )


def test_the_api_import_graph_does_not_pull_in_the_ingestion_stack() -> None:
    """The api enqueues uploads; the worker parses them. Importing Docling in the api costs
    ~4.5s of startup for nothing.

    Run in a subprocess because this test session has already imported Docling (the drift check
    above does), so an in-process `sys.modules` check would always fail.

    Most likely way this regresses: someone adds a convenience import to a router, to
    `app/ingestion/uploads.py`, or back into `formats.py`. Nothing would visibly break -- the
    api would just get slower on every start, which is how it got that way the first time.
    """
    code = (
        "import sys, app.api.main; "
        f"leaked = sorted(m for m in {INGESTION_MODULES!r} if m in sys.modules); "
        "print(','.join(leaked))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "", f"app.api.main now imports the ingestion stack: {result.stdout.strip()}"


def test_supported_and_unsupported_extensions() -> None:
    assert is_supported_upload("paper.pdf")
    assert is_supported_upload("REPORT.DOCX")  # case-insensitive
    assert is_supported_upload("scan.tiff")
    assert not is_supported_upload("archive.zip")
    assert not is_supported_upload("noextension")
    assert not is_supported_upload("")


def test_extension_set_is_lowercased_for_matching() -> None:
    """Docling lists `Rmd` with a capital R, so the flattened set must be lowercased or an
    uploaded `notes.rmd` would be rejected while `notes.Rmd` was accepted.
    """
    assert "rmd" in SUPPORTED_UPLOAD_EXTENSIONS
    assert is_supported_upload("notes.Rmd")
    assert is_supported_upload("notes.rmd")
