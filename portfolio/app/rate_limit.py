"""Per-key sliding-window rate limiting on Redis.

Hand-rolled rather than `slowapi`, which the original plan named. Re-examined in full in
`docs/TECHNICAL_DECISIONS.md`; the short version, with the numbers measured rather than
assumed:

1. `limits[redis]>=5` requires `redis>3,<8.0.0` against this project's
   `redis[hiredis]>=8.0.0,<9.0.0`, and uv reports *that pair* as unsatisfiable. Careful:
   asking for `slowapi` unpinned does **not** error -- uv satisfies it by silently
   resolving `limits==1.6` and `slowapi==0.1.6`, releases from 2018 and 2022. Adopting
   slowapi means downgrading redis-py to 7.x, which resolves cleanly at current versions.
2. `slowapi` has no async storage path at all. `extension.py` imports `limits.storage`
   and `limits.strategies` -- the synchronous modules -- and calls `self.limiter.hit(...)`
   inline, so the Redis round trip blocks the event loop. Measured against localhost Redis:
   at 100 concurrent checks, 21.4 ms wall versus 11.1 ms for the async version; at 200,
   65.5 ms versus 18.5 ms. Single-request latency is a wash (0.32 ms vs 0.36 ms) -- the
   cost is head-of-line blocking, and it scales with Redis RTT, so a managed Redis one
   network hop away multiplies it.

`redis-py` 8 already ships `redis.asyncio`, so the remaining work is one Lua script.

Sliding window, not a fixed window: a fixed window lets a caller spend its whole budget at
the end of one window and again at the start of the next, so the observed burst is twice the
configured limit. The window here is a sorted set of request timestamps, trimmed on each
check.

The check is a Lua script so it is atomic. A read-then-write version has a real race:
concurrent requests all read a count below the limit and all proceed, which is precisely the
case rate limiting exists to stop.
"""

from __future__ import annotations

import asyncio
import time
import uuid
import weakref
from dataclasses import dataclass

import redis.asyncio as aioredis
import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)

# KEYS[1] window key; ARGV: now_ms, window_ms, limit, unique member
# Returns {allowed, retry_after_ms, remaining, reset_ms}
#
# `remaining` and `reset_ms` come back from the same atomic call that decides `allowed`,
# rather than from a second read afterwards. A follow-up ZCARD would report a count from a
# different instant, so under concurrency the advertised remaining would routinely disagree
# with what the next request is actually granted -- a client that trusts the header then
# paces itself wrongly, which is worse than sending no header at all.
_SLIDING_WINDOW = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
local used = redis.call('ZCARD', KEYS[1])
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
-- Time until the window has room again: when the oldest request in it falls out. With an
-- empty window that is a full window from now, which is what a first request should report.
local reset = window
if oldest[2] ~= nil then
  reset = tonumber(oldest[2]) + window - now
  if reset < 0 then reset = 0 end
end
if used >= limit then
  return {0, reset, 0, reset}
end
redis.call('ZADD', KEYS[1], now, ARGV[4])
redis.call('PEXPIRE', KEYS[1], window)
return {1, 0, limit - used - 1, reset}
"""


_clients: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, aioredis.Redis] = weakref.WeakKeyDictionary()


def _client() -> aioredis.Redis:
    """The Redis client for the *running event loop*, created lazily.

    Keyed per loop rather than cached once per process, because a `redis.asyncio` client
    binds its connection pool to the loop that created it. A single process-wide client
    breaks the moment a second loop appears -- which is not hypothetical: anything using
    `asyncio.run()` more than once (Streamlit's script model, a CLI, per-test loops) gets a
    client attached to a closed loop and every call fails. The test suite caught exactly
    this: some tests passed while others reported Redis unreachable on the same live server.

    A `WeakKeyDictionary` so entries disappear with their loop instead of leaking one pool
    per loop ever created.

    Lazy also matters with gunicorn's `--preload`: building a pool at import time would
    create it in the master process before forking, leaving children sharing socket state.
    """
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None:
        client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        _clients[loop] = client
    return client


@dataclass(frozen=True)
class Budget:
    """What is left of a subject's allowance, as the `X-RateLimit-*` headers report it.

    Returned from the *same* atomic script call that granted or refused the request, so the
    numbers describe one instant rather than two.
    """

    limit: int
    remaining: int
    reset_seconds: int
    """Seconds until the window has room again -- a delta, not a wall-clock timestamp.

    GitHub's `X-RateLimit-Reset` is epoch seconds and that is the more common reading of the
    name, but it forces the client to trust its own clock against ours. A delta needs no
    agreement about time at all, and it is what the IETF `RateLimit` draft settled on for the
    same reason. Documented in the OpenAPI description because the name alone is ambiguous.
    """

    def headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(self.reset_seconds),
        }


class RateLimitExceeded(Exception):
    """Raised with the number of seconds after which the caller may retry."""

    def __init__(self, retry_after_seconds: int, budget: Budget) -> None:
        self.retry_after_seconds = retry_after_seconds
        self.budget = budget
        super().__init__(f"Rate limit exceeded; retry in {retry_after_seconds}s")


async def check(scope: str, subject: str, limit: int) -> Budget | None:
    """Consume one unit of `subject`'s budget for `scope`, or raise.

    Returns the remaining budget so a caller can advertise it in headers, or **None** when
    Redis was unreachable. None rather than a synthetic full budget: during an outage the
    limit is not being enforced at all, and reporting `remaining: 60` would tell a client the
    guardrail is intact. Absent headers say "unknown", which is the truth.

    `subject` is an **API key id**, not a tenant id -- so one key cannot exhaust the budget of
    another key belonging to the same tenant. Deliberately typed as an opaque string and named
    for what it is used as rather than what it currently holds: this function should not need
    to change if the bucket is ever widened or narrowed.

    `scope` keeps endpoints in separate buckets, so exhausting the upload budget does not
    also block questions.

    **Fails open.** If Redis is unreachable the request is allowed and a warning is logged.
    That is a deliberate availability-over-strictness choice: a rate limiter is a guardrail,
    and letting its outage take down the whole API converts a degraded dependency into a
    total one. The tradeoff is that a Redis outage removes the protection exactly when load
    may be why Redis is struggling -- hence the loud log rather than a silent pass.
    """
    settings = get_settings()
    window_ms = settings.rate_limit_window_seconds * 1000
    now_ms = int(time.time() * 1000)
    key = f"ratelimit:{scope}:{subject}"

    try:
        allowed, retry_after_ms, remaining, reset_ms = await _client().eval(
            _SLIDING_WINDOW, 1, key, now_ms, window_ms, limit, uuid.uuid4().hex
        )
    except Exception as exc:  # noqa: BLE001 -- any Redis failure must not take down the API
        log.warning("rate_limit.unavailable", scope=scope, error=str(exc))
        return None

    budget = Budget(limit=limit, remaining=int(remaining), reset_seconds=_ceil_seconds(reset_ms))
    if not int(allowed):
        retry_after = max(1, _ceil_seconds(retry_after_ms))
        log.info("rate_limit.exceeded", scope=scope, subject=subject, retry_after=retry_after)
        raise RateLimitExceeded(retry_after, budget)
    return budget


def _ceil_seconds(milliseconds: int) -> int:
    """Round up, always. Rounding down would advertise a reset that has not happened yet, so
    a client obeying the header retries a moment early and gets a second 429.
    """
    return -(-int(milliseconds) // 1000)
