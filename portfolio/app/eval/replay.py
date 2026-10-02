"""Record every provider call an eval run makes, and replay them with no network and no keys.

Why: the CI gate must not depend on provider uptime, cost money per pull request, or hold
secrets. So a human records once (real keys, seeded stack) and CI replays. The cassettes are
committed, which shapes everything below: they are read by strangers, so nothing sensitive may
reach them, and a stale or partial set has to fail loudly rather than pass on whatever matched.

One cassette per golden pair id, plus `_setup.yaml` for the lazily-built services. Both modes run
**strictly sequentially**: vcrpy patches the HTTP classes process-wide, so two questions in
flight would play each other's cassettes.

What this module deliberately refuses to do quietly (each one a way to score a wrong answer that
looks like a right one):

- **A cassette miss is never a scored miss.** `run_question` keeps errors as data, and the app
  swallows some of them (`reranker.rerank` falls back to vector order when Voyage fails), so a
  missed rerank call would degrade the run and pass. Misses are counted at the moment vcr raises,
  not inferred from what the app did next, and an unplayed recorded interaction also aborts.
- **Replay never reaches a real host.** Keys are replaced with dummies, tracing is forced off,
  and a socket-level guard turns any non-loopback connect into a hard error.
- **Secrets never reach a cassette.** Request and response headers are allow-listed rather than
  filtered, and every cassette is scanned afterwards.

HTTP libraries, read from the installed packages rather than assumed (voyageai 0.5.0,
anthropic 0.120.2, qdrant-client 1.18.0, vcrpy 8.3.0): anthropic and qdrant_client REST use
httpx; voyageai's *async* rerank uses aiohttp, and its *sync* embed -- which is what
`QdrantVectorStore.asimilarity_search` calls, in a worker thread, for the query vector -- uses
requests. vcrpy patches all three.
"""

from __future__ import annotations

import contextlib
import functools
import ipaddress
import json
import os
import re
import socket
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Self, cast
from unittest import mock
from urllib.parse import urlparse, urlunparse

import structlog

from app.eval.golden import EVAL_DIR

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Iterator
    from pathlib import Path
    from types import TracebackType

log = structlog.get_logger(__name__)

CASSETTE_DIR = EVAL_DIR / "cassettes"
META_NAME = "meta.json"
SETUP_NAME = "_setup"

STALE_AFTER = timedelta(days=90)
"""Age past which the gate warns that the cassettes may vouch for a model that has since changed.
A quarter, chosen rather than derived: too short and the warning becomes noise nobody reads, too
long and a replay keeps certifying behaviour the provider may no longer serve. It only warns --
failing would turn the calendar into a broken build. Revisit with a measured re-record cost."""

_META_SCHEMA = 1
_QDRANT_PLACEHOLDER_HOST = "qdrant.recorded.invalid"
_REPLAY_KEY = "replay-not-a-real-key"

_MATCH_ON = ("method", "scheme", "host", "port", "path", "query", "body")
"""vcrpy's defaults plus the body. Host stays in for the providers; only Qdrant's is normalised
(`_scrub_request`). Body matching is safe because every request is deterministic given the
recorded responses before it: the Voyage rerank and Anthropic bodies carry chunks in the order the
replayed Qdrant response gave, and the Qdrant query body carries the replayed embedding, which
round-trips through JSON floats exactly. Body matching is also the point -- it is what makes a
changed prompt or filter a miss instead of a silent reuse of a stale answer."""

_KEEP_REQUEST_HEADERS = frozenset({"content-type", "transfer-encoding"})
_KEEP_RESPONSE_HEADERS = frozenset({"content-type"})
"""Allow-lists, not deny-lists. A deny-list of `x-api-key`, `authorization`, `api-key` fails open
for whichever credential header nobody thought of, in a file that gets committed to a public repo.
These two are also the only headers replay needs: content-type selects vcrpy's JSON body matcher
and the SDKs' response parsing. Everything else (user-agent with the recording machine's OS,
request ids, organisation ids, rate-limit counters) is noise or identity."""

