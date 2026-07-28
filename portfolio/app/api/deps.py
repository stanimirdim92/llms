"""Request-scoped dependencies. `current_tenant` is the API's authentication boundary.

A FastAPI dependency rather than middleware, deliberately -- README's build sequence called
this `api/middleware/auth.py`, but middleware is the wrong mechanism: it can't be overridden
per-route in tests, can't declare itself in the OpenAPI schema, and would have to
re-implement path matching to skip unauthenticated routes. A dependency gets all three for
free.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header

from app.auth.service import resolve_tenant
from app.config import get_settings
from app.exceptions import APIError
from app.rate_limit import RateLimitExceeded, check

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


async def current_tenant(x_api_key: Annotated[str | None, Header()] = None) -> str:
    """The authenticated tenant id, or 401.

    This return value is the sole input to retrieval scoping. Nothing from the request body
    or query string may reach `_build_filter` -- if a caller could supply the scope, it could
    read another tenant's documents, which is exactly the hole this closes.

    One message for every failure mode (absent, malformed, unknown, revoked) so the response
    never reveals whether a key exists or once did.
    """
    tenant_id = await resolve_tenant(x_api_key)
    if tenant_id is None:
        raise APIError("Missing or invalid API key", code=401)
    return tenant_id


CurrentTenant = Annotated[str, Depends(current_tenant)]
"""Alias so routes read as `tenant_id: CurrentTenant` instead of repeating the Depends()."""


def rate_limited(scope: str, limit_name: str) -> Callable[[str], Awaitable[None]]:
    """A dependency enforcing `tenant_id`'s budget for `scope`.

    Depends on `current_tenant`, so an unauthenticated request is rejected with 401 before
    any budget is consumed -- otherwise anonymous traffic could exhaust a tenant's limit, or
    worse, share one bucket keyed on nothing.

    FastAPI caches dependency results per request, so `current_tenant` resolves once even
    though both this and the route handler ask for it. That's why the tenant doesn't need
    stashing on `request.state` the way slowapi's `key_func(request)` signature would force.

    `limit_name` is read from `Settings` at request time rather than captured at import, so
    limits stay configurable without the decorator freezing whatever value was loaded first.
    """

    async def _check(tenant_id: CurrentTenant) -> None:
        limit = getattr(get_settings(), limit_name)
        try:
            await check(scope, tenant_id, limit)
        except RateLimitExceeded as exc:
            raise APIError(
                str(exc),
                code=429,
                headers={"Retry-After": str(exc.retry_after_seconds)},
            ) from exc

    return _check
