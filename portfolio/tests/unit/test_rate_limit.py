"""Per-tenant rate limiting against a real Redis.

Skipped when no Redis is reachable, for the same reason the auth tests need real Postgres:
the limiter is a Lua script and a sorted-set expiry contract, and a fake would be asserting
that the fake behaves as written rather than that Redis does.
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
    """The reason the check is a Lua script rather than read-then-write: with a non-atomic
    implementation, concurrent callers all observe a count below the limit and all proceed.
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
    # Every grant reports a distinct `remaining`, counting down to zero. A duplicate would
    # mean two callers were told the same slot was theirs -- the read-then-write race, showing
    # up in the headers even where the count happened to come out right.
    assert sorted(b.remaining for b in granted) == list(range(limit))


async def test_window_expiry_is_set_so_buckets_do_not_leak() -> None:
    """Without PEXPIRE, every tenant/scope pair would leave a sorted set in Redis forever."""
    scope = _scope("expiry")
    await rate_limit.check(scope, TENANT_A, limit=1)

    ttl = await rate_limit._client().pttl(f"ratelimit:{scope}:{TENANT_A}")

    assert 0 < ttl <= get_settings().rate_limit_window_seconds * 1000


async def test_unreachable_redis_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rate limiter outage must not become an API outage -- see `check`'s docstring for
    the tradeoff this encodes.
    """

    class _Broken:
        async def eval(self, *_args: object, **_kwargs: object) -> object:
            msg = "connection refused"
            raise ConnectionError(msg)

    def _broken_client() -> _Broken:
        return _Broken()

    monkeypatch.setattr(rate_limit, "_client", _broken_client)

    await rate_limit.check(_scope("broken"), TENANT_A, limit=1)  # must not raise


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
    """The numbers behind `X-RateLimit-*`. Asserted here rather than only through HTTP because
    they come out of the Lua script, and an off-by-one in `limit - used - 1` is the kind of
    thing a client only notices as a 429 it thought it had budget for.
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
    # A full window from the first request, not from now: the window slides off the *oldest*
    # entry, so a client polling this must not see it creep forward with every call.
    assert 0 < third.reset_seconds <= window
    assert third.reset_seconds <= first.reset_seconds


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


async def test_the_window_boundary_is_inclusive_so_a_full_window_frees_a_slot() -> None:
    """Where the sliding window actually slides, asserted at the millisecond rather than by
    sleeping.

    The Lua trims with `ZREMRANGEBYSCORE key 0 (now - window)`, and that range is **inclusive**:
    a request exactly one window old falls out, so a client that waited the advertised
    `X-RateLimit-Reset` is granted its next request rather than being refused by one millisecond.
    An exclusive trim would make the header a lie in the least forgivable way -- a client that
    did exactly what it was told still gets a 429, and the natural fix (retry immediately) is a
    tight loop.

    Time is injected rather than slept: a real test of a 60-second window would take 60 seconds
    and still only prove one point on the line.
    """
    scope = _scope("boundary")
    window_ms = get_settings().rate_limit_window_seconds * 1000
    clock = [1_000_000_000.0]

    async def _check_at(offset_ms: int) -> rate_limit.Budget | None:
        clock[0] = 1_000_000_000.0 + offset_ms / 1000
        return await rate_limit.check(scope, TENANT_A, limit=1)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(rate_limit.time, "time", lambda: clock[0])

        await _check_at(0)  # spends the single slot

        with pytest.raises(rate_limit.RateLimitExceeded):
            await _check_at(window_ms - 1)  # one millisecond short of the window

        budget = await _check_at(window_ms)  # exactly one window later

    assert budget is not None, "Redis must be reachable for this suite; a None here means it is not"
    assert budget.remaining == 0, "the slot was reused, not added to"
