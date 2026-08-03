"""`scripts/fetch_corpus.py` -- the corpus download loop.

Its sibling `scripts/ingest.py` got tests for the identical per-item survival rule and this did
not, which is how the two holes below survived: `httpx.InvalidURL` is not an `httpx.HTTPError`,
and an `OSError` from the write was outside the guard entirely. Both meant "one bad id stops the
build", which is exactly what the code's own comment claimed to prevent.

No network. `httpx.Client` is replaced with a scripted stub, so every branch -- transient
failure, permanent failure, unusable URL, unwritable path -- is reachable without arxiv.org.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, ClassVar, Self

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType


def _load_cli() -> ModuleType:
    """`scripts/` is not a package, so load by path -- same as `test_create_tenant.py`."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "fetch_corpus.py"
    spec = importlib.util.spec_from_file_location("fetch_corpus_cli", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PAPERS = ("1111", "2222", "3333")


class _Response:
    """A response, successful unless given a `status`.

    A real `httpx.HTTPStatusError` needs a real Request and Response to attach, so the 4xx/5xx
    cases build one -- which matters, because `_download` now branches on
    `exc.response.is_client_error` and a hand-rolled stand-in would not have that attribute.
    """

    def __init__(self, content: bytes = b"", status: int = 200) -> None:
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
        outcome = type(self).outcomes.get(arxiv_id, _Response(b"%PDF-1.4 body"))
        if isinstance(outcome, list):
            outcome = outcome.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, _Response)
        return outcome


@pytest.fixture
def corpus(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[ModuleType]:
    """The script with a manifest of three papers, no network, and no sleeping."""
    cli = _load_cli()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"papers": [{"arxiv_id": paper} for paper in _PAPERS]}))

    monkeypatch.setattr(
        cli, "get_settings", lambda: SimpleNamespace(manifest_path=manifest, raw_pdf_dir=tmp_path / "raw")
    )
    _ScriptedClient.requests = []
    _ScriptedClient.outcomes = {}
    monkeypatch.setattr(cli.httpx, "Client", _ScriptedClient)
    # Real spacing is 3s per paper and per retry; a test that honoured it would take 20 seconds
    # to assert nothing about timing. `test_papers_are_spaced_apart` asserts the calls instead.
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)
    yield cli
    _ScriptedClient.requests = []
    _ScriptedClient.outcomes = {}


def _downloaded(cli: ModuleType) -> list[str]:
    return sorted(path.stem for path in cli.get_settings().raw_pdf_dir.glob("*.pdf"))


def test_every_paper_is_downloaded(corpus: ModuleType) -> None:
    corpus.main()

    assert _downloaded(corpus) == list(_PAPERS)


def test_one_permanently_failing_paper_does_not_stop_the_others(corpus: ModuleType) -> None:
    """The rule this script shares with `scripts/ingest.py`: every item is attempted, and a run
    with any failure still exits non-zero so a half-built corpus cannot pass for a clean one.
    """
    _ScriptedClient.outcomes = {"2222": [httpx.ConnectError("no route")] * 3}

    with pytest.raises(SystemExit) as excinfo:
        corpus.main()

    assert excinfo.value.code == 1
    assert _downloaded(corpus) == ["1111", "3333"]


def test_a_transient_failure_is_retried_rather_than_abandoned(corpus: ModuleType) -> None:
    """Restores what dropping the `arxiv` client removed: it defaulted to `num_retries=3`, and
    the bare `client.get` loop that replaced it gave up on the first 5xx. On a 45-paper corpus
    build against a public host, one transient error should not cost the whole run.
    """
    _ScriptedClient.outcomes = {"2222": [httpx.ConnectError("reset"), _Response(b"%PDF-1.4 second try")]}

    corpus.main()  # must not raise SystemExit

    assert _downloaded(corpus) == list(_PAPERS)
    assert _ScriptedClient.requests.count("2222") == 2


def test_a_paper_is_not_retried_forever(corpus: ModuleType) -> None:
    """Bounded at `_ATTEMPTS`. Unbounded retry against a withdrawn id is a hang, not a build."""
    _ScriptedClient.outcomes = {"2222": [httpx.ConnectError("no route")] * 10}

    with pytest.raises(SystemExit):
        corpus.main()

    assert _ScriptedClient.requests.count("2222") == corpus._ATTEMPTS


