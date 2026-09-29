"""The record/replay harness the CI eval gate stands on (`app/eval/replay.py`).

No live service and no network: the "network" is an `httpx.MockTransport`, which vcrpy patches
exactly as it patches the real transports, so a recording made against it goes through the same
matching, scrubbing and bookkeeping a recording of Anthropic, Voyage or Qdrant does. What this
cannot show is that the real clients are intercepted; that was checked once, by running
`anthropic`, `voyageai` (sync via requests, async via aiohttp) and `qdrant_client` against a local
server (`app/eval/replay.py`'s docstring has the result).

Needs the `eval` extra (vcrpy); the CI `test` job installs it, so these run rather than skip.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from langsmith.utils import tracing_is_enabled
from qdrant_client.qdrant_remote import QdrantRemote

from app.config import get_settings
from app.eval.replay import (
    STALE_AFTER,
    Harness,
    Mode,
    ReplayError,
    build_meta,
    current_models,
    current_pipeline,
    find_secrets,
    offline_environment,
    read_meta,
    require_judges_match,
    staleness_warnings,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

RECORDER_QDRANT = "http://recorder-host:6333"
PROVIDER_URL = "https://api.example.com/v1/rerank"
QDRANT_PATH = "/collections/portfolio_rag/points/query"

KEY = "sk-ant-api03-THISISNOTAREALKEYBUTLOOKSLIKEONE0123456789"


async def _call(url: str, body: dict, *, headers: dict | None = None) -> tuple[dict, int]:
    """One POST through a fake network. Returns the reply and how many times the network was hit."""
    hits = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal hits
        hits += 1
        return httpx.Response(
            200,
            json={"echo": json.loads(request.content)},
            headers={
                "set-cookie": "session=SECRETCOOKIE",
                "anthropic-organization-id": "org-1234",
                "x-request-id": "r1",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await client.post(url, json=body, headers=headers)
    return response.json(), hits


async def _record(
    directory: Path, fns: dict[str, Callable[[], Awaitable[Any]]], qdrant: str = RECORDER_QDRANT
) -> dict[str, Any]:
    results = {}
    with Harness(Mode.RECORD, qdrant_url=qdrant, directory=directory) as harness:
        harness.prepare_recording()
        for name, fn in fns.items():
            results[name] = await harness.run(name, fn)
    return results


async def _replay[T](directory: Path, name: str, fn: Callable[[], Awaitable[T]], qdrant: str = RECORDER_QDRANT) -> T:
    with Harness(Mode.REPLAY, qdrant_url=qdrant, directory=directory) as harness:
        return await harness.run(name, fn)


def _post(url: str, body: dict, headers: dict | None = None) -> Callable[[], Awaitable[tuple[dict, int]]]:
    async def call() -> tuple[dict, int]:
        return await _call(url, body, headers=headers)

    return call


# -------------------------------------------------------------------------------------------
# Replay is faithful, and loud about everything else
# -------------------------------------------------------------------------------------------


async def test_replay_serves_the_recording_and_never_reaches_the_network(tmp_path: Path) -> None:
    recorded = await _record(tmp_path, {"q001": _post(PROVIDER_URL, {"q": "a"})})
    assert recorded["q001"][1] == 1, "recording goes to the network"

    reply, hits = await _replay(tmp_path, "q001", _post(PROVIDER_URL, {"q": "a"}))

    assert reply == recorded["q001"][0]
    assert hits == 0, "replay must not reach the network"


async def test_a_request_the_recording_lacks_aborts_and_names_the_pair(tmp_path: Path) -> None:
    """The body is part of the match: a changed prompt or filter is a miss, not a reused answer."""
    await _record(tmp_path, {"q001": _post(PROVIDER_URL, {"q": "a"})})

    with pytest.raises(ReplayError, match=r"cassette miss in q001") as raised:
        await _replay(tmp_path, "q001", _post(PROVIDER_URL, {"q": "a different prompt"}))

    assert "api.example.com" in str(raised.value), "the message names the request that missed"


async def test_a_miss_that_the_app_swallows_still_aborts(tmp_path: Path) -> None:
    """`reranker.rerank` falls back to vector order when Voyage fails. Its miss must not become a
    quietly degraded, scored run.
    """
    await _record(tmp_path, {"q001": _post(PROVIDER_URL, {"q": "a"})})

    async def swallows_everything() -> str:
        try:
            await _call(PROVIDER_URL, {"q": "changed"})
        except Exception:  # noqa: BLE001 -- this is the behaviour under test
            return "fell back"
        return "answered"

    with pytest.raises(ReplayError, match="cassette miss in q001"):
        await _replay(tmp_path, "q001", swallows_everything)


async def test_a_recorded_request_that_is_never_made_aborts(tmp_path: Path) -> None:
    async def two_calls() -> None:
        await _call(PROVIDER_URL, {"q": "first"})
        await _call(PROVIDER_URL, {"q": "second"})

    await _record(tmp_path, {"q001": two_calls})

    async def only_the_first() -> None:
        await _call(PROVIDER_URL, {"q": "first"})

    with pytest.raises(ReplayError, match=r"1 recorded request\(s\) were never made") as raised:
        await _replay(tmp_path, "q001", only_the_first)

    assert "second" in str(raised.value), "the message shows which recorded request went unplayed"


async def test_an_identical_request_made_twice_is_recorded_and_replayed_twice(tmp_path: Path) -> None:
    """Replay plays each recorded response at most once, so an identical request made twice needs
    two recordings. Pins that recording keeps both rather than collapsing them.
    """

    async def twice() -> int:
        return (await _call(PROVIDER_URL, {"q": "same"}))[1] + (await _call(PROVIDER_URL, {"q": "same"}))[1]

    assert (await _record(tmp_path, {"q001": twice}))["q001"] == 2, "both reached the network"
    assert await _replay(tmp_path, "q001", twice) == 0


async def test_a_recording_that_captured_nothing_is_refused(tmp_path: Path) -> None:
    async def no_http() -> None:
        return None

    with pytest.raises(ReplayError, match="nothing was recorded for q001"):
        await _record(tmp_path, {"q001": no_http})


async def test_a_cassette_name_cannot_escape_the_directory(tmp_path: Path) -> None:
    with pytest.raises(ReplayError, match="unsafe cassette name"):
        await _record(tmp_path, {"../escape": _post(PROVIDER_URL, {})})


def test_replay_needs_a_cassette_for_every_pair_and_reports_strays(tmp_path: Path) -> None:
    for name in ("_setup", "q001", "q999"):
        (tmp_path / f"{name}.yaml").write_text("")
    harness = Harness(Mode.REPLAY, qdrant_url=RECORDER_QDRANT, directory=tmp_path)

    with pytest.raises(ReplayError, match="q002"):
        harness.check_replayable(["q001", "q002"])

    assert harness.check_replayable(["q001"]) == ["cassette q999.yaml matches no golden pair"]


def test_recording_starts_from_an_empty_directory(tmp_path: Path) -> None:
    (tmp_path / "q999.yaml").write_text("")
    (tmp_path / "meta.json").write_text("{}")

    Harness(Mode.RECORD, qdrant_url=RECORDER_QDRANT, directory=tmp_path).prepare_recording()

    assert list(tmp_path.iterdir()) == []


def test_replay_must_agree_with_the_recording_about_judges() -> None:
    require_judges_match({"judges": True}, judges=True)
    require_judges_match({"judges": False}, judges=False)
    with pytest.raises(ReplayError, match="without --judges"):
        require_judges_match({"judges": False}, judges=True)
    with pytest.raises(ReplayError, match="with --judges"):
        require_judges_match({"judges": True}, judges=False)


# -------------------------------------------------------------------------------------------
# Secrets
# -------------------------------------------------------------------------------------------


async def test_credentials_never_reach_the_cassette(tmp_path: Path) -> None:
    secrets = {
        "x-api-key": KEY,
        "authorization": "Bearer AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "api-key": "qdrant-key-value-123456",
        "x-goog-api-key": "google-key-value-123456",
        "x-some-token": "token-value-123456",
    }
    await _record(tmp_path, {"q001": _post(PROVIDER_URL, {"q": "a"}, headers=secrets)})

    text = (tmp_path / "q001.yaml").read_text().lower()

    for name, value in secrets.items():
        assert value.lower() not in text, f"{name}'s value was recorded"
        assert name not in text, f"the {name} header was recorded"
    for response_leak in ("secretcookie", "set-cookie", "org-1234", "anthropic-organization-id"):
        assert response_leak not in text, f"response header content {response_leak!r} was recorded"
    assert "content-type" in text, "the header replay actually needs must survive"
    assert find_secrets(tmp_path, [KEY]) == []


def test_the_secret_scan_finds_what_it_is_looking_for(tmp_path: Path) -> None:
    """A scan that finds nothing in a clean file only means something if it finds a dirty one."""
    (tmp_path / "header.yaml").write_text("interactions:\n- request:\n    headers:\n      x-api-key:\n      - abc\n")
    (tmp_path / "value.yaml").write_text(f"body: {{string: 'token {KEY}'}}\n")
    (tmp_path / "clean.yaml").write_text("body: {string: 'nothing to see'}\n")

    found = find_secrets(tmp_path, ["a-literal-key-value"])
    files = {line.split(":")[0] for line in found}

    assert files == {"header.yaml", "value.yaml"}
    (tmp_path / "literal.yaml").write_text("body: a-literal-key-value\n")
    assert any(line.startswith("literal.yaml") for line in find_secrets(tmp_path, ["a-literal-key-value"]))
    assert not any(line.startswith("literal.yaml") for line in find_secrets(tmp_path, ["short"])), (
        "short values are ignored"
    )


def test_a_cassette_holding_a_secret_is_deleted_and_the_recording_does_not_finish(tmp_path: Path) -> None:
    (tmp_path / "q001.yaml").write_text(f"body: {KEY}\n")
    harness = Harness(Mode.RECORD, qdrant_url=RECORDER_QDRANT, directory=tmp_path)

    with pytest.raises(ReplayError, match="all cassettes were deleted"):
        harness.finish_recording({"recorded_at": "x"}, secret_literals=[KEY])

    assert list(tmp_path.iterdir()) == [], "nothing is left for `git add` to find, and no meta.json vouches for it"


def test_a_clean_recording_finishes_by_writing_meta_last(tmp_path: Path) -> None:
    (tmp_path / "q001.yaml").write_text("body: clean\n")
    Harness(Mode.RECORD, qdrant_url=RECORDER_QDRANT, directory=tmp_path).finish_recording({"recorded_at": "x"}, [KEY])
    assert read_meta(tmp_path) == {"recorded_at": "x"}


# -------------------------------------------------------------------------------------------
# The Qdrant host is the recorder's business, not CI's
# -------------------------------------------------------------------------------------------


async def test_the_qdrant_host_is_normalised_so_replay_works_against_any_qdrant_url(tmp_path: Path) -> None:
    body = {"query": [0.1, 0.2], "limit": 20}
    recorded = await _record(tmp_path, {"q001": _post(f"{RECORDER_QDRANT}{QDRANT_PATH}", body)})
    text = (tmp_path / "q001.yaml").read_text()
    assert "recorder-host" not in text, "the recording machine's host must not be committed"

    # (configured QDRANT_URL, where the request actually goes). The last has no port configured
    # while the request carries one: QdrantClient fills in 6333, so only the hostname can be compared.
    cases = [
        ("http://ci-qdrant.invalid:1234", "http://ci-qdrant.invalid:1234"),
        ("https://ci-qdrant.invalid", "https://ci-qdrant.invalid"),
        ("http://ci-qdrant.invalid", "http://ci-qdrant.invalid:6333"),
    ]
    for configured, target in cases:
        reply, hits = await _replay(tmp_path, "q001", _post(f"{target}{QDRANT_PATH}", body), qdrant=configured)
        assert reply == recorded["q001"][0], configured
        assert hits == 0, configured


async def test_only_the_qdrant_host_is_normalised(tmp_path: Path) -> None:
    """A provider call to a different host is a different request, not a match."""
    await _record(tmp_path, {"q001": _post(PROVIDER_URL, {"q": "a"})})

    with pytest.raises(ReplayError, match="cassette miss"):
        await _replay(tmp_path, "q001", _post("https://api.elsewhere.example/v1/rerank", {"q": "a"}))


# -------------------------------------------------------------------------------------------
# Nothing live, nothing traced
# -------------------------------------------------------------------------------------------


def _swallowed_remote_connect(directory: Path) -> None:
    # Documentation address (RFC 5737): never routable, and the guard raises before any connect.
    with (
        Harness(Mode.REPLAY, qdrant_url=RECORDER_QDRANT, directory=directory),
        contextlib.suppress(ReplayError),
        socket.socket() as sock,
    ):
        sock.connect(("203.0.113.7", 80))


def test_a_remote_connect_is_refused_even_if_the_caller_swallows_the_error(tmp_path: Path) -> None:
    with pytest.raises(ReplayError, match="attempted during replay"):
        _swallowed_remote_connect(tmp_path)


def test_loopback_is_not_refused(tmp_path: Path) -> None:
    """Postgres runs on loopback in CI. A closed loopback port fails as an ordinary OSError."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with (
        Harness(Mode.REPLAY, qdrant_url=RECORDER_QDRANT, directory=tmp_path),
        socket.socket() as sock,
        pytest.raises(OSError, match=r"refused|Errno"),
    ):
        sock.connect(("127.0.0.1", port))


