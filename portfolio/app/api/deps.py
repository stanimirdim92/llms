"""Request-scoped dependencies. `current_tenant` is the API's authentication boundary.

A FastAPI dependency rather than middleware, deliberately -- README's build sequence called
this `api/middleware/auth.py`, but middleware is the wrong mechanism: it can't be overridden
per-route in tests, can't declare itself in the OpenAPI schema, and would have to
re-implement path matching to skip unauthenticated routes. A dependency gets all three for
free.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header

from app.auth.service import resolve_tenant
from app.exceptions import APIError


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
