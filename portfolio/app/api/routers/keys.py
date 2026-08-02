"""Key management over HTTP.

Until now the only way to get a key was `scripts/create_tenant.py`, which needs database
access. That is right for bootstrapping the *first* key and wrong for everything after: a
tenant rotating its own credentials should not need a shell on the database host.

Thin on purpose. The rules that make key management safe -- a key may only grant scopes it
already holds, every lookup is filtered by `tenant_id`, the plaintext is returned exactly once
-- live in `auth/management.py`, because the Streamlit UI enforces the same rules in process
and a second copy of a privilege-escalation guard is one copy too many. What is left here is
the part that is genuinely about HTTP: which refusal is which status code.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import CurrentPrincipal, rate_limited, require_scopes
from app.api.schemas import ApiKeyResponse, CreatedKeyResponse, CreateKeyRequest
from app.auth import management
from app.auth.scopes import ALL_SCOPES, KEYS_READ, KEYS_WRITE
from app.exceptions import APIError

router = APIRouter()


def _to_response(api_key: management.ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        key_id=api_key.id,
        name=api_key.name,
        prefix=api_key.prefix,
        # `or ALL_SCOPES` for keys minted before the column existed: an empty stored list means
        # unrestricted, and a client should never have to know that.
        scopes=list(api_key.scopes) or list(ALL_SCOPES),
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
        last_used_at=api_key.last_used_at,
        revoked_at=api_key.revoked_at,
    )


@router.post(
    "/keys",
    status_code=201,
    tags=["keys"],
    summary="Mint a new API key for your own tenant",
    description="Returns the key **once**. It is stored only as a hash, so it cannot be shown again -- "
    "a lost key is revoked and replaced, never recovered.\n\n"
    "You may only grant scopes your own key already holds; requesting more returns 403. Omitting "
    "`scopes` copies your own, which for an unrestricted key means everything.",
    response_description="The new key's plaintext, shown once, plus its metadata",
    dependencies=[Depends(require_scopes(KEYS_WRITE)), Depends(rate_limited("keys", "rate_limit_keys"))],
)
async def create_key(request: CreateKeyRequest, principal: CurrentPrincipal) -> CreatedKeyResponse:
    try:
        key, record = await management.create_key(
            principal, name=request.name, scopes=request.scopes, expires_in_days=request.expires_in_days
        )
    except management.UnknownScopeError as exc:
        raise APIError(str(exc), code=400) from exc
    except management.ScopeEscalationError as exc:
        # 403, not 404: the caller is entitled to this tenant and merely lacks a capability,
        # so naming the scope tells them only about their own key.
        raise APIError(str(exc), code=403) from exc

    return CreatedKeyResponse(key=key, **_to_response(record).model_dump())


@router.get(
    "/keys",
    tags=["keys"],
    summary="List your tenant's API keys",
    description="Metadata only -- never the keys themselves. Revoked and expired keys are included, "
    "because the audit question is usually about a key that no longer works.",
    response_description="Every key belonging to the authenticated tenant, newest first",
    dependencies=[Depends(require_scopes(KEYS_READ)), Depends(rate_limited("keys", "rate_limit_keys"))],
)
async def list_keys(principal: CurrentPrincipal) -> list[ApiKeyResponse]:
    return [_to_response(key) for key in await management.list_keys(principal.tenant_id)]


@router.delete(
    "/keys/{key_id}",
    status_code=204,
    tags=["keys"],
    summary="Revoke one of your tenant's API keys",
    description="Revocation is immediate and irreversible. It records a timestamp rather than deleting "
    "the row, so the audit trail survives -- a deleted row cannot answer *was this leaked key ever "
    "used?*\n\nRevoking the key you are calling with is allowed, and locks you out. That is deliberate: "
    "it is the correct response to a key you believe is compromised, and refusing would make the one "
    "case that matters the one case unsupported.",
    dependencies=[Depends(require_scopes(KEYS_WRITE)), Depends(rate_limited("keys", "rate_limit_keys"))],
)
async def revoke_key(key_id: str, principal: CurrentPrincipal) -> None:
    try:
        await management.revoke_key(principal.tenant_id, key_id)
    except management.NoSuchKeyError as exc:
        # 404 for another tenant's key, not 403: distinguishing "not yours" from "does not
        # exist" would confirm that a given key id is real. Note this differs from the scope
        # failure above, which is 403 -- there the caller is entitled to the resource.
        raise APIError(str(exc), code=404) from exc
