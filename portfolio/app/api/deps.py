"""Request-scoped dependencies. `current_tenant` is the API's authentication boundary.

A FastAPI dependency rather than middleware, deliberately -- the original plan called this
`api/middleware/auth.py`, but middleware is the wrong mechanism: it can't be overridden
per-route in tests, can't declare itself in the OpenAPI schema, and would have to
re-implement path matching to skip unauthenticated routes. A dependency gets all three for
free.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request, Response
from fastapi.security import APIKeyHeader

from app.auth.scopes import has_scope
from app.auth.service import Principal, resolve_principal
from app.config import get_settings
from app.exceptions import APIError
from app.rate_limit import RateLimitExceeded, check

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


_api_key_header = APIKeyHeader(
    name="x-api-key",
    scheme_name="ApiKeyAuth",
    description="A key from `scripts/create_tenant.py`. Format `pf_live_` + 49 characters.",
    # `auto_error=False` so a missing header returns None here instead of FastAPI raising its
    # own 403 with its own wording. Every failure mode has to reach the same 401 below --
    # with auto_error on, an absent key would be distinguishable from an invalid one by
    # status code alone, which is exactly the leak `resolve_tenant` is careful to avoid.
    auto_error=False,
)
"""Declares the scheme in OpenAPI rather than just accepting a header.

A plain `Header()` parameter authenticates identically but describes itself as an ordinary
input: no `securitySchemes` entry, no `security` requirement on each operation, and no
Authorize button in `/docs`. That difference is not cosmetic -- an OpenAPI generator turns a
security scheme into a client-level credential and a bare header into a parameter every call
site must remember to pass, and the Phase 6 React client is generated from this schema.
"""


async def current_principal(x_api_key: Annotated[str | None, Depends(_api_key_header)] = None) -> Principal:
    """The authenticated caller -- tenant, key, and scopes -- or 401.

    One message for every failure mode (absent, malformed, unknown, revoked, expired) so the
    response never reveals whether a key exists or once did.
    """
    principal = await resolve_principal(x_api_key)
    if principal is None:
        raise APIError("Missing or invalid API key", code=401)
    return principal


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


async def current_tenant(principal: CurrentPrincipal) -> str:
    """The authenticated tenant id.

    This return value is the sole input to retrieval scoping. Nothing from the request body
    or query string may reach `_build_filter` -- if a caller could supply the scope, it could
    read another tenant's documents, which is exactly the hole this closes.

    A separate dependency rather than routes reaching into `principal.tenant_id` themselves,
    for two reasons. Existing routes keep reading `tenant_id: CurrentTenant`, so adding
    scopes touched none of them. And it stays the seam the contract tests override -- there
    is one place to swap when authenticating a test, not one per route.
    """
    return principal.tenant_id


CurrentTenant = Annotated[str, Depends(current_tenant)]
"""Alias so routes read as `tenant_id: CurrentTenant` instead of repeating the Depends()."""


class require_scopes:
    """A dependency asserting the calling key holds every scope in `required`.

    Lowercase because every call site reads as a function call -- `Depends(require_scopes(ASK))`
    -- and it was one until the route table needed to be introspectable; see below.

    **403, not 404.** Everywhere else in this API an authorization failure is a 404, to avoid
    confirming that someone else's resource exists. This is the deliberate exception: the
    caller *is* authenticated and *is* entitled to the tenant, they simply hold the wrong
    capability. Hiding that produces a client that retries forever against a 404 it cannot
    fix, and there is nothing to leak -- naming the missing scope tells them only about their
    own key.

    Declared per route, like `CurrentTenant`, with the same consequence: a route that forgets
    it is reachable by any key. `tests/unit/test_scopes.py` asserts the mapping from route to
    required scope, because that is the assertion a new route silently falsifies.

    A callable class rather than a closure for exactly that test's benefit. FastAPI accepts
    either, but a closure hides its requirement in a cell object, so a route registered with
    no scope at all is indistinguishable from one that needs none when you walk the route
    table. `required_scopes` on the instance is what makes the mapping readable from outside.
    """

    def __init__(self, *required: str) -> None:
        self.required_scopes = required

    async def __call__(self, principal: CurrentPrincipal) -> Principal:
        missing = [scope for scope in self.required_scopes if not has_scope(principal.scopes, scope)]
        if missing:
            raise APIError(f"This API key lacks the required scope: {', '.join(missing)}", code=403)
        return principal


def rate_limited(scope: str, limit_name: str) -> Callable[[Principal, Request, Response], Awaitable[None]]:
    """A dependency enforcing the calling **key**'s budget for `scope`.

    Per key, not per tenant. Once keys differ in capability, a CI key hammering uploads should
    not be able to exhaust the budget of the dashboard key sitting next to it -- with one
    shared bucket, that is a support ticket about the wrong component.

    **The consequence, stated because it is real:** a tenant holding N keys now has N times
    the budget, so this is a fairness device between clients and not a cost ceiling. If it
    ever needs to be a ceiling, the fix is a second bucket keyed on `tenant_id` checked
    alongside this one -- two Redis round trips instead of one. Recorded in `docs/IDEAS.md`
    rather than built, because nothing here bills by request today.

    Depends on `current_principal`, so an unauthenticated request is rejected with 401 before
    any budget is consumed -- otherwise anonymous traffic could exhaust a key's limit, or
    worse, share one bucket keyed on nothing.

    FastAPI caches dependency results per request, so the key resolves once even though both
    this and the route handler ask for it -- the *principal* never needs stashing on
    `request.state` the way slowapi's `key_func(request)` signature would force. The budget
    headers do, but only so an error response can carry them; see below.

    `limit_name` is read from `Settings` at request time rather than captured at import, so
    limits stay configurable without the decorator freezing whatever value was loaded first.

    **`X-RateLimit-*` goes on every response, not just the 429.** Headers only on rejection
    make the limit undiscoverable: a client learns its budget by exceeding it, which is the
    one moment it wanted to avoid. `response: Response` is an injected sub-response whose
    headers FastAPI merges into the real one, which is the only way a *dependency* can set
    headers on a success -- returning them from the route would put the concern back in every
    handler.
    """

    async def _check(principal: CurrentPrincipal, request: Request, response: Response) -> None:
        limit = getattr(get_settings(), limit_name)
        try:
            budget = await check(scope, principal.key_id, limit)
        except RateLimitExceeded as exc:
            raise APIError(
                str(exc),
                code=429,
                headers={"Retry-After": str(exc.retry_after_seconds), **exc.budget.headers()},
            ) from exc
        if budget is not None:
            # Also stashed on `request.state` so `api/main.py`'s error handler can re-attach
            # them. Headers set on the injected sub-response are merged into the *route's*
            # response, and an `APIError` never produces one -- the handler builds a fresh
            # JSONResponse. Without this a 404 or a 422 silently drops the budget while the
            # 429 keeps it, so a client polling a status route learns its remaining quota
            # only on the requests that happened to succeed.
            request.state.ratelimit_headers = budget.headers()
            # None means Redis was unreachable and the request passed unchecked. Emitting
            # nothing is deliberate -- see `rate_limit.check`; a fabricated full budget would
            # report the guardrail as intact while it is absent.
            response.headers.update(budget.headers())

    return _check
