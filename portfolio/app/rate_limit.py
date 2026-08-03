"""Per-key sliding-window rate limiting on Redis, via `limits`.

`limits` is the engine behind flask-limiter and slowapi, and it is the counting that is
battle-tested here -- not the policy. This module is the policy: which subject, which bucket,
what happens when Redis dies, and what the client is told. All four are ours because `limits`
does not have opinions about any of them, and each one has cost us a bug before.

Reached through `limits.aio`, never `limits.storage`/`limits.strategies`. The synchronous
modules are what `slowapi` imports -- `extension.py:514` is a bare `self.limiter.hit(...)` --
so every check there blocks the event loop. Measured against localhost Redis: 21.4 ms at 100
concurrent checks versus 11.1 ms async, 65.5 ms versus 18.5 ms at 200. Single-request latency
is a wash; the cost is head-of-line blocking and it scales with Redis RTT.

`implementation="redispy"` rather than the coredis default, so this runs on the
`redis[hiredis]>=8` the project already has: no coredis, no third Redis client, no downgrade.
The `redis>3,<8.0.0` pin people hit belongs to the *synchronous* `limits[redis]` extra only.

**`SlidingWindowCounterRateLimiter`, which is an approximation.** It keeps two counters per
key -- current window and previous -- and weights the previous one by how much of it still
overlaps, instead of storing a timestamp per request. So a burst can be off by a fraction of
the previous window's count where the old hand-rolled ZSET was exact. What it buys, measured:
**120 bytes per key** after 60 requests against 3120 for the ZSET and 1464 for `limits`' own
exact `MovingWindowRateLimiter`. At the 10k-tenant target that is ~2.4 MB of Redis instead of
~62 MB. The property that actually matters is preserved: unlike a *fixed* window it cannot be
straddled to spend two budgets back to back.

What was given up by moving off the hand-rolled script, stated plainly because a reader will
otherwise assume it still holds:

- **`remaining` is a second observation, not part of the decision.** `hit()` returns a bool;
  the numbers come from `get_window_stats()` afterwards. Under concurrency the advertised
  `remaining` can therefore disagree with what the next request is granted -- the old Lua
  returned both from one atomic call. Two round trips per check instead of one.
- **`Retry-After` is conservative rather than tight.** The counter knows when a *window* rolls,
  not when the oldest request falls out, so a refused caller may be told to wait longer than
  strictly needed. Never shorter, which is the direction that matters.
- **The window boundary is Redis key expiry, not arithmetic we control**, so it cannot be
  tested by injecting a clock. `test_a_full_window_frees_a_slot` uses a real one-second window
  and really waits.
"""

from __future__ import annotations

import asyncio
import math
import time
import weakref
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, cast

import structlog
from limits import RateLimitItemPerSecond
from limits.aio.storage import RedisStorage
from limits.aio.storage.redis.redispy import RedispyBridge
from limits.aio.strategies import SlidingWindowCounterRateLimiter

from app.config import get_settings

if TYPE_CHECKING:
    import redis.asyncio as aioredis

log = structlog.get_logger(__name__)


_storages: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, RedisStorage] = weakref.WeakKeyDictionary()
_limiters: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, SlidingWindowCounterRateLimiter] = (
    weakref.WeakKeyDictionary()
)


def _storage() -> RedisStorage:
    """The `limits` storage for the *running event loop*, created lazily.

    Keyed per loop rather than once per process, because the redispy bridge holds a
    `redis.asyncio` client and that binds its connection pool to the loop that created it. A
    single process-wide storage breaks the moment a second loop appears -- which is not
    hypothetical: anything calling `asyncio.run()` more than once (Streamlit's script model, a
    CLI, per-test loops) gets a client attached to a closed loop and every call fails. The test
    suite caught exactly this shape before: some tests passing while others reported Redis
    unreachable against the same live server. A module-level `storage_from_string(...)`, which
    is how every `limits` example is written, is the bug.

    A `WeakKeyDictionary` so entries disappear with their loop instead of leaking a pool per
    loop ever created.

    Lazy also matters with gunicorn's `--preload`: building a pool at import time would create
    it in the master process before forking, leaving children sharing socket state.

    `max_connections` is passed explicitly because **`limits` defaults it to 100** -- measured,
    not read -- and at 200 concurrent checks the pool raises `MaxConnectionsError: Too many
    connections` rather than queueing. That surfaces as 500s under exactly the load rate
    limiting exists for.
    """
    loop = asyncio.get_running_loop()
    storage = _storages.get(loop)
    if storage is None:
        settings = get_settings()
        storage = RedisStorage(
            f"async+{settings.redis_url}",
            implementation="redispy",
            max_connections=settings.redis_max_connections,
        )
        _storages[loop] = storage
    return storage


