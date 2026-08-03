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
    # **Twice** the window, not one -- measured at 119999 ms for a 60 s window. The sliding
    # counter has to keep the current window's count alive through the *following* window to
    # weight it as "previous", so retention is inherently 2x. The bound is what matters (it is
    # bounded at all); the factor is recorded so a future 2x -> 3x drift is visible rather than
    # being absorbed by a loose `< 1 hour`.
    assert ttl <= 2 * window * 1000


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


async def test_reset_is_never_zero_while_the_window_holds_a_request() -> None:
    """Pins the clamp in `_reset_seconds`, which exists to cover a `limits` boundary bug.

    Its counter is stored with a TTL of twice the window, and the reset is
    `current_expires_in % expiry` -- right inside the window, but `120 % 60 == 0` at the instant
    the window opens. So the *first* request against a fresh key was told
    `X-RateLimit-Reset: 0`, i.e. "retry immediately", while holding a spent budget.

    This is the first request against a brand-new scope, which is exactly that instant. Remove
    the clamp and it reports 0.
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


async def test_a_full_window_frees_a_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Where the sliding window actually slides: a client that waits is served.

    This is the one test that had to change shape rather than wording. The old version injected
    a fake clock and asserted the millisecond boundary, which worked because the trim was
    arithmetic *we* wrote (`ZREMRANGEBYSCORE key 0 (now - window)`, inclusive). `limits`'
    sliding-window counter rolls on **Redis key expiry** instead, so no clock we can patch moves
    it -- a time-injected version would pass with the window mechanism entirely broken, which is
    a test that proves the fake.

    So: a real one-second window, really waited out. That costs the suite ~1.2 s and proves one
    point on the line instead of the exact boundary. The boundary precision is genuinely gone,
    and `Retry-After` is now conservative rather than tight -- a refused caller may be told to
    wait slightly longer than needed, never shorter, which is the safe direction.
    """
    scope = _scope("window-slide")
    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: get_settings().model_copy(update={"rate_limit_window_seconds": 1}),
    )

    first = await rate_limit.check(scope, TENANT_A, limit=1)
    assert first is not None, "Redis must be reachable for this suite; a None here means it is not"

    with pytest.raises(rate_limit.RateLimitExceeded) as excinfo:
        await rate_limit.check(scope, TENANT_A, limit=1)
    assert excinfo.value.retry_after_seconds >= 1, "a 429 that says 'retry in 0s' is a tight loop"

    await asyncio.sleep(1.2)

    after = await rate_limit.check(scope, TENANT_A, limit=1)

    assert after is not None, "the window did not slide: a caller that waited was still refused"
    assert after.remaining == 0, "the slot was reused, not added to"
