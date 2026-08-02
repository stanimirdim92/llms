"""Key management UI: mint, list, and revoke keys for the tenant whose key is in the sidebar.

Calls `auth/management.py` in process, exactly as `Home.py` calls the ingestion pipeline in
process -- so the privilege-escalation guard, the tenant filter, and the show-once rule are the
*same code* the HTTP route enforces, not a UI-side reimplementation of them. That is the whole
reason those rules do not live in the router.

The one thing this page must never do is widen what the entered key can do. It resolves a
`Principal` rather than a tenant id, offers only the scopes that principal holds, and passes
the principal straight to `management.create_key`, which checks again. Two checks, because the
UI-side one is a courtesy (a disabled checkbox) and only the service-side one is a control.
"""

import asyncio
from datetime import UTC, datetime

import streamlit as st

from app.auth.expiry import DEFAULT_EXPIRY_DAYS, EXPIRY_CHOICES, NEVER
from app.auth.management import KeyManagementError, create_key, list_keys, revoke_key
from app.auth.models import ApiKey
from app.auth.scopes import ALL_SCOPES, KEYS_READ, KEYS_WRITE, granted
from app.auth.service import Principal, resolve_principal
from app.logs import configure_logging

configure_logging()

st.set_page_config(page_title="API keys", page_icon="🔑")
st.title("API keys")
st.caption("Mint, inspect, and revoke keys for your tenant. A key is shown once and never again.")

with st.sidebar:
    st.subheader("API key")
    st.caption("The key you authenticate *with*. Its scopes bound what you can mint.")
    api_key = st.text_input("Key", type="password", label_visibility="collapsed")

# Resolved on this page rather than read from `Home.py`'s session state, and deliberately so:
# Home stores a tenant id, and a tenant id is not enough to decide what may be granted. Sharing
# the widget key means the same key is already filled in when you arrive from Home.
principal: Principal | None = asyncio.run(resolve_principal(api_key)) if api_key else None

if principal is None:
    if api_key:
        st.error("Invalid, revoked, or expired key.")
    st.info("Enter an API key in the sidebar.")
    st.stop()

held = granted(principal.scopes)
st.success(f"Tenant `{principal.tenant_id[:8]}…` — you hold: {', '.join(sorted(held))}")


def _rows(keys: list[ApiKey]) -> list[dict[str, object]]:
    return [
        {
            "name": key.name,
            "key_id": key.id,
            "prefix": f"{key.prefix}…",
            "scopes": ", ".join(key.scopes) or "all",
            "state": _state(key),
            "expires": key.expires_at,
            "last used": key.last_used_at,
        }
        for key in keys
    ]


def _state(key: ApiKey) -> str:
    """One column answering "can this key authenticate right now, and if not why not".

    Revocation is reported ahead of expiry because it is the deliberate act: a key that was
    revoked *and* has since lapsed is still a revocation story.
    """
    if key.revoked_at:
        return "revoked"
    if key.expires_at and key.expires_at <= datetime.now(UTC):
        return "expired"
    return "active"


if KEYS_READ in held:
    st.subheader("Your keys")
    keys = asyncio.run(list_keys(principal.tenant_id))
    if not keys:
        st.caption("No keys yet.")
    else:
        # Revoked and expired keys are listed too -- the question people bring to this page is
        # usually about a key that stopped working.
        st.dataframe(_rows(keys), hide_index=True)
else:
    keys = []
    st.info("Your key lacks `keys:read`, so it cannot list keys.")

if KEYS_WRITE not in held:
    st.warning("Your key lacks `keys:write`, so it cannot mint or revoke keys.")
    st.stop()

st.subheader("Mint a key")
with st.form("mint"):
    name = st.text_input("Name", placeholder="ci", help="How you will recognise this key later.")
    # Only the scopes this principal holds are offered. The service checks again -- a disabled
    # option is a courtesy, not a control.
    chosen = st.multiselect(
        "Scopes",
        options=[scope for scope in ALL_SCOPES if scope in held],
        default=[scope for scope in ALL_SCOPES if scope in held],
        help="You cannot grant a scope your own key lacks.",
    )
    lifetime = st.selectbox(
        "Expires in",
        options=[*(str(days) for days in EXPIRY_CHOICES), NEVER],
        index=list(EXPIRY_CHOICES).index(DEFAULT_EXPIRY_DAYS),
        format_func=lambda choice: "never" if choice == NEVER else f"{choice} days",
    )
    submitted = st.form_submit_button("Mint", type="primary")

if submitted:
    if not name.strip():
        st.error("A key needs a name.")
    else:
        try:
            plaintext, record = asyncio.run(
                create_key(
                    principal,
                    name=name.strip(),
                    scopes=chosen,
                    expires_in_days=None if lifetime == NEVER else int(lifetime),
                )
            )
        except KeyManagementError as exc:
            # The same refusals the API returns as 400/403, surfaced rather than swallowed --
            # a UI that quietly drops an escalation attempt teaches the wrong thing about
            # what the key can do.
            st.error(str(exc))
        else:
            st.success(f"Created `{record.name}`. Copy it now — this is the only time it is shown.")
            st.code(plaintext, language=None)
            st.caption("Stored only as a SHA-512 hash. There is no endpoint that can show it again.")

if keys:
    st.subheader("Revoke a key")
    live = [key for key in keys if key.revoked_at is None]
    if not live:
        st.caption("Nothing left to revoke.")
    else:
        target = st.selectbox(
            "Key",
            options=[key.id for key in live],
            format_func=lambda key_id: next(f"{k.name} ({k.prefix}…)" for k in live if k.id == key_id),
        )
        st.caption(
            "Immediate and irreversible. Revoking the key you are using is allowed and will lock you "
            "out of this page — that is the right move for a key you believe is compromised."
        )
        if st.button("Revoke", type="secondary"):
            asyncio.run(revoke_key(principal.tenant_id, target))
            st.success("Revoked.")
            st.rerun()