def _limiter() -> SlidingWindowCounterRateLimiter:
    """The strategy bound to this loop's storage. Cached for the same reason as `_storage`."""
    loop = asyncio.get_running_loop()
    limiter = _limiters.get(loop)
    if limiter is None:
        limiter = SlidingWindowCounterRateLimiter(_storage())
        _limiters[loop] = limiter
    return limiter


def _client() -> aioredis.Redis:
    """The underlying `redis.asyncio` client, for `GET /health/ready`'s probe.

    Reaching into the bridge deliberately, rather than building a second client: the readiness
    probe must report on the *same* connection pool the limiter uses, or a healthy ping would
    coexist with a limiter that cannot reach Redis at all.

    Via `connection_getter` rather than the `.storage` attribute that holds the identical object
    (checked at runtime: `client is bridge.storage`), because only the former is annotated on
    the class -- `.storage` is assigned untyped in `__init__`, so `ty` rejects it outright and
    no cast can recover an attribute the type does not have.

    The `isinstance` narrowing is what makes that annotation reachable, and it doubles as an
    assertion that `implementation="redispy"` above is still in force: swap it for the coredis
    default and this raises here instead of silently probing a client the limiter never uses.

    The `cast` is because `connection_getter` is declared as returning a *protocol*, which does
    not carry `pttl`/`scan_iter`; the object really is a `redis.asyncio.Redis`, verified rather
    than assumed. The narrowing above is what makes that safe to assert.
    """
    bridge = _storage().bridge
    if not isinstance(bridge, RedispyBridge):
        msg = f"rate limiting expects the redispy bridge, got {type(bridge).__name__}"
        raise TypeError(msg)
    return cast("aioredis.Redis", bridge.connection_getter(False))


@lru_cache(maxsize=32)
def _item(limit: int, window_seconds: int) -> RateLimitItemPerSecond:
    """`limit` requests per `window_seconds`. Cached because it is immutable and hashable, and
    `check` is on the hot path for every authenticated request.
    """
    return RateLimitItemPerSecond(limit, window_seconds)


@dataclass(frozen=True)
class Budget:
    """What is left of a subject's allowance, as the `X-RateLimit-*` headers report it."""

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

    **Fails open, and `limits` does not.** An unreachable Redis raises
    `redis.exceptions.ConnectionError` straight out of `hit()`, which without this `except`
    would 500 every request the moment Redis blinked. That is a deliberate
    availability-over-strictness choice: a rate limiter is a guardrail, and letting its outage
    take down the whole API converts a degraded dependency into a total one. The tradeoff is
    that a Redis outage removes the protection exactly when load may be why Redis is
    struggling -- hence the loud log rather than a silent pass.

    `hit` and `get_window_stats` are two calls, so the budget describes a moment just after
    the decision rather than the decision itself. Both are inside the one `try`: a failure
    between them must fail open too, not return a half-formed budget.
    """
    window = get_settings().rate_limit_window_seconds
    item = _item(limit, window)
    limiter = _limiter()

    try:
        allowed = await limiter.hit(item, scope, subject)
        stats = await limiter.get_window_stats(item, scope, subject)
    except Exception as exc:  # noqa: BLE001 -- any Redis failure must not take down the API
        log.warning("rate_limit.unavailable", scope=scope, error=str(exc))
        return None

    budget = Budget(limit=limit, remaining=stats.remaining, reset_seconds=_reset_seconds(stats.reset_time, window))
    if not allowed:
        retry_after = max(1, budget.reset_seconds)
        log.info("rate_limit.exceeded", scope=scope, subject=subject, retry_after=retry_after)
        raise RateLimitExceeded(retry_after, budget)
    return budget


def _reset_seconds(reset_time: float, window: int) -> int:
    """`limits`' absolute epoch reset into the delta the header advertises, rounded **up**.

    Rounding down would advertise a reset that has not happened yet, so a client obeying the
    header retries a moment early and gets a second 429.

    **The zero case is a `limits` boundary bug, not a real "resets now".** Its counter stores
    the current window with a TTL of *twice* the window (measured: 119999 ms for a 60 s window)
    so the count survives to serve as the next window's "previous", then derives the reset as
    `current_expires_in % expiry`. For any instant inside the window that is correct -- at t
    seconds in, `(2w - t) % w == w - t`. At **t = 0 it yields `120 % 60 == 0`**, so the very
    first request of a fresh window is told the window resets immediately. For a low-traffic key
    that is the common request, and a client pacing on the header retries at once and earns a
    429. A request was just counted, so the truthful answer is a full window from now.

    Delete this clamp and `test_reset_is_never_zero_while_the_window_holds_a_request` goes red.
    """
    seconds = max(0, math.ceil(reset_time - time.time()))
    return window if seconds == 0 else seconds