_SECRET_HEADER = re.compile(
    r"^\s*(?:-\s*)?['\"]?(?:authorization|proxy-authorization|x-api-key|api-key|apikey|x-auth-token|cookie|set-cookie)"
    r"['\"]?\s*:",
    re.IGNORECASE | re.MULTILINE,
)
_SECRET_VALUE = re.compile(r"\b(?:sk-ant-[\w-]{10,}|pa-[\w-]{30,}|lsv2_[\w]{10,}|Bearer\s+[\w.~+/=-]{16,})")


class ReplayError(RuntimeError):
    """A record/replay invariant broke. Always fatal: continuing would score the wrong material."""


class Mode(StrEnum):
    RECORD = "record"
    REPLAY = "replay"


# -------------------------------------------------------------------------------------------
# What reaches a cassette
# -------------------------------------------------------------------------------------------


def _scrub_request(request: Any, *, qdrant_host: str | None) -> Any:  # noqa: ANN401 -- vcr.request.Request, untyped
    """Applied when recording *and* when matching, so both sides compare the same thing.

    The Qdrant host is rewritten to a fixed placeholder because the recording machine's
    `QDRANT_URL` is not CI's. Left in, replay would miss every Qdrant call the moment the two
    differ -- and the recorder's hostname would be committed. Only the hostname is compared, not
    the port: `QdrantClient` fills in 6333 when the URL names none.
    """
    request.headers = {k: v for k, v in request.headers.items() if k.lower() in _KEEP_REQUEST_HEADERS}
    parsed = urlparse(request.uri)
    if qdrant_host and parsed.hostname == qdrant_host:
        request.uri = urlunparse(("http", _QDRANT_PLACEHOLDER_HOST, parsed.path, parsed.params, parsed.query, ""))
    return request


def _decode_zstd(response: dict) -> dict:
    """Decompress a zstd body, which vcrpy's `decode_compressed_response` leaves alone (it knows
    gzip, deflate and br). Qdrant answers httpx's `Accept-Encoding: zstd` with zstd once
    `zstandard` is installed, and the allow-list below then drops `content-encoding`, so the first
    real recording stored compressed bytes labelled as plain JSON: every replay died in
    `response.json()` with `UnicodeDecodeError ... byte 0xb5` (zstd's magic is `28 b5 2f fd`).
    """
    headers = response.get("headers") or {}
    encoding = next((v for k, v in headers.items() if k.lower() == "content-encoding"), None)
    codecs = [c.strip().lower() for value in (encoding or []) for c in str(value).split(",") if c.strip()]
    if not codecs:
        return response
    if codecs != ["zstd"]:
        # Anything vcrpy didn't decode and we don't either would be stored compressed under a
        # header the allow-list is about to drop -- the failure above, for a different codec.
        msg = f"response body is still {'+'.join(codecs)}-encoded; add a decoder in replay._decode_zstd"
        raise ReplayError(msg)
    import zstandard  # noqa: PLC0415 -- present whenever httpx advertised zstd, which is the only way to get here

    response["body"]["string"] = zstandard.ZstdDecompressor().decompressobj().decompress(response["body"]["string"])
    response["headers"] = {k: v for k, v in headers.items() if k.lower() != "content-encoding"}
    return response


def _scrub_response(response: dict) -> dict:
    response = _decode_zstd(response)
    response["headers"] = {
        k: v for k, v in (response.get("headers") or {}).items() if k.lower() in _KEEP_RESPONSE_HEADERS
    }
    return response