def test_a_404_is_not_retried(corpus: ModuleType) -> None:
    """A withdrawn or mistyped id is what a 404 actually is, and it is permanent -- so the first
    version's three attempts with two 3-second sleeps burned six seconds per bad id to reach the
    same answer, against this function's own stated rationale. It must still be a *paper* failure
    rather than a build failure.
    """
    _ScriptedClient.outcomes = {"2222": [_Response(status=404)] * 3}

    with pytest.raises(SystemExit):
        corpus.main()

    assert _ScriptedClient.requests.count("2222") == 1, "a 404 is permanent; do not retry it"
    assert _downloaded(corpus) == ["1111", "3333"]


def test_a_500_is_retried(corpus: ModuleType) -> None:
    """The other side of the 4xx/5xx split: a server error is exactly the transient case retries
    exist for, and a 45-paper corpus build against a public host will meet them.
    """
    _ScriptedClient.outcomes = {"2222": [_Response(status=503), _Response(b"%PDF-1.4 second try")]}

    corpus.main()

    assert _ScriptedClient.requests.count("2222") == 2
    assert _downloaded(corpus) == list(_PAPERS)


def test_an_unusable_url_is_a_paper_failure_not_a_build_failure(corpus: ModuleType) -> None:
    """`httpx.InvalidURL` is **not** a subclass of `httpx.HTTPError` -- checked against httpx
    0.28.1 -- so it escapes the per-paper handler unless named there, and stops the build.

    Reachable from a *non-printable* character, i.e. a stray newline in `manifest.json`.
    Deliberately not described as "a mistyped id" any more: `httpx.URL` accepts `abc`,
    `2008 10896` and `../../etc/passwd` without complaint, so an ordinary typo is a valid URL and
    a 404 -- covered by `test_a_404_is_not_retried` instead.
    """
    _ScriptedClient.outcomes = {"2222": [httpx.InvalidURL("not a url")] * 3}

    with pytest.raises(SystemExit):
        corpus.main()

    assert _downloaded(corpus) == ["1111", "3333"]
    assert _ScriptedClient.requests.count("2222") == 1, "an unusable URL is permanent -- do not retry it"


def test_an_unwritable_path_is_a_paper_failure_too(corpus: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """The write was outside the guard. A full disk, a read-only mount, or an old-style arXiv id
    (`cond-mat/0009063`, whose slash makes the output path a missing directory) therefore stopped
    the build partway through -- after some papers had downloaded, which is the worst place.
    """
    real_write = corpus.Path.write_bytes

    def _fail_for_one(self: Path, data: bytes) -> int:
        if self.stem == "2222":
            raise OSError("no space left on device")
        return real_write(self, data)

    monkeypatch.setattr(corpus.Path, "write_bytes", _fail_for_one)

    with pytest.raises(SystemExit):
        corpus.main()

    assert _downloaded(corpus) == ["1111", "3333"]


def test_an_already_downloaded_paper_is_never_requested(corpus: ModuleType) -> None:
    """The cache check, which is what makes a re-run cheap. It must skip the *request*, not just
    the write -- these are multi-MB files from a public academic host.
    """
    raw = corpus.get_settings().raw_pdf_dir
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "2222.pdf").write_bytes(b"%PDF-1.4 already here")

    corpus.main()

    assert "2222" not in _ScriptedClient.requests


def test_papers_are_spaced_apart(corpus: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """The `arxiv` client defaulted to `delay_seconds=3.0` and its docstring tied that to arXiv's
    Terms of Use. Removing the dependency removed the pacing with it, silently: back-to-back
    multi-MB requests to a public host, whose consequence is a block rather than an exception.
    """
    slept: list[float] = []

    def _record(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(corpus.time, "sleep", _record)

    corpus.main()

    assert slept == [corpus._REQUEST_SPACING_SECONDS] * (len(_PAPERS) - 1), "one gap between each pair"


def test_a_fully_cached_corpus_sleeps_not_at_all(corpus: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-running the script on a complete corpus is the common case -- it is how `ingest.py` is
    re-run -- and it should cost nothing.
    """
    raw = corpus.get_settings().raw_pdf_dir
    raw.mkdir(parents=True, exist_ok=True)
    for paper in _PAPERS:
        (raw / f"{paper}.pdf").write_bytes(b"%PDF-1.4")
    slept: list[float] = []

    def _record(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(corpus.time, "sleep", _record)

    corpus.main()

    assert slept == []
    assert _ScriptedClient.requests == []
