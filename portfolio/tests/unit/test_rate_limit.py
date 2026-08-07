"""Per-tenant rate limiting against a real Redis.

Skipped when no Redis is reachable, for the same reason the auth tests need real Postgres:
the counting happens in `limits`' Lua inside Redis, and a fake would be asserting that the fake
behaves as written rather than that Redis does.

These tests deliberately assert the **policy** -- which subject, which bucket, fail-open, and
the numbers a client is told -- and not `limits`' counting, which is `limits`' own suite's job.
The one exception is `test_concurrent_requests_cannot_exceed_the_budget`: atomicity is the whole
reason for using a library here, so it is worth one test of our own that we actually get it.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from starlette.requests import Request

from app import rate_limit
from app.api.main import portfolio_error_handler
from app.config import get_settings
from app.exceptions import APIError

TENANT_A = "a" * 32
TENANT_B = "b" * 32


async def _redis_reachable() -> bool:
    try:
        client = rate_limit._client()
        await client.ping()
    except Exception:  # noqa: BLE001 -- unreachable means skip, not fail
        return False
    return True


@pytest.fixture(autouse=True)
async def _redis() -> None:
    if not await _redis_reachable():
        pytest.skip("no Redis reachable -- start it with docker compose")


def _scope(name: str) -> str:
    """A unique scope per test, so runs stay independent without flushing a shared Redis
    (which would be hostile if someone points these at a Redis holding other data).
    """
    return f"test-{uuid.uuid4().hex}-{name}"


async def test_requests_within_the_budget_are_allowed() -> None:
    scope = _scope("within")

    for _ in range(3):
        await rate_limit.check(scope, TENANT_A, limit=3)


async def test_the_request_past_the_budget_is_refused() -> None:
    scope = _scope("over")
    for _ in range(3):
        await rate_limit.check(scope, TENANT_A, limit=3)

    with pytest.raises(rate_limit.RateLimitExceeded) as excinfo:
        await rate_limit.check(scope, TENANT_A, limit=3)

    assert excinfo.value.retry_after_seconds >= 1


async def test_the_budget_is_per_tenant_not_global() -> None:
    """The point of keying on tenant: one tenant exhausting its budget must not throttle
    everyone else, which is what an IP-keyed or global limiter would do here.
    """
    scope = _scope("per-tenant")
    for _ in range(3):
        await rate_limit.check(scope, TENANT_A, limit=3)

    with pytest.raises(rate_limit.RateLimitExceeded):
        await rate_limit.check(scope, TENANT_A, limit=3)

    await rate_limit.check(scope, TENANT_B, limit=3)  # unaffected


async def test_scopes_have_separate_budgets() -> None:
    """Exhausting uploads must not also block questions."""
    upload_scope, ask_scope = _scope("upload"), _scope("ask")
    await rate_limit.check(upload_scope, TENANT_A, limit=1)

    with pytest.raises(rate_limit.RateLimitExceeded):
        await rate_limit.check(upload_scope, TENANT_A, limit=1)

    await rate_limit.check(ask_scope, TENANT_A, limit=1)


async def test_concurrent_requests_cannot_exceed_the_budget() -> None:
    """Atomicity, which is the entire reason for using `limits` rather than a read-then-write
    of our own: with a non-atomic implementation, concurrent callers all observe a count below
    the limit and all proceed.

    Asserts the *count* only. An earlier version also asserted that the grants reported
    distinct `remaining` values counting down to zero, which held while one Lua call returned
    the decision and the numbers together. It cannot hold now: `hit()` decides, and
    `get_window_stats()` is a separate round trip afterwards, so 25 racing callers observe
    whatever the counter reached by the time each of them looked. Deleting that assertion is
    a real loss of precision in the headers under concurrency, not a test cleanup -- it is
    written down in `check`'s docstring and in `docs/TECHNICAL_DECISIONS.md`.
    """
    scope = _scope("concurrent")
    limit = 5
    attempts = 25

    results = await asyncio.gather(
        *(rate_limit.check(scope, TENANT_A, limit=limit) for _ in range(attempts)),
        return_exceptions=True,
    )
    granted = [r for r in results if isinstance(r, rate_limit.Budget)]

    assert len(granted) == limit, f"expected exactly {limit} to pass, {len(granted)} did"
    # The refusals must be refusals, not crashes: `check` swallows every exception to fail
    # open, so a bug there would show up as 25 grants or as 20 `None`s, never as an error.
    refused = [r for r in results if isinstance(r, rate_limit.RateLimitExceeded)]
    assert len(refused) == attempts - limit
    assert all(r.budget.remaining == 0 for r in refused)


async def test_window_expiry_is_set_so_buckets_do_not_leak() -> None:
    """Every counter must carry a TTL, or a bucket per key/scope pair stays in Redis forever.

    `limits` owns the key naming now, so this asserts against the key it actually writes --
    derived through the same `RateLimitItem` the limiter uses rather than a literal, because a
    hardcoded `ratelimit:{scope}:{subject}` is what this test used to check and it would now
    pass vacuously by reading a key nobody writes: `pttl` on a missing key returns -2, and an
    assertion of `0 < ttl` catches that, but only by accident.
    """
    scope = _scope("expiry")
    window = get_settings().rate_limit_window_seconds
    await rate_limit.check(scope, TENANT_A, limit=1)

    client = rate_limit._client()
    keys = [key async for key in client.scan_iter(f"*{scope}*")]

    # Found by scan rather than reconstructed. `prefixed_key(item.key_for(...))` gives
    # `LIMITS:LIMITER/...` while the key Redis actually holds is `LIMITS:{LIMITER/...}` --
    # brace-wrapped as a Cluster hash tag. Rebuilding it got `pttl == -2` for a key that was
    # written perfectly well, so the assertion below would have "caught" a leak that did not
    # exist and hidden a real one behind the same number.
    assert len(keys) == 1, f"expected one counter for {scope}, got {keys}"
    ttl = await client.pttl(keys[0])

    assert ttl > 0, f"no TTL on {keys[0]!r} (pttl={ttl}; -2 means the key does not exist)"
    # One window, measured at 59999 ms for a 60 s window. It was `2 *` for a day, under
    # `SlidingWindowCounterRateLimiter`, which has to keep the current window's count alive
    # through the *following* window to weight it as "previous". `MovingWindowRateLimiter` needs
    # no such thing. The tight bound is deliberate: `2 *` would still pass today and would stop
    # this test noticing a strategy change, which is exactly what it should notice.
    assert ttl <= window * 1000


async def test_unreachable_redis_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rate limiter outage must not become an API outage -- see `check`'s docstring for
    the tradeoff this encodes.

    This matters *more* since moving to `limits`, not less: `limits` fails **closed**. An
    unreachable Redis raises `redis.exceptions.ConnectionError` straight out of `hit()`, so
    without the `except` in `check` every request would 500 the moment Redis blinked. Patching
    the limiter rather than the client, because that is where the call now happens.
    """

    class _Broken:
        async def hit(self, *_args: object, **_kwargs: object) -> bool:
            msg = "connection refused"
            raise ConnectionError(msg)

        async def get_window_stats(self, *_args: object, **_kwargs: object) -> object:
            raise AssertionError("must not be reached: hit() failed first")

    monkeypatch.setattr(rate_limit, "_limiter", _Broken)

    assert await rate_limit.check(_scope("broken"), TENANT_A, limit=1) is None


