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

**`MovingWindowRateLimiter`, the exact one.** It stores a timestamp per request, so the window
slides off the oldest entry -- the same semantics as the hand-rolled ZSET this replaced.

`SlidingWindowCounterRateLimiter` was used first, for one day, because it costs **120 bytes per
key** against 1464 for this one (measured, 60 requests on one key). That was the wrong trade and
the measurement that killed it is worth keeping: the counter **does not honour its own
`Retry-After`**. Spend a 10-request budget in a 2-second window, and it says "reset in 2.00s"
exactly as this one does -- but a client that waits 2.2 s is granted **2 of 10**, and does not
get the full budget back until 4.2 s, twice the window. Because it weights the *previous*
window's count rather than expiring individual requests, a caller that did exactly what the
header told it still gets a 429, and the obvious client-side reaction is to retry in a tight
loop. This one grants 10 of 10 at 2.2 s.

The memory difference is 1464 vs 120 bytes per key, so ~29 MB against ~2.4 MB at 10k tenants x
2 scopes -- both nothing on a 16 GB box, and still less than half the 3120 bytes/key the ZSET
cost. Beware the 26x figure that briefly justified the counter: it compared `limits`' *cheapest*
strategy against *our* implementation. Like for like, exact against exact, `limits` is 2x
cheaper than the ZSET, and that is the honest number.

`FixedWindowRateLimiter` is cheaper still and wrong here: a caller can spend a full budget at
the end of one window and again at the start of the next, an observed burst of twice the limit.

What *is* given up by moving off the hand-rolled script, stated plainly because a reader will
otherwise assume it still holds:

- **`remaining` is a second observation, not part of the decision.** `hit()` returns a bool;
  the numbers come from `get_window_stats()` afterwards. Under concurrency the advertised
  `remaining` can therefore disagree with what the next request is granted -- the old Lua
  returned both from one atomic call. Two round trips per check instead of one.
- **The window boundary is inside `limits` now**, so it cannot be tested by injecting a clock
  the way the ZSET's arithmetic could. `test_the_full_budget_returns_after_the_advertised_reset`
  uses a real one-second window and really waits. It is also one of the two tests that catch a
  switch back to the counter -- both measured red in 5 of 5 mutation runs, the other being
  `test_window_expiry_is_set_so_buckets_do_not_leak` on the 1x-vs-2x TTL.
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
from limits.aio.strategies import MovingWindowRateLimiter

from app.config import get_settings

if TYPE_CHECKING:
    import redis.asyncio as aioredis

log = structlog.get_logger(__name__)


_storages: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, RedisStorage] = weakref.WeakKeyDictionary()
_limiters: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, MovingWindowRateLimiter] = weakref.WeakKeyDictionary()


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


def _limiter() -> MovingWindowRateLimiter:
    """The strategy bound to this loop's storage. Cached for the same reason as `_storage`."""
    loop = asyncio.get_running_loop()
    limiter = _limiters.get(loop)
    if limiter is None:
        limiter = MovingWindowRateLimiter(_storage())
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

    budget = Budget(limit=limit, remaining=stats.remaining, reset_seconds=_reset_seconds(stats.reset_time))
    if not allowed:
        retry_after = max(1, budget.reset_seconds)
        log.info("rate_limit.exceeded", scope=scope, subject=subject, retry_after=retry_after)
        raise RateLimitExceeded(retry_after, budget)
    return budget


def _reset_seconds(reset_time: float) -> int:
    """`limits`' absolute epoch reset into the delta the header advertises, rounded **up**.

    Rounding down would advertise a reset that has not happened yet, so a client obeying the
    header retries a moment early and gets a second 429.

    **There is no clamp here, and there was one for a day.** Under
    `SlidingWindowCounterRateLimiter` this had to special-case zero: that strategy stores the
    counter with a TTL of *twice* the window and derives the reset as
    `current_expires_in % expiry`, which is right inside the window but yields `120 % 60 == 0`
    at the instant one opens -- so the first request against a fresh key was told "resets now"
    while holding a spent budget. `MovingWindowRateLimiter` reports a full window on that same
    first request (measured: 60.00 s), because it expires individual entries rather than whole
    windows, so the workaround became dead code and dead code that looks defensive is worse than
    none.

    What stops the counter coming back is `test_window_expiry_is_set_so_buckets_do_not_leak` and
    `test_the_full_budget_returns_after_the_advertised_reset`, both red in 5 of 5 mutation runs.
    `test_a_fresh_window_advertises_a_full_window_not_zero` covers the same ground but is only red
    in **8 of 10** -- the modulo lands on zero only when the first hit falls within a millisecond
    of the window opening -- so treat it as a hint and not as the guard.
    """
    return max(0, math.ceil(reset_time - time.time()))
