"""`parse_document` must reject anything short of a full conversion.

`document_timeout` makes a partial parse a routine outcome, and Docling signals it by
returning (status = PARTIAL_SUCCESS) rather than raising. The caller persists whatever it
gets to `data/processed/<doc_id>.json` and every later ingest reads that cache, so
accepting a partial result makes the truncation permanent.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

import pytest
from docling.datamodel.base_models import ConversionStatus
from docling_core.types.doc.document import DoclingDocument

from app.config import get_settings
from app.ingestion import parser

if TYPE_CHECKING:
    from pathlib import Path


class _FakeError:
    def __init__(self, message: str) -> None:
        self.error_message = message


class _FakeResult:
    def __init__(self, status: ConversionStatus, errors: list[_FakeError] | None = None) -> None:
        self.status = status
        self.errors = errors or []
        self.document = DoclingDocument(name="fake")


def _converter_returning(result: _FakeResult, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parser._converter, "convert", lambda *_a, **_k: result)


def test_success_is_returned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _converter_returning(_FakeResult(ConversionStatus.SUCCESS), monkeypatch)

    assert parser.parse_document(tmp_path / "paper.pdf").name == "fake"


@pytest.mark.parametrize(
    "status",
    [ConversionStatus.PARTIAL_SUCCESS, ConversionStatus.FAILURE, ConversionStatus.SKIPPED],
)
def test_incomplete_conversion_raises(
    status: ConversionStatus, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _converter_returning(_FakeResult(status), monkeypatch)

    with pytest.raises(parser.DocumentParseError, match=status.value):
        parser.parse_document(tmp_path / "paper.pdf")


def test_timeout_detail_reaches_the_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The reason has to survive into the exception, or a timeout is indistinguishable
    from a corrupt file when someone reads the logs.
    """
    errors = [_FakeError("Document processing timeout: exceeded 90.000s limit")]
    _converter_returning(_FakeResult(ConversionStatus.PARTIAL_SUCCESS, errors), monkeypatch)

    with pytest.raises(parser.DocumentParseError, match="timeout"):
        parser.parse_document(tmp_path / "paper.pdf")


def test_the_parse_ceiling_is_configurable_not_a_literal(monkeypatch: pytest.MonkeyPatch) -> None:
    """`document_timeout` was `90` written into `parser.py`, which is Docling's own generic
    recommendation and is roughly seven pages on a four-core box -- it rejected every paper in
    `data/eval/corpus_manifest.json`. The value belongs to the deployment, not to this module,
    and the failure this pins is someone inlining a literal back.

    Reloading is the only honest check: `_PDF_PIPELINE_OPTIONS` is built once at import, so a
    test that read `get_settings()` directly would pass with the literal still in place.
    """
    monkeypatch.setenv("DOCLING_DOCUMENT_TIMEOUT", "123")
    get_settings.cache_clear()
    try:
        assert importlib.reload(parser)._PDF_PIPELINE_OPTIONS.document_timeout == 123
    finally:
        monkeypatch.delenv("DOCLING_DOCUMENT_TIMEOUT")
        get_settings.cache_clear()
        importlib.reload(parser)


def test_there_is_always_a_ceiling() -> None:
    """Docling reads `None` as "no timeout", and an unbounded parse holds one of the worker's
    concurrency slots until the process is killed -- with no error, because nothing failed.
    """
    assert parser._PDF_PIPELINE_OPTIONS.document_timeout, "a missing ceiling is an unbounded parse"
