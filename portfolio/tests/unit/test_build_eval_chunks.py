"""`scripts/build_eval_chunks.py` -- the drift check that guards every golden chunk id.

The script's expensive half (Docling parse, chunking) is not exercised here; it needs the real
corpus and minutes of CPU per paper. What is exercised is the comparison, because that is the
part with a failure mode: a chunk id is `f"{doc_id}-text-{index:04d}"`, so a Docling or
tokenizer change that splits one paper differently **renumbers every later chunk in it**. The
golden pairs keep resolving -- to different passages -- and the only visible symptom is recall@k
dropping, which reads as a retrieval regression rather than a fixture that moved.

So the tests below are all one question: does a rebuild that differs get *reported*, and does an
identical rebuild stay quiet.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType


def _load_cli() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "build_eval_chunks.py"
    spec = importlib.util.spec_from_file_location("build_eval_chunks_cli", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CLI = _load_cli()


def _built(*, chunks: dict[str, str], doc_id: str = "tenant-abc") -> dict:
    return {
        "documents": [
            {
                "arxiv_id": "1111v1",
                "doc_id": doc_id,
                "chunks": [{"chunk_id": chunk_id, "text_sha256": digest} for chunk_id, digest in chunks.items()],
            }
        ]
    }


_BASE = _built(chunks={"tenant-abc-text-0000": "aaa", "tenant-abc-text-0001": "bbb"})


def test_an_identical_rebuild_reports_no_drift() -> None:
    assert _CLI._report_drift(_CLI._comparable(_BASE), _CLI._comparable(_BASE)) == 0


def test_a_chunk_whose_text_changed_under_the_same_id_is_drift() -> None:
    """The dangerous case, and the one a count of chunks would miss entirely: the corpus still
    produces two chunks with the same two ids, and `-text-0001` is now a different passage.
    """
    rebuilt = _built(chunks={"tenant-abc-text-0000": "aaa", "tenant-abc-text-0001": "CHANGED"})

    assert _CLI._report_drift(_CLI._comparable(_BASE), _CLI._comparable(rebuilt)) == 1


def test_an_extra_chunk_is_drift() -> None:
    rebuilt = _built(
        chunks={"tenant-abc-text-0000": "aaa", "tenant-abc-text-0001": "bbb", "tenant-abc-text-0002": "ccc"}
    )

    assert _CLI._report_drift(_CLI._comparable(_BASE), _CLI._comparable(rebuilt)) == 1


def test_a_changed_doc_id_is_drift() -> None:
    """`doc_id` is the tenant-salted digest of the file, so this fires when the PDF changed or
    when someone re-minted `seed_tenant_id` instead of keeping the pinned one.
    """
    rebuilt = _built(chunks={"tenant-xyz-text-0000": "aaa"}, doc_id="tenant-xyz")

    assert _CLI._report_drift(_CLI._comparable(_BASE), _CLI._comparable(rebuilt)) == 1


def test_a_document_that_stopped_parsing_is_drift_not_silence() -> None:
    """A paper that times out is `skipped` in the rebuild, which means its chunks simply are not
    there. Left unreported, the golden pairs referencing it would all score as retrieval misses.
    """
    assert _CLI._report_drift(_CLI._comparable(_BASE), _CLI._comparable({"documents": []})) == 1


def test_timings_and_tool_versions_are_not_compared() -> None:
    """`parse_seconds` moves with the hardware and a Docling bump that changes no chunk is not a
    regression -- comparing either would make the check cry wolf, and a check that cries wolf
    gets run with `|| true` within a month.
    """
    old = _built(chunks={"tenant-abc-text-0000": "aaa", "tenant-abc-text-0001": "bbb"})
    old["produced_by"] = {"docling": "1.0.0"}
    old["documents"][0]["parse_seconds"] = 12.0
    new = _built(chunks={"tenant-abc-text-0000": "aaa", "tenant-abc-text-0001": "bbb"})
    new["produced_by"] = {"docling": "2.0.0"}
    new["documents"][0]["parse_seconds"] = 300.0

    assert _CLI._report_drift(_CLI._comparable(old), _CLI._comparable(new)) == 0
