---
paths:
  - "**/app/rate_limit.py"
  - "**/app/api/deps.py"
  - "**/app/api/main.py"
  - "**/.docker/nginx/**"
  - "**/.docker/docker-compose.yml"
---

# Rate limiting (app and edge)

Path-scoped: loads when a matching file is read. The general rules (`../CLAUDE.md`) and the
cross-cutting contracts (`CLAUDE.md` § Never, § The tenant boundary) still apply.

## Rate limiting

- **`limits` does the counting; `app/rate_limit.py` is the policy.** The library is battle-tested
  at the part that was never the problem here -- atomic counting in Redis. Which subject, which
  bucket, what happens when Redis dies, and what the client is told are all ours, because
  `limits` has no opinion about any of them and each one has cost a bug before. Was hand-rolled
  Lua until 2026-08-03; `docs/TECHNICAL_DECISIONS.md` has the full comparison and the numbers.
- **Import from `limits.aio`, never `limits.storage`/`limits.strategies`.** The synchronous
  modules are what `slowapi` imports (`extension.py:514` is a bare `self.limiter.hit(...)`), so
  every check there blocks the event loop -- 65.5 ms versus 18.5 ms at 200 concurrent checks.
  Use `implementation="redispy"` so it runs on the `redis[hiredis]>=8` already here: the
  `redis>3,<8.0.0` pin belongs to the *synchronous* `limits[redis]` extra only, and
  `limits[async-redis]` would add coredis for nothing.
- **`limits` fails CLOSED; `check` must keep failing open.** An unreachable Redis raises
  `redis.exceptions.ConnectionError` straight out of `hit()`. Both `hit` and `get_window_stats`
  sit inside one `try` -- narrowing it to just `hit` would 500 a caller whose budget was already
  spent. Two tests pin this, including the failure *between* the calls.
- **`remaining` is a second observation, not part of the decision** -- `hit()` returns a bool and
  the numbers come from `get_window_stats()` afterwards. Under concurrency it can disagree with
  what the next request is granted. That precision was real and is gone; it is the price of the
  swap, not an oversight, and the concurrency test says so where it used to assert distinct
  `remaining` values.
- **`MovingWindowRateLimiter`, never `SlidingWindowCounterRateLimiter`.** The counter shipped for
  one day and its failure is subtle enough to re-choose by accident: it **does not honour its own
  `Retry-After`**. On a 10-request/2-second budget it advertises `reset in 2.00s`, identical to the
  exact strategy, then grants **2 of 10** to a caller that waited 2.2 s, with the full budget back
  only at 4.2 s. It weights the previous window's count instead of expiring individual requests, so
  obeying the header is not enough and the natural client reaction is a tight retry loop. It also
  reports `X-RateLimit-Reset: 0` on the first request of a fresh window (`120 % 60 == 0` against a
  2x-window TTL), which needed a clamp that the exact strategy makes unnecessary. Two tests hold
  the line, both red in 5 of 5 mutation runs: the full-budget-returns test and the 1x-vs-2x TTL
  bound in the expiry test. `FixedWindowRateLimiter` is cheaper again and wrong for a different
  reason: a caller straddles the boundary and spends two budgets back to back. Byte-cost numbers
  are in `docs/TECHNICAL_DECISIONS.md` § Rate limiting, not repeated here.
- **Pass `max_connections`.** `limits` defaults it to 100 and its pool raises
  `MaxConnectionsError` rather than queueing, so the default turns burst load into 500s.
- **`X-RateLimit-*` goes on successes too, not just 429s**, or the budget is only discoverable
  by exceeding it. Set via the injected `response: Response` in `rate_limited`. When Redis is
  unreachable `check` returns None and **no headers are emitted** -- a fabricated full budget
  would report the guardrail as intact while it is absent.
- **Fails open**: unreachable Redis allows the request and logs a warning. A guardrail's
  outage must not become the API's outage. `docker-compose.yml` therefore has `api` wait on
  redis being healthy, so the gap isn't silently open at startup.
- The Redis client is cached **per event loop**, not per process -- a `redis.asyncio` client
  binds its pool to the creating loop, so a process-wide singleton breaks under repeated
  `asyncio.run()` (Streamlit, CLIs, per-test loops).
- `api/main.py`'s error handler must forward `exc.headers`; it overrides FastAPI's default,
  so dropping them silently strips `Retry-After` from every 429.
- **There are now TWO limiters, and they are keyed differently on purpose.** nginx does a per-IP
  flood shield (`limit_req`, two zones, added 2026-08-05); the app does per-API-key fairness. That
  is not the contradiction it looks like next to `TECHNICAL_DECISIONS.md` rejecting an IP key: nginx
  cannot see a *verified* key, and trusting `$http_x_api_key` at the edge would hand an attacker
  unlimited buckets by varying a header. Three things not to undo:
  - **Health must stay exempt.** `/health/live` and `/health/ready` are exempted by mapping their
    key to the empty string, which is the only mechanism available — there is no `limit_req off`.
    The container `HEALTHCHECK` hits readiness every 30s and `depends_on: service_healthy` gates the
    stack on it, so shedding a probe takes the container out of rotation to protect it. Verified by
    execution: 200 of 200 requests to `/health/ready` returned 200, where a limited path allowed 41.
  - **Never set an `EDGE_*` rate below the app's own budget.** The edge would 429 a caller who still
    had app budget while `X-RateLimit-Remaining` said otherwise — unreproducible from the client.
  - **The `limit_req` directives live at `server` level, not in `location /`.** A location that
    declares its own `limit_req` does not inherit the ones above it, so a location added later would
    be silently unlimited — the same inheritance trap `nginx.conf` documents for `add_header`, with
    a quieter failure.

  Behind a load balancer, `$binary_remote_addr` is the *immediate peer*, so every request shares one
  key and the zone becomes a global cap. `set_real_ip_from` is present but **commented out on
  purpose**: enabling it with a too-broad trust range is worse than no limiter, because a client can
  then spoof `X-Forwarded-For` and mint a bucket per request.
