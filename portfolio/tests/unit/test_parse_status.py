"""`parse_document` must reject anything short of a full conversion.

`document_timeout` makes a partial parse a routine outcome, and Docling signals it by
returning (status = PARTIAL_SUCCESS) rather than raising. The caller persists whatever it
gets to `data/processed/<doc_id>.json` and every later ingest reads that cache, so
accepting a partial result makes the truncation permanent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from docling.datamodel.base_models import ConversionStatus
from docling_core.types.doc.document import DoclingDocument

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
