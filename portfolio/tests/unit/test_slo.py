"""The `/ask` latency SLO (`app/observability/slo.py`).

Most of this needs no service: the percentile, the too-few-samples rule, both fail-open paths,
the webhook, and which `/ask` branches get sampled are all tested against stubs. The part that
is *about* Redis -- samples pooled in a sorted set, equal latencies not collapsing, the window
trim -- runs against a real one and skips when none is reachable, so CI asserts this file did
not skip, like the other service-backed suites.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError

from app import rate_limit
from app.api import deps
from app.api.main import app
from app.api.routers import ask as ask_router
from app.auth.scopes import UNRESTRICTED
from app.auth.service import Principal
from app.config import Settings, get_settings
from app.generation.answer_service import Answer
from app.observability import slo

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine, Iterator

DOCKERFILE = Path(__file__).resolve().parents[2] / ".docker" / "Dockerfile"


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """The cached `Settings`, with SLO fields a test can set without touching the environment."""
    current = get_settings()
    monkeypatch.setattr(current, "slo_min_samples", 20)
    monkeypatch.setattr(current, "slo_ask_p95_ms", 15_000.0)
    monkeypatch.setattr(current, "slo_window_seconds", 900)
    monkeypatch.setattr(current, "slo_webhook_url", SecretStr(""))
    return current


# -------------------------------------------------------------------------------------------
# The judgement: percentile and sample floor
# -------------------------------------------------------------------------------------------


def test_p95_is_a_latency_some_request_actually_had() -> None:
    assert slo.p95([float(n) for n in range(1, 21)]) == 19.0
    assert slo.p95([float(n) for n in range(1, 101)]) == 95.0
    assert slo.p95([5.0]) == 5.0
    assert slo.p95([3.0, 1.0, 2.0]) == 3.0


@pytest.mark.usefixtures("settings")
def test_too_few_samples_is_no_verdict_rather_than_a_pass() -> None:
    assert slo.evaluate([60_000.0] * 19) is None


@pytest.mark.usefixtures("settings")
def test_a_slow_window_breaches_and_a_normal_one_does_not() -> None:
    measured_normal = [600.0] + [10_000.0] * 18 + [12_000.0]
    healthy = slo.evaluate(measured_normal)
    assert healthy is not None
    assert not healthy.breached

    slow = slo.evaluate([10_000.0] * 18 + [20_000.0, 20_000.0])
    assert slow is not None
    assert slow.p95_ms == 20_000.0
    assert slow.breached


# -------------------------------------------------------------------------------------------
# Failing open
# -------------------------------------------------------------------------------------------


def _unreachable() -> NoReturn:
    msg = "redis is down"
    raise ConnectionError(msg)


@pytest.mark.usefixtures("settings")
async def test_recording_with_redis_unreachable_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rate_limit, "_client", _unreachable)
    await slo.record_ask_latency(1234.0)


@pytest.mark.usefixtures("settings")
async def test_checking_with_redis_unreachable_is_no_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rate_limit, "_client", _unreachable)
    assert await slo.check_ask_latency() is None


# -------------------------------------------------------------------------------------------
# The webhook
# -------------------------------------------------------------------------------------------


def _capture_posts(monkeypatch: pytest.MonkeyPatch, status: int = 200) -> list[dict[str, Any]]:
    """Routes `slo`'s `httpx.AsyncClient` through a `MockTransport` and records each body."""
    posted: list[dict[str, Any]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        import json  # noqa: PLC0415

        posted.append(json.loads(request.content))
        return httpx.Response(status)

    real_client = httpx.AsyncClient

    def _client(*, timeout: float) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(_handler), timeout=timeout)

    monkeypatch.setattr(slo.httpx, "AsyncClient", _client)
    return posted


def _samples(values: list[float]) -> Callable[[], Coroutine[object, object, list[float]]]:
    async def _window() -> list[float]:
        return values

    return _window


async def test_a_breach_posts_the_numbers_to_the_webhook(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "slo_webhook_url", SecretStr("https://hooks.example.test/slo"))
    monkeypatch.setattr(slo, "window_samples", _samples([10_000.0] * 18 + [20_000.0, 20_000.0]))
    posted = _capture_posts(monkeypatch)

    verdict = await slo.check_ask_latency()

    assert verdict is not None
    assert verdict.breached
    assert len(posted) == 1
    assert posted[0]["p95_ms"] == 20_000.0
    assert posted[0]["threshold_ms"] == 15_000.0
    assert posted[0]["samples"] == 20
    assert "breached" in posted[0]["text"]


async def test_a_healthy_window_posts_nothing(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "slo_webhook_url", SecretStr("https://hooks.example.test/slo"))
    monkeypatch.setattr(slo, "window_samples", _samples([1_000.0] * 20))
    posted = _capture_posts(monkeypatch)

    await slo.check_ask_latency()

    assert posted == []