async def test_a_failure_between_the_two_calls_also_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """The window `hit`-then-`get_window_stats` opened.

    `hit` succeeding and `get_window_stats` failing is the case a narrower `try` would miss:
    the request has already been counted, so raising here would 500 a caller whose budget was
    spent -- the worst of both. Both calls are inside one `try` for this reason, and this test
    is what stops someone tightening it.
    """

    class _HalfBroken:
        async def hit(self, *_args: object, **_kwargs: object) -> bool:
            return True

        async def get_window_stats(self, *_args: object, **_kwargs: object) -> object:
            msg = "connection reset mid-check"
            raise ConnectionError(msg)

    monkeypatch.setattr(rate_limit, "_limiter", _HalfBroken)

    assert await rate_limit.check(_scope("half-broken"), TENANT_A, limit=1) is None


async def test_error_handler_forwards_retry_after() -> None:
    """A 429 must say *how long* to wait.

    Exercises the handler, not just the exception: `api/main.py` overrides FastAPI's default
    `HTTPException` handler, which makes it solely responsible for forwarding headers. It
    originally didn't, and the omission was invisible -- the response was still a valid 429,
    just one that told clients to back off without saying for how long.

    A real `Request` built from a minimal ASGI scope rather than a stub, so this exercises
    the handler's actual signature instead of a shape that merely resembles it.
    """
    request = Request({"type": "http", "method": "POST", "path": "/v1/documents", "headers": []})
    exceeded = APIError("slow down", code=429, headers={"Retry-After": "42"})

    response = await portfolio_error_handler(request, exceeded)

    assert response.status_code == 429
    assert response.headers["retry-after"] == "42"


async def test_the_budget_reports_what_is_left_and_when_it_resets() -> None:
    """The numbers behind `X-RateLimit-*`. Asserted here rather than only through HTTP because a
    client only notices an off-by-one as a 429 it thought it had budget for.
    """
    scope = _scope("budget")
    window = get_settings().rate_limit_window_seconds

    first = await rate_limit.check(scope, TENANT_A, limit=3)
    second = await rate_limit.check(scope, TENANT_A, limit=3)
    third = await rate_limit.check(scope, TENANT_A, limit=3)

    assert first is not None
    assert second is not None
    assert third is not None
    assert [first.remaining, second.remaining, third.remaining] == [2, 1, 0]
    assert all(budget.limit == 3 for budget in (first, second, third))
    # Every one of them within the window and never zero. The old assertion here was
    # `third.reset_seconds <= first.reset_seconds` -- a monotonic countdown, which held when the
    # window slid off the oldest ZSET entry. It cannot be asserted now: all three land in the
    # same one-second bucket of the same window, so the comparison would pass on equality and
    # prove nothing, and `limits` derives the value by modulo rather than by counting down.
    assert all(0 < budget.reset_seconds <= window for budget in (first, second, third))