def find_secrets(directory: Path, literals: Iterable[str] = ()) -> list[str]:
    """Where a credential appears in any cassette under `directory`: file and what matched.

    Structural patterns catch a header that slipped past the allow-list; `literals` (the real key
    values, at record time) catch a key that was echoed into a body. Values shorter than eight
    characters are ignored, since a blank or placeholder key would match everything.
    """
    needles = [value for value in literals if len(value) >= 8]  # noqa: PLR2004 -- see docstring
    found = []
    for path in sorted(directory.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        if match := _SECRET_HEADER.search(text):
            found.append(f"{path.name}: credential header {match.group().strip()!r}")
        if match := _SECRET_VALUE.search(text):
            found.append(f"{path.name}: key-shaped value {match.group()[:12]!r}...")
        found.extend(f"{path.name}: the literal value of a configured key" for needle in needles if needle in text)
    return found


# -------------------------------------------------------------------------------------------
# Meta and staleness
# -------------------------------------------------------------------------------------------

_PIPELINE_SETTINGS = (
    "reranker_backend",
    "retrieval_top_k",
    "rerank_top_n",
    "aggregate_answering",
    "dynamic_prompt",
    "query_expansion",
    "query_decomposition",
    "whole_document_scope",
)
"""Settings that change which requests the pipeline makes. Recorded so a replay under different
ones can say *why* it is about to miss, instead of only that it did."""


def current_models(settings: Any) -> dict[str, str]:  # noqa: ANN401 -- app.config.Settings, kept loose so tests need no Settings
    return {
        "answer_model": settings.answer_model,
        "intent_router_model": settings.intent_router_model,
        "judge_model": settings.eval_judge_model,
        "voyage_model": settings.voyage_model,
        "voyage_rerank_model": settings.voyage_rerank_model,
    }


def current_pipeline(settings: Any) -> dict:  # noqa: ANN401 -- see current_models
    return {name: getattr(settings, name) for name in _PIPELINE_SETTINGS}


def build_meta(
    settings: Any,  # noqa: ANN401 -- see current_models
    pair_ids: list[str],
    *,
    judges: bool,
    git_sha: str,
    now: datetime | None = None,
) -> dict:
    return {
        "schema": _META_SCHEMA,
        "recorded_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "git_sha": git_sha,
        "models": current_models(settings),
        "pipeline": current_pipeline(settings),
        "judges": judges,
        "pair_ids": pair_ids,
    }


def read_meta(directory: Path = CASSETTE_DIR) -> dict:
    path = directory / META_NAME
    if not path.exists():
        # Written last by a *finished* recording, so its absence means an interrupted one.
        msg = f"{path} is missing: the cassettes were never fully recorded. Re-run run_eval.py --record."
        raise ReplayError(msg)
    return json.loads(path.read_text(encoding="utf-8"))


def _differences(recorded: dict, current: dict, label: str) -> list[str]:
    return [
        f"{label} {key}: recorded {recorded.get(key)!r}, now {value!r}"
        for key, value in current.items()
        if recorded.get(key) != value
    ]


def staleness_warnings(meta: dict, models: dict[str, str], pipeline: dict, now: datetime | None = None) -> list[str]:
    """Reasons to distrust the cassettes. Warnings, never errors: age and drift are judgement calls,
    and a model change that really alters requests is already a hard miss at replay.
    """
    warnings = []
    try:
        recorded_at = datetime.fromisoformat(meta["recorded_at"])
    except (KeyError, ValueError) as exc:
        msg = f"{META_NAME} has no readable recorded_at: {exc!r}"
        raise ReplayError(msg) from exc
    age = (now or datetime.now(UTC)) - recorded_at
    if age > STALE_AFTER:
        warnings.append(
            f"cassettes were recorded {age.days} days ago (threshold {STALE_AFTER.days}); "
            "they may describe models and prompts that have since moved -- re-record"
        )
    warnings += _differences(meta.get("models", {}), models, "model")
    warnings += _differences(meta.get("pipeline", {}), pipeline, "pipeline setting")
    return warnings


def require_judges_match(meta: dict, *, judges: bool) -> None:
    """Judge calls live in the pair cassettes, so `--judges` has to agree with how they were made.

    Without the flag, recorded judge calls go unplayed; with it against a judge-less recording,
    every judge call misses. Both would abort anyway, but pair by pair and with a message about
    HTTP requests rather than the flag.
    """
    if bool(meta.get("judges")) != judges:
        recorded = "with" if meta.get("judges") else "without"
        msg = f"cassettes were recorded {recorded} --judges; replay must pass the same setting"
        raise ReplayError(msg)


# -------------------------------------------------------------------------------------------
# Environment: nothing live, nothing traced
# -------------------------------------------------------------------------------------------


def _offline_tokenize(_self: object, texts: list[str], model: str | None = None) -> list[list[str]]:
    """Stands in for `voyageai` tokenization during record and replay; see `offline_environment`."""
    return [text.split() for text in texts]


@contextlib.contextmanager
def offline_environment(mode: Mode) -> Iterator[None]:
    """LangSmith tracing off in both modes; dummy provider keys in replay.

    Tracing off means no LangSmith call is recorded into a cassette or attempted during replay.
    It needs three things, because each one alone was not enough: the environment (a `.env` with
    tracing on would otherwise win -- `Settings` loads it and `_configure_langsmith` writes the
    variables back), LangSmith's own cache of environment lookups (filled on first use, so a
    late override is invisible), and a tracing context (which overrides both for the run's
    tasks).

    Dummy keys in replay so that a request that somehow escaped the cassettes is a 401 from the
    provider, not a billed call with a real key.

    Also keeps Voyage's tokenizer off the network. `langchain_voyageai` tokenizes every text it
    embeds, queries included, only to size batches, and `voyageai` loads that tokenizer from the
    Hugging Face Hub. On the recording machine the Hub cache was warm, so `_setup.yaml` captured
    two `HEAD`s; on a fresh CI runner the cache is cold, the Hub `GET`s the file, and that is a
    cassette miss in the first warm-up call. Every eval embed is one short text, which is one
    batch whatever the count, so a whitespace count batches identically and needs no file.

    Also silences `QdrantClient`'s compatibility check. It is a fire-and-forget daemon thread
    started by the constructor, so its `GET /` lands at an arbitrary moment: inside whichever
    cassette happens to be open (a miss at replay, or an unplayed recording), or after it has
    closed (a real call). Nothing about the eval depends on its result.
    """
    from langsmith import tracing_context  # noqa: PLC0415 -- runtime dependency, kept off import time
    from langsmith.utils import get_env_var  # noqa: PLC0415
    from qdrant_client.qdrant_remote import QdrantRemote  # noqa: PLC0415
    from voyageai._base import _BaseClient  # noqa: PLC0415

    from app.config import get_settings  # noqa: PLC0415

    overrides = {
        "LANGSMITH_TRACING": "false",
        "LANGSMITH_TRACING_V2": "false",
        "LANGCHAIN_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
    }
    if mode is Mode.REPLAY:
        overrides |= {"ANTHROPIC_API_KEY": _REPLAY_KEY, "VOYAGE_API_KEY": _REPLAY_KEY}
    env_cache = cast("Any", get_env_var)  # an lru_cache wrapper that its overloads hide from the type checker
    with (
        mock.patch.dict(os.environ, overrides),
        tracing_context(enabled=False),
        mock.patch.object(QdrantRemote, "_check_compatibility", staticmethod(lambda *_args, **_kwargs: None)),
        mock.patch.object(_BaseClient, "tokenize", _offline_tokenize),
    ):
        env_cache.cache_clear()
        get_settings.cache_clear()
        try:
            yield
        finally:
            env_cache.cache_clear()
            get_settings.cache_clear()


def _is_local(address: object) -> bool:
    if not isinstance(address, tuple):
        return True  # AF_UNIX path
    host = str(address[0])
    if host in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@contextlib.contextmanager
def forbid_remote_sockets() -> Iterator[list[str]]:
    """Any Python-level connect to a non-loopback address raises and is logged in the yielded list.

    Belt and braces behind vcrpy: a request made outside a cassette (between pairs, or from a
    library vcrpy does not patch) would otherwise go live. The list exists because the app
    catches broad exceptions around providers, so a raise alone can be swallowed; `Harness` checks
    the list on exit. Postgres is unaffected: libpq does not go through Python sockets.
    """
    attempts: list[str] = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def refuse(address: object) -> None:
        attempts.append(str(address))
        msg = f"live network call to {address} attempted during replay"
        raise ReplayError(msg)

    def connect(self: socket.socket, address: Any) -> None:  # noqa: ANN401 -- mirrors socket.connect
        if not _is_local(address):
            refuse(address)
        return real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:  # noqa: ANN401
        if not _is_local(address):
            refuse(address)
        return real_connect_ex(self, address)

    with (
        mock.patch.object(socket.socket, "connect", connect),
        mock.patch.object(socket.socket, "connect_ex", connect_ex),
    ):
        yield attempts


# -------------------------------------------------------------------------------------------
# The harness
# -------------------------------------------------------------------------------------------


def _head(body: Any, limit: int = 300) -> str:  # noqa: ANN401 -- vcr hands over bytes, a file or an iterator
    if hasattr(body, "read"):
        body = body.read()
    text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)
    return text[:limit] + ("..." if len(text) > limit else "")


