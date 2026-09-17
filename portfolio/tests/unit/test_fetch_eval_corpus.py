"""`scripts/fetch_eval_corpus.py` -- the eval corpus download and its digest guard.

Adapted from the deleted `test_fetch_corpus.py` (removed with the shared corpus, 2026-08-03),
which is where the retry and per-paper-survival cases come from. The digest cases are new, and
they are the point of the script: the old one fetched an *unversioned* arXiv id and recorded no
hash, so a paper revised upstream would re-chunk and every golden chunk id pointing into it
would silently address a different passage.

No network. `httpx.Client` is replaced with a scripted stub, so every branch -- transient
failure, permanent failure, unusable URL, digest mismatch -- is reachable without arxiv.org.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Self

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType

_BODY = b"%PDF-1.4 body"
_BODY_SHA = hashlib.sha256(_BODY).hexdigest()
_PAPERS = ("1111v1", "2222v2", "3333v1")


def _load_cli() -> ModuleType:
    """`scripts/` is not a package, so load by path -- same as `test_create_tenant.py`."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "fetch_eval_corpus.py"
    spec = importlib.util.spec_from_file_location("fetch_eval_corpus_cli", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, content: bytes = _BODY, status: int = 200) -> None:
        self.content = content
        self._status = status

    def raise_for_status(self) -> None:
        if self._status >= 400:
            request = httpx.Request("GET", "https://arxiv.org/pdf/x")
            response = httpx.Response(self._status, request=request)
            raise httpx.HTTPStatusError(f"{self._status}", request=request, response=response)


class _ScriptedClient:
    """Returns, or raises, whatever `outcomes` says for each requested id.

    An outcome may be a list, in which case successive requests for that id consume it -- which
    is how the retry path is tested without waiting on real backoff.
    """

    requests: ClassVar[list[str]] = []
    outcomes: ClassVar[dict[str, object]] = {}

    def __init__(self, **_kwargs: object) -> None:
        pass

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def get(self, url: str) -> _Response:
        arxiv_id = url.rsplit("/", 1)[-1]
        type(self).requests.append(arxiv_id)
        outcome = type(self).outcomes.get(arxiv_id, _Response())
        if isinstance(outcome, list):
            outcome = outcome.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, _Response)
        return outcome


@pytest.fixture
def corpus(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[ModuleType]:
    """The script with a three-paper manifest, no network, and no sleeping."""
    cli = _load_cli()
    manifest = tmp_path / "corpus_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "seed_tenant_id": "0" * 32,
                "papers": [
                    {"arxiv_id": paper, "filename": f"{paper}.pdf", "sha256": None, "bytes": None} for paper in _PAPERS
                ],
            }
        )
    )
    monkeypatch.setattr(cli, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(cli, "CORPUS_DIR", tmp_path / "corpus")
    _ScriptedClient.requests = []
    _ScriptedClient.outcomes = {}
    monkeypatch.setattr(cli.httpx, "Client", _ScriptedClient)
    # Real spacing is 3s per paper and per retry; a test that honoured it would take 20 seconds
    # to assert nothing about timing.
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)
    yield cli
    _ScriptedClient.requests = []
    _ScriptedClient.outcomes = {}


def _pin(cli: ModuleType, **digests: str | None) -> None:
    """Rewrite the manifest's digests -- `None` leaves a paper unpinned."""
    manifest = json.loads(cli.MANIFEST_PATH.read_text())
    for paper in manifest["papers"]:
        if paper["arxiv_id"] in digests:
            paper["sha256"] = digests[paper["arxiv_id"]]
    cli.MANIFEST_PATH.write_text(json.dumps(manifest))


def _downloaded(cli: ModuleType) -> list[str]:
    return sorted(path.stem for path in cli.CORPUS_DIR.glob("*.pdf"))


def test_every_paper_is_downloaded_and_pinned_by_record(corpus: ModuleType) -> None:
    assert corpus.fetch(record=True) == 0

    assert _downloaded(corpus) == list(_PAPERS)
    manifest = json.loads(corpus.MANIFEST_PATH.read_text())
    assert [paper["sha256"] for paper in manifest["papers"]] == [_BODY_SHA] * 3
    assert [paper["bytes"] for paper in manifest["papers"]] == [len(_BODY)] * 3


def test_an_unpinned_paper_is_refused_without_record(corpus: ModuleType) -> None:
    """The guard that makes the digest mandatory rather than advisory.

    Without it the bootstrap flag is the only thing standing between a fixture corpus and an
    unpinned one, and an unpinned corpus produces chunk ids that *look* exactly as real as
    pinned ones -- there is no later point at which the difference becomes visible.
    """
    with pytest.raises(corpus.CorpusDigestError):
        corpus.fetch(record=False)

    assert _downloaded(corpus) == [], "a refused paper must not be left on disk"


