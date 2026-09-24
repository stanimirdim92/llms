"""The `/ask` latency SLO: the api records, the worker checks, a webhook hears about a breach.

Epic 4 Phase 4's latency half (`docs/EPIC_4_PLAN.md`). The faithfulness half needs Epic 2's
scores and is deliberately absent rather than stubbed -- a placeholder check that always passes
would read as a guardrail that exists.

**The check runs in the worker, not the api.** The api runs `GUNICORN_WORKERS` processes, so a
check there would alert once per process per breach, and each would see only the samples it
shares with the others through Redis anyway. procrastinate's periodic deferrer enqueues one job
per tick across however many workers run, so exactly one check happens.

**Redis holds the samples** because they must be pooled across api processes -- the same reason
the rate limiter's counters live there, and on the same connection pool (`rate_limit._client`),
so there is no second client to configure or keep healthy.

**Both halves fail open.** This is a guardrail on the service, not part of it: an unreachable
Redis must not fail a question that was answered, and must not crash the worker's job loop.
Each logs loudly instead (root `CLAUDE.md` rule 9).
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass

import httpx
import structlog

from app import rate_limit
from app.config import get_settings

log = structlog.get_logger(__name__)

ASK_LATENCY_KEY = "slo:ask:latency_ms"
"""A sorted set scored by the wall-clock second each sample was recorded, so a window is one
`ZRANGEBYSCORE` and expiry is one `ZREMRANGEBYSCORE`. Members carry the latency itself; see
`_member`."""

CHECK_CRON = "*/5 * * * *"
"""How often the worker checks. Shorter than any sane window, so a breach is reported within
five minutes of the window crossing the threshold."""

_WEBHOOK_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class Verdict:
    p95_ms: float
    samples: int
    threshold_ms: float
    window_seconds: int

    @property
    def breached(self) -> bool:
        return self.p95_ms > self.threshold_ms


def _member(latency_ms: float) -> str:
    """Unique per sample. A sorted set de-duplicates members, so two requests that took the same
    number of milliseconds would otherwise collapse into one sample and understate the load --
    and the collapse would be commonest exactly when latency is flat and the SLO is healthy.
    """
    return f"{latency_ms:.1f}:{uuid.uuid4().hex}"


def _latency_of(member: object) -> float:
    # `object` because redis-py types `zrangebyscore`'s result as the union of every shape its
    # options can return; without `withscores` it is plain members.
    text = member.decode() if isinstance(member, bytes) else str(member)
    return float(text.split(":", 1)[0])


def p95(samples: list[float]) -> float:
    """Nearest-rank 95th percentile: a latency one of the samples actually had.

    Not interpolated. An interpolated p95 over 20 samples can land between the two slowest
    answers and report a number no request ever took, which is a poor thing to put in an alert.
    """
    ordered = sorted(samples)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


async def record_ask_latency(latency_ms: float) -> None:
    """Add one answered `/ask` to the window, and drop what has aged out of it.

    One pipelined round trip. The trim runs on every write so the set stays bounded by one
    window's traffic, and the TTL removes the key entirely once traffic stops.
    """
    window = get_settings().slo_window_seconds
    now = time.time()
    try:
        client = rate_limit._client()
        async with client.pipeline(transaction=False) as pipe:
            pipe.zadd(ASK_LATENCY_KEY, {_member(latency_ms): now})
            pipe.zremrangebyscore(ASK_LATENCY_KEY, "-inf", now - window)
            pipe.expire(ASK_LATENCY_KEY, window)
            await pipe.execute()
    except Exception as exc:  # noqa: BLE001 -- the answer was already produced; never fail it here
        log.warning("slo.record_unavailable", error=str(exc))


async def window_samples() -> list[float]:
    window = get_settings().slo_window_seconds
    client = rate_limit._client()
    members = await client.zrangebyscore(ASK_LATENCY_KEY, time.time() - window, "+inf")
    return [_latency_of(m) for m in members]


def evaluate(samples: list[float]) -> Verdict | None:
    """None when there are too few samples to say anything.

    Not a pass. Three quiet requests overnight have a p95 that is just the slowest of the three,
    so alerting on it pages someone for one slow answer, and reporting it as healthy claims a
    measurement nobody took.
    """
    settings = get_settings()
    if len(samples) < settings.slo_min_samples:
        return None
    return Verdict(
        p95_ms=p95(samples),
        samples=len(samples),
        threshold_ms=settings.slo_ask_p95_ms,
        window_seconds=settings.slo_window_seconds,
    )


async def _notify(verdict: Verdict) -> None:
    url = get_settings().slo_webhook_url.get_secret_value().strip()
    if not url:
        return
    text = (
        f"/ask latency SLO breached: p95 {verdict.p95_ms:.0f} ms over the last "
        f"{verdict.window_seconds} s ({verdict.samples} answers), threshold {verdict.threshold_ms:.0f} ms."
    )
    # `text` so a Slack incoming webhook renders it as-is; the numbers alongside for anything else.
    payload = {
        "text": text,
        "slo": "ask_latency_p95",
        "p95_ms": verdict.p95_ms,
        "threshold_ms": verdict.threshold_ms,
        "samples": verdict.samples,
        "window_seconds": verdict.window_seconds,
    }
    try:
        async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        # The breach itself is already logged at error level by the caller, so a dead alert sink
        # loses the notification but not the record of it.
        log.error("slo.webhook_failed", error=type(exc).__name__)


async def check_ask_latency() -> Verdict | None:
    try:
        samples = await window_samples()
    except Exception as exc:  # noqa: BLE001 -- can't measure is logged, not raised into the job loop
        log.warning("slo.check_unavailable", error=str(exc))
        return None

    verdict = evaluate(samples)
    if verdict is None:
        log.info("slo.insufficient_samples", samples=len(samples), required=get_settings().slo_min_samples)
        return None
    if verdict.breached:
        log.error(
            "slo.breach",
            slo="ask_latency_p95",
            p95_ms=verdict.p95_ms,
            threshold_ms=verdict.threshold_ms,
            samples=verdict.samples,
            window_seconds=verdict.window_seconds,
        )
        await _notify(verdict)
    else:
        log.info("slo.ok", p95_ms=verdict.p95_ms, threshold_ms=verdict.threshold_ms, samples=verdict.samples)
    return verdict