async def test_a_fresh_window_advertises_a_full_window_not_zero() -> None:
    """Guards the *strategy choice*, which is why it survived the clamp it was written for.

    `SlidingWindowCounterRateLimiter` stores its counter with a TTL of twice the window and
    derives the reset as `current_expires_in % expiry` -- right inside the window, but
    `120 % 60 == 0` at the instant one opens. So under that strategy the **first** request
    against a fresh key was told `X-RateLimit-Reset: 0`: retry immediately, with a budget
    already spent. It needed a clamp in `_reset_seconds`, and this test was written to pin it.

    `MovingWindowRateLimiter` expires individual entries rather than whole windows and reports a
    full window here, so the clamp is gone and this test kept the behaviour.

    **It is a hint, not the guard.** Measured against the counter it is red in only 8 of 10 runs:
    the modulo lands on zero only when the first hit falls within a millisecond of the window
    opening, so it is timing-dependent by nature. `test_window_expiry_is_set_so_buckets_do_not_leak`
    and `test_the_full_budget_returns_after_the_advertised_reset` were red in 5 of 5 -- those are
    what actually stop the strategy regressing.
    """
    budget = await rate_limit.check(_scope("fresh-window"), TENANT_A, limit=5)

    assert budget is not None
    assert budget.reset_seconds > 0, "a fresh window advertised 'resets now' with a request counted"
    assert budget.reset_seconds == get_settings().rate_limit_window_seconds


async def test_a_refusal_carries_the_budget_too() -> None:
    """So the 429 can advertise `remaining: 0` alongside `Retry-After` rather than leaving a
    client to infer it.
    """
    scope = _scope("refused-budget")
    await rate_limit.check(scope, TENANT_A, limit=1)

    with pytest.raises(rate_limit.RateLimitExceeded) as excinfo:
        await rate_limit.check(scope, TENANT_A, limit=1)

    budget = excinfo.value.budget
    assert budget.remaining == 0
    assert budget.limit == 1
    assert budget.headers()["X-RateLimit-Remaining"] == "0"


async def test_reset_is_a_delta_not_an_epoch_timestamp() -> None:
    """Pinned because the header name is ambiguous -- GitHub's `X-RateLimit-Reset` is epoch
    seconds. A delta needs no agreement between the client's clock and ours, and switching to
    epoch silently would make every client's backoff calculation absurd rather than wrong by a
    little.
    """
    scope = _scope("reset-delta")
    budget = await rate_limit.check(scope, TENANT_A, limit=1)

    assert budget is not None
    assert budget.reset_seconds <= get_settings().rate_limit_window_seconds


async def test_the_full_budget_returns_after_the_advertised_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """A client that waits exactly as long as we told it must get its **whole** budget back.

    This is the most valuable test in the file, because a strategy that fails it looks completely
    fine everywhere else. `SlidingWindowCounterRateLimiter` was in use for one day and fails it
    badly: on a 10-request/2-second budget it advertises `reset in 2.00s` -- identical to what the
    exact strategy advertises -- and then grants **2 of 10** to a caller that waited 2.2 s, with
    the full budget not back until 4.2 s. It weights the previous window's count instead of
    expiring individual requests, so obeying the header is not enough, and the natural client
    reaction to "I waited and still got a 429" is a tight retry loop. `MovingWindowRateLimiter`
    grants 10 of 10.

    Asserting the *whole* budget rather than one slot is the point: a single slot comes back under
    the counter too, which is why the earlier version of this test passed while the strategy was
    wrong. It used `limit=1`, so "some budget returned" and "all budget returned" were the same
    assertion, and the bug had nowhere to show.

    Time is real here. The window boundary lives inside `limits` now, so injecting a clock would
    move nothing and the test would pass with the mechanism entirely broken.
    """
    scope = _scope("full-budget-returns")
    limit = 4
    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: get_settings().model_copy(update={"rate_limit_window_seconds": 1}),
    )

    for _ in range(limit):
        assert await rate_limit.check(scope, TENANT_A, limit=limit) is not None

    with pytest.raises(rate_limit.RateLimitExceeded) as excinfo:
        await rate_limit.check(scope, TENANT_A, limit=limit)
    told_to_wait = excinfo.value.retry_after_seconds
    assert told_to_wait >= 1, "a 429 that says 'retry in 0s' is a tight loop"

    await asyncio.sleep(told_to_wait + 0.2)

    granted = 0
    for _ in range(limit):
        try:
            if await rate_limit.check(scope, TENANT_A, limit=limit) is not None:
                granted += 1
        except rate_limit.RateLimitExceeded:
            pass

    assert granted == limit, (
        f"waited the advertised {told_to_wait}s and only {granted}/{limit} were granted -- "
        "the strategy does not honour its own Retry-After"
    )
