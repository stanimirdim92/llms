"""Per-tenant sliding-window rate limiting on Redis.

Hand-rolled rather than `slowapi`, which the original plan named. Two reasons, both hard:

1. `slowapi` stores counters through `limits`, and `limits[redis]` requires `redis<8.0.0`
   while this project depends on `redis>=8.0.1`. uv reports that as unsatisfiable, not as a
   warning.
2. Even resolved, `limits`' redis-py storage is *synchronous*, so every rate-limit check
   would block the event loop -- the exact failure this codebase has repeatedly designed
   around. Non-blocking would mean adding `coredis`, a third redis client alongside
   `redis-py` and `aiocache[redis]`.

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

import redis.asyncio as aioredis
import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)

# KEYS[1] window key; ARGV: now_ms, window_ms, limit, unique member
# Returns {allowed, retry_after_ms}
_SLIDING_WINDOW = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, tonumber(ARGV[1]) - tonumber(ARGV[2]))
local used = redis.call('ZCARD', KEYS[1])
if used >= tonumber(ARGV[3]) then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  local retry = tonumber(oldest[2]) + tonumber(ARGV[2]) - tonumber(ARGV[1])
  if retry < 0 then retry = 0 end
  return {0, retry}
end
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[4])
redis.call('PEXPIRE', KEYS[1], ARGV[2])
return {1, 0}
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


class RateLimitExceeded(Exception):
    """Raised with the number of seconds after which the caller may retry."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Rate limit exceeded; retry in {retry_after_seconds}s")


async def check(scope: str, tenant_id: str, limit: int) -> None:
    """Consume one unit of `tenant_id`'s budget for `scope`, or raise.

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
    key = f"ratelimit:{scope}:{tenant_id}"

    try:
        allowed, retry_after_ms = await _client().eval(
            _SLIDING_WINDOW, 1, key, now_ms, window_ms, limit, uuid.uuid4().hex
        )
    except Exception as exc:  # noqa: BLE001 -- any Redis failure must not take down the API
        log.warning("rate_limit.unavailable", scope=scope, error=str(exc))
        return

    if not int(allowed):
        retry_after = max(1, -(-int(retry_after_ms) // 1000))  # ceil to whole seconds
        log.info("rate_limit.exceeded", scope=scope, tenant_id=tenant_id, retry_after=retry_after)
        raise RateLimitExceeded(retry_after)