@contextlib.contextmanager
def _record_misses() -> Iterator[list[str]]:
    """Every request vcrpy refused to serve, captured where it is raised.

    Not read back from the exception that reaches the caller: `rerank` and
    `QdrantStore._ensure_payload_indexes` swallow theirs, and the Anthropic and Qdrant paths
    re-wrap theirs (an `APIConnectionError`, a 503), so what surfaces no longer names the request.
    """
    from vcr.errors import CannotOverwriteExistingCassetteException as Miss  # noqa: PLC0415

    misses: list[str] = []
    real_init = Miss.__init__

    def logging_init(self: Miss, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401 -- forwarded verbatim
        real_init(self, *args, **kwargs)
        request = kwargs["failed_request"]
        misses.append(f"{request.method} {request.uri}\n  body: {_head(request.body)}\n  {str(self)[:1500]}")

    with mock.patch.object(Miss, "__init__", logging_init):
        yield misses


class Harness:
    """Runs a coroutine inside one cassette, and enforces the invariants in the module docstring.

    Used as a context manager so the offline environment is entered and left with it; `run` is
    the only entry point that talks to vcrpy.
    """

    def __init__(self, mode: Mode, *, qdrant_url: str, directory: Path = CASSETTE_DIR) -> None:
        self.mode = mode
        self.directory = directory
        self._qdrant_host = urlparse(qdrant_url).hostname
        self._stack = contextlib.ExitStack()
        self._escapes: list[str] = []
        self.recorded: list[str] = []
        """Names of the cassettes written this run, in order."""

    def __enter__(self) -> Self:
        self._stack.enter_context(offline_environment(self.mode))
        if self.mode is Mode.REPLAY:
            self._escapes = self._stack.enter_context(forbid_remote_sockets())
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self._stack.close()
        if exc_type is None and self._escapes:
            msg = f"live network call(s) attempted during replay: {self._escapes}"
            raise ReplayError(msg)

    def _path(self, name: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            # A pair id becomes a filename; anything else could name a path outside the directory.
            msg = f"unsafe cassette name {name!r}"
            raise ReplayError(msg)
        return self.directory / f"{name}.yaml"

    def prepare_recording(self) -> None:
        """Start from an empty directory, so a pair dropped from the golden set leaves no orphan."""
        self.directory.mkdir(parents=True, exist_ok=True)
        for stale in [*self.directory.glob("*.yaml"), self.directory / META_NAME]:
            stale.unlink(missing_ok=True)

    def check_replayable(self, names: list[str]) -> list[str]:
        """Raise if any cassette is absent; return warnings for cassettes nothing asks for."""
        expected = {SETUP_NAME, *names}
        missing = sorted(n for n in expected if not self._path(n).exists())
        if missing:
            msg = f"no cassette for {missing} in {self.directory}: the golden set changed since recording -- re-record"
            raise ReplayError(msg)
        return [
            f"cassette {p.name} matches no golden pair"
            for p in sorted(self.directory.glob("*.yaml"))
            if p.stem not in expected
        ]

    def _vcr(self) -> Any:  # noqa: ANN401 -- vcr.VCR, imported lazily
        import vcr  # noqa: PLC0415 -- only record/replay needs it; the `eval` extra is optional

        return vcr.VCR(
            serializer="yaml",
            match_on=_MATCH_ON,
            before_record_request=functools.partial(_scrub_request, qdrant_host=self._qdrant_host),
            before_record_response=_scrub_response,
            decode_compressed_response=True,
        )

    async def run[T](self, name: str, fn: Callable[[], Awaitable[T]]) -> T:
        """Run `fn` with every HTTP call recorded to, or served from, `<name>.yaml`."""
        path = self._path(name)
        recording = self.mode is Mode.RECORD
        if recording:
            # Delete first, then record with ALL: a stale file would otherwise be loaded, and vcrpy
            # would serve requests from it instead of the network (or append to it). Measured:
            # on a fresh file `once` and `all` both record an identical request twice, so ALL is
            # not what makes the count right -- it is the mode that cannot replay while recording.
            path.unlink(missing_ok=True)
        with (
            self._vcr().use_cassette(
                str(path),
                record_mode="all" if recording else "none",
                allow_playback_repeats=False,
                record_on_exception=False,
            ) as cassette,
            _record_misses() as misses,
        ):
            try:
                result = await fn()
            except Exception as exc:
                if misses:
                    raise ReplayError(self._miss_message(name, misses)) from exc
                raise
            if recording:
                self._check_recorded(name, cassette)
            else:
                self._check_replayed(name, cassette, misses)
        if recording:
            self.recorded.append(name)
        return result

    @staticmethod
    def _miss_message(name: str, misses: list[str]) -> str:
        return (
            f"cassette miss in {name}: the pipeline made {len(misses)} request(s) the recording does not contain "
            f"(the code, prompt, settings or golden set changed since recording -- re-record).\nFirst:\n{misses[0]}"
        )

    def _check_replayed(self, name: str, cassette: Any, misses: list[str]) -> None:  # noqa: ANN401
        if misses:
            raise ReplayError(self._miss_message(name, misses))
        if not cassette.all_played:
            unplayed = [
                f"{request.method} {request.uri}\n  body: {_head(request.body)}"
                for index, request in enumerate(cassette.requests)
                if cassette.play_counts[index] == 0
            ]
            # The reranker's swallowed failure lands here: its recorded call is never played.
            msg = f"{name}: {len(unplayed)} recorded request(s) were never made this run. First:\n{unplayed[0]}"
            raise ReplayError(msg)

    @staticmethod
    def _check_recorded(name: str, cassette: Any) -> None:  # noqa: ANN401
        if len(cassette) == 0:
            msg = f"nothing was recorded for {name}: the pipeline made no provider call, which no question should do"
            raise ReplayError(msg)
        for request, response in zip(cassette.requests, cassette.responses, strict=True):
            code = response["status"]["code"]
            if code >= 400:  # noqa: PLR2004 -- HTTP error class
                # Kept, because replaying it reproduces the run faithfully -- but a baseline taken
                # over a provider error is worth a second look.
                log.warning(
                    "replay.recorded_http_error", pair=name, status=code, request=f"{request.method} {request.uri}"
                )

    def finish_recording(self, meta: dict, secret_literals: Iterable[str] = ()) -> None:
        """Scan, then write `meta.json` last: its presence is what says the recording completed.

        A cassette holding a credential is deleted rather than left for `git add` to find.
        """
        found = find_secrets(self.directory, secret_literals)
        if found:
            for path in self.directory.glob("*.yaml"):
                path.unlink()
            msg = "credential(s) reached a cassette; all cassettes were deleted:\n  " + "\n  ".join(found)
            raise ReplayError(msg)
        (self.directory / META_NAME).write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")


async def warm_services(*, judges: bool) -> None:
    """Build every lazily-constructed service, so its setup calls land in the setup cassette.

    `QdrantStore.__init__` makes a collection lookup and two payload-index calls,
    and `ask.py` builds one store per `lru_cache` factory (two, not one: the aggregate service has
    its own). Left lazy, those calls would fall into whichever pair happened to run first, which
    would then replay only in that position -- and every other pair's cassette would need them
    too. Warm here and each pair's cassette holds only its own question.
    """
    # Private factories on purpose: warming *is* calling the ones the route uses.
    from app.api.routers.ask import _aggregate_service, _service  # noqa: PLC0415
    from app.eval.judges import _judge  # noqa: PLC0415
    from app.generation.intent_router import _classifier  # noqa: PLC0415

    _service()
    _aggregate_service()
    _classifier()
    if judges:
        _judge()