def test_bytes_that_do_not_match_the_manifest_abort_the_run(corpus: ModuleType) -> None:
    """A versioned arXiv id is supposed to be immutable. If it is not, this is the only place
    that can notice -- downstream, a changed document just re-chunks, and every golden chunk id
    pointing into it addresses a different passage while still resolving.
    """
    _pin(corpus, **dict.fromkeys(_PAPERS, _BODY_SHA))
    _ScriptedClient.outcomes = {"2222v2": [_Response(b"%PDF-1.4 revised")]}

    with pytest.raises(corpus.CorpusDigestError) as excinfo:
        corpus.fetch(record=False)

    assert "2222v2" in str(excinfo.value)
    assert "2222v2" not in _downloaded(corpus), "the mismatched bytes must not reach disk"


def test_a_matching_paper_already_on_disk_is_not_refetched(corpus: ModuleType) -> None:
    """A rerun of a built corpus must not hit arXiv again -- the pacing above exists because
    this is a public academic host, and `build_eval_chunks.py` expects to be run repeatedly.
    """
    _pin(corpus, **dict.fromkeys(_PAPERS, _BODY_SHA))
    corpus.CORPUS_DIR.mkdir(parents=True)
    (corpus.CORPUS_DIR / "2222v2.pdf").write_bytes(_BODY)

    assert corpus.fetch(record=False) == 0

    assert "2222v2" not in _ScriptedClient.requests
    assert _downloaded(corpus) == list(_PAPERS)


def test_a_corrupted_local_copy_is_refetched(corpus: ModuleType) -> None:
    """The cache check is by digest, not by existence. A truncated download that survived a
    previous interrupted run would otherwise be chunked as if it were the whole paper.
    """
    _pin(corpus, **dict.fromkeys(_PAPERS, _BODY_SHA))
    corpus.CORPUS_DIR.mkdir(parents=True)
    (corpus.CORPUS_DIR / "2222v2.pdf").write_bytes(b"%PDF-1.4 trunc")

    assert corpus.fetch(record=False) == 0

    assert "2222v2" in _ScriptedClient.requests
    assert (corpus.CORPUS_DIR / "2222v2.pdf").read_bytes() == _BODY


def test_one_permanently_failing_paper_does_not_stop_the_others(corpus: ModuleType) -> None:
    """Every paper is attempted, and a run with any failure still exits non-zero so a
    half-built corpus cannot pass for a clean one.
    """
    _ScriptedClient.outcomes = {"2222v2": [httpx.ConnectError("no route")] * 3}

    assert corpus.fetch(record=True) == 1
    assert _downloaded(corpus) == ["1111v1", "3333v1"]


def test_a_transient_failure_is_retried_rather_than_abandoned(corpus: ModuleType) -> None:
    _ScriptedClient.outcomes = {"2222v2": [httpx.ConnectError("reset"), _Response()]}

    assert corpus.fetch(record=True) == 0
    assert _ScriptedClient.requests.count("2222v2") == 2


def test_a_paper_is_not_retried_forever(corpus: ModuleType) -> None:
    """Bounded at `_ATTEMPTS`. Unbounded retry against a withdrawn id is a hang, not a build."""
    _ScriptedClient.outcomes = {"2222v2": [httpx.ConnectError("no route")] * 10}

    assert corpus.fetch(record=True) == 1
    assert _ScriptedClient.requests.count("2222v2") == corpus._ATTEMPTS


def test_a_404_is_not_retried(corpus: ModuleType) -> None:
    """A withdrawn or mistyped id is what a 404 actually is, and it is permanent."""
    _ScriptedClient.outcomes = {"2222v2": [_Response(status=404)] * 3}

    assert corpus.fetch(record=True) == 1
    assert _ScriptedClient.requests.count("2222v2") == 1, "a 404 is permanent; do not retry it"
    assert _downloaded(corpus) == ["1111v1", "3333v1"]


def test_a_500_is_retried(corpus: ModuleType) -> None:
    _ScriptedClient.outcomes = {"2222v2": [_Response(status=503), _Response()]}

    assert corpus.fetch(record=True) == 0
    assert _ScriptedClient.requests.count("2222v2") == 2


def test_an_unusable_url_is_a_paper_failure_not_a_build_failure(corpus: ModuleType) -> None:
    """`httpx.InvalidURL` is **not** a subclass of `httpx.HTTPError` -- checked against httpx
    0.28.1 -- so it escapes the per-paper handler unless named there, and stops the build.
    Reachable from a non-printable character, i.e. a stray newline in the manifest.
    """
    _ScriptedClient.outcomes = {"2222v2": [httpx.InvalidURL("not a url")] * 3}

    assert corpus.fetch(record=True) == 1
    assert _downloaded(corpus) == ["1111v1", "3333v1"]