def test_the_qdrant_compatibility_thread_cannot_reach_out(tmp_path: Path) -> None:
    """`QdrantClient.__init__` starts a daemon thread that GETs `/`, at whatever moment it likes.
    Called directly here, so the outcome does not depend on timing: unpatched it would attempt a
    remote connect, which the guard records and `Harness.__exit__` turns into an error.
    """
    with Harness(Mode.REPLAY, qdrant_url=RECORDER_QDRANT, directory=tmp_path):
        QdrantRemote._check_compatibility("http://203.0.113.7:6333", {}, None, 1)


@pytest.mark.parametrize("mode", [Mode.RECORD, Mode.REPLAY])
def test_langsmith_tracing_is_forced_off_in_both_modes(mode: Mode, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-real-looking-key")

    with offline_environment(mode):
        assert tracing_is_enabled() is False
        assert get_settings().langsmith_tracing is False, "a .env with tracing on must not win"
        assert (os.environ["ANTHROPIC_API_KEY"] != "a-real-looking-key") is (mode is Mode.REPLAY)

    assert os.environ["LANGSMITH_TRACING"] == "true", "the environment is restored afterwards"


# -------------------------------------------------------------------------------------------
# meta.json and staleness
# -------------------------------------------------------------------------------------------

_NOW = datetime(2026, 9, 29, tzinfo=UTC)
_SETTINGS = SimpleNamespace(
    answer_model="answer-1",
    intent_router_model="router-1",
    eval_judge_model="judge-1",
    voyage_model="voyage-1",
    voyage_rerank_model="rerank-1",
    reranker_backend="voyage",
    retrieval_top_k=20,
    rerank_top_n=5,
    aggregate_answering=False,
    dynamic_prompt=False,
    query_expansion=False,
    query_decomposition=False,
    whole_document_scope=False,
)


def _meta(age: timedelta) -> dict:
    return build_meta(_SETTINGS, ["q001"], judges=True, git_sha="abc1234", now=_NOW - age)


def _warnings(meta: dict, **changes: object) -> list[str]:
    changed = SimpleNamespace(**{**vars(_SETTINGS), **changes})
    return staleness_warnings(meta, current_models(changed), current_pipeline(changed), now=_NOW)


def test_fresh_cassettes_recorded_with_the_current_models_do_not_warn() -> None:
    assert _warnings(_meta(timedelta(days=1))) == []


def test_the_gate_warns_past_the_staleness_threshold_and_not_at_it() -> None:
    assert _warnings(_meta(STALE_AFTER)) == [], "exactly at the threshold is still fresh"

    (warning,) = _warnings(_meta(STALE_AFTER + timedelta(days=1)))

    assert "91 days ago" in warning
    assert "re-record" in warning


def test_the_gate_warns_when_a_model_id_differs_from_the_recorded_one() -> None:
    (warning,) = _warnings(_meta(timedelta(days=1)), answer_model="answer-2")

    assert "answer_model" in warning
    assert "answer-1" in warning
    assert "answer-2" in warning


def test_the_gate_warns_when_a_pipeline_setting_differs() -> None:
    (warning,) = _warnings(_meta(timedelta(days=1)), aggregate_answering=True)

    assert "aggregate_answering" in warning


def test_a_meta_without_a_readable_date_is_an_error_not_a_pass() -> None:
    with pytest.raises(ReplayError, match="recorded_at"):
        staleness_warnings({"models": {}, "pipeline": {}}, {}, {}, now=_NOW)


def test_meta_records_what_a_replay_needs_to_judge_the_recording() -> None:
    meta = _meta(timedelta(0))

    assert meta["recorded_at"] == _NOW.isoformat(timespec="seconds")
    assert meta["git_sha"] == "abc1234"
    assert meta["models"] == {
        "answer_model": "answer-1",
        "intent_router_model": "router-1",
        "judge_model": "judge-1",
        "voyage_model": "voyage-1",
        "voyage_rerank_model": "rerank-1",
    }
    assert meta["judges"] is True
    assert meta["pair_ids"] == ["q001"]


def test_reading_meta_that_was_never_written_says_the_recording_is_incomplete(tmp_path: Path) -> None:
    with pytest.raises(ReplayError, match="never fully recorded"):
        read_meta(tmp_path)