@pytest.mark.usefixtures("settings")
async def test_no_webhook_configured_means_no_post(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(slo, "window_samples", _samples([20_000.0] * 20))
    posted = _capture_posts(monkeypatch)

    verdict = await slo.check_ask_latency()

    assert verdict is not None
    assert verdict.breached
    assert posted == []


async def test_a_failing_webhook_does_not_raise_into_the_worker(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "slo_webhook_url", SecretStr("https://hooks.example.test/slo"))
    monkeypatch.setattr(slo, "window_samples", _samples([20_000.0] * 20))
    posted = _capture_posts(monkeypatch, status=500)

    verdict = await slo.check_ask_latency()

    assert verdict is not None
    assert len(posted) == 1


def test_a_malformed_webhook_url_fails_at_boot() -> None:
    with pytest.raises(ValidationError, match="SLO_WEBHOOK_URL"):
        Settings(slo_webhook_url=SecretStr("hooks.slack.com/services/x"))


# -------------------------------------------------------------------------------------------
# Which /ask branches are sampled
# -------------------------------------------------------------------------------------------


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def as_a_tenant() -> Iterator[None]:
    key_id = f"key-{uuid.uuid4().hex}"
    app.dependency_overrides[deps.current_principal] = lambda: Principal(
        tenant_id="a" * 32, key_id=key_id, scopes=UNRESTRICTED
    )
    yield
    app.dependency_overrides.clear()


def _recorded(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    samples: list[float] = []

    async def _record(latency_ms: float) -> None:
        samples.append(latency_ms)

    monkeypatch.setattr(ask_router, "record_ask_latency", _record)
    return samples


def _intent(label: str) -> Callable[[str], Coroutine[object, object, str]]:
    async def _classify(_question: str) -> str:
        return label

    return _classify


@pytest.mark.usefixtures("as_a_tenant")
async def test_a_factual_answer_is_sampled(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.retrieval.document_scope import DocumentScope  # noqa: PLC0415

    class _Stub:
        async def answer(self, _question: str, **_kwargs: object) -> Answer:
            return Answer(text="an answer", citations=[], retrieved_chunks=[])

    async def _no_scope(_question: str, _tenant_id: str) -> DocumentScope:
        return DocumentScope()

    monkeypatch.setattr(ask_router, "classify_intent", _intent("factual"))
    monkeypatch.setattr(ask_router, "_service", _Stub)
    monkeypatch.setattr(ask_router, "_document_scope", _no_scope)
    samples = _recorded(monkeypatch)

    response = await client.post("/v1/ask", json={"question": "what did they measure?"})

    assert response.status_code == 200
    assert len(samples) == 1
    assert samples[0] >= 0


@pytest.mark.usefixtures("as_a_tenant")
async def test_a_question_answered_without_retrieval_is_not_sampled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sub-second refusal in the window would pull the p95 down while factual answers slowed."""
    monkeypatch.setattr(ask_router, "classify_intent", _intent("out_of_scope"))
    samples = _recorded(monkeypatch)

    response = await client.post("/v1/ask", json={"question": "what's the weather?"})

    assert response.status_code == 200
    assert samples == []


# -------------------------------------------------------------------------------------------
# The worker actually consumes the check's queue
# -------------------------------------------------------------------------------------------


def test_the_worker_cli_listens_on_every_queue_a_task_uses() -> None:
    """A queue missing from `--queues` is enqueued into and never consumed -- the SLO check
    would stop running with no error anywhere, which is the one failure an alert cannot report.
    """
    from app.worker.tasks import app as worker_app  # noqa: PLC0415

    # Anchored on the closing `"]` so it reads the CMD, not the comment above it naming the flag.
    match = re.search(r"--queues\s+([\w,]+)\"\]", DOCKERFILE.read_text())
    assert match, "the worker CMD no longer passes --queues"
    listened = set(match.group(1).split(","))
    # `builtin` is procrastinate's own maintenance tasks, which nothing here defers.
    used = {task.queue for task in worker_app.tasks.values()} - {"builtin"}
    assert used <= listened, f"tasks use {sorted(used - listened)} but the worker never listens there"


# -------------------------------------------------------------------------------------------
# Against a real Redis
# -------------------------------------------------------------------------------------------


@pytest.fixture
async def real_redis(monkeypatch: pytest.MonkeyPatch) -> str:
    """A unique key per test, so runs don't read each other's samples in a shared Redis."""
    try:
        await rate_limit._client().ping()
    except Exception:  # noqa: BLE001 -- unreachable means skip, not fail
        pytest.skip("no Redis reachable -- start it with docker compose")
    key = f"test-slo-{uuid.uuid4().hex}"
    monkeypatch.setattr(slo, "ASK_LATENCY_KEY", key)
    return key


@pytest.mark.usefixtures("settings", "real_redis")
async def test_samples_are_pooled_and_equal_latencies_do_not_collapse() -> None:
    for _ in range(3):
        await slo.record_ask_latency(500.0)
    await slo.record_ask_latency(9000.0)

    assert sorted(await slo.window_samples()) == [500.0, 500.0, 500.0, 9000.0]


@pytest.mark.usefixtures("settings")
async def test_samples_older_than_the_window_are_dropped(real_redis: str) -> None:
    client = rate_limit._client()
    stale = slo.time.time() - 2000
    await client.zadd(real_redis, {"42000.0:stale": stale})

    await slo.record_ask_latency(700.0)

    assert await slo.window_samples() == [700.0]
    assert await client.zcard(real_redis) == 1, "the stale sample must be trimmed, not just filtered"
    assert 0 < await client.ttl(real_redis) <= get_settings().slo_window_seconds
