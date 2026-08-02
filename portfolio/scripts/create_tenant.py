"""CLI: create a tenant and mint or revoke its API keys.

Until Phase 5 adds a registration UI, this is the only way to get a usable key.

    python scripts/create_tenant.py "Acme Corp"                    # new tenant + first key
    python scripts/create_tenant.py --tenant <id> --name ci        # extra key for a tenant
    python scripts/create_tenant.py --tenant <id> --expires-in 90  # key that lapses in 90 days
    python scripts/create_tenant.py --list
    python scripts/create_tenant.py --revoke <key-id>
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import UTC, datetime, timedelta

from sqlmodel import select

from app.auth.keys import display_prefix, generate_key, hash_key
from app.auth.models import ApiKey, Tenant
from app.db import get_session, init_db
from app.ids import new_id


async def _mint_key(tenant_id: str, name: str, expires_in_days: int | None) -> str:
    """Create one key. The plaintext is returned to be printed once and then discarded --
    only its hash is stored, so it cannot be recovered later, only revoked and replaced.
    """
    key = generate_key()
    expires_at = datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days else None
    async with get_session() as session:
        session.add(
            ApiKey(
                id=new_id(),
                tenant_id=tenant_id,
                key_hash=hash_key(key),
                prefix=display_prefix(key),
                name=name,
                expires_at=expires_at,
            )
        )
        await session.commit()
    return key


def _report_expiry(expires_in_days: int | None) -> None:
    """Say what was minted either way.

    A key with no deadline is a legitimate choice, not a mistake -- but it is the choice
    people make by omission rather than on purpose, so it gets said out loud. Silence here is
    how a credential handed to CI in 2026 is still live in 2030.
    """
    if expires_in_days:
        print(f"expires  in {expires_in_days} days")
    else:
        print("expires  never  (pass --expires-in DAYS to set a deadline)")


async def create_tenant(tenant_name: str, key_name: str, expires_in_days: int | None) -> None:
    tenant_id = new_id()
    async with get_session() as session:
        session.add(Tenant(id=tenant_id, name=tenant_name))
        await session.commit()

    key = await _mint_key(tenant_id, key_name, expires_in_days)
    print(f"tenant   {tenant_id}  ({tenant_name})")
    print(f"key      {key}")
    _report_expiry(expires_in_days)
    print("\nStore the key now -- it is not recoverable. Send it as the x-api-key header.")


async def add_key(tenant_id: str, key_name: str, expires_in_days: int | None) -> None:
    async with get_session() as session:
        if await session.get(Tenant, tenant_id) is None:
            print(f"no such tenant: {tenant_id}", file=sys.stderr)
            raise SystemExit(1)

    key = await _mint_key(tenant_id, key_name, expires_in_days)
    print(f"key      {key}")
    _report_expiry(expires_in_days)
    print("\nStore it now -- it is not recoverable.")


def _day(value: datetime | None) -> str:
    return f"{value:%Y-%m-%d}" if value else "never"


def _state(key: ApiKey) -> str:
    """One column answering "can this key authenticate right now, and if not why not".

    Order matters: revocation is reported ahead of expiry because it is the deliberate act.
    A key that was revoked *and* has since lapsed is still a revocation story.
    """
    if key.revoked_at:
        return f"revoked {_day(key.revoked_at)}"
    if key.expires_at is None:
        return "active"
    if key.expires_at <= datetime.now(UTC):
        return f"EXPIRED {_day(key.expires_at)}"
    return f"active until {_day(key.expires_at)}"


async def list_all() -> None:
    async with get_session() as session:
        tenants = (await session.exec(select(Tenant))).all()
        keys = (await session.exec(select(ApiKey))).all()

    if not tenants:
        print("no tenants yet")
        return
    for tenant in tenants:
        print(f"{tenant.id}  {tenant.name}")
        for key in (k for k in keys if k.tenant_id == tenant.id):
            print(f"    {key.id}  {key.prefix}...  {key.name:<12} {_state(key):<22} last used {_day(key.last_used_at)}")


async def revoke(key_id: str) -> None:
    async with get_session() as session:
        api_key = await session.get(ApiKey, key_id)
        if api_key is None:
            print(f"no such key: {key_id}", file=sys.stderr)
            raise SystemExit(1)
        if api_key.revoked_at is not None:
            print("already revoked")
            return
        api_key.revoked_at = datetime.now(UTC)
        session.add(api_key)
        await session.commit()
    print(f"revoked {key_id}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tenant_name", nargs="?", help="Name for a new tenant")
    parser.add_argument("--tenant", help="Existing tenant id to mint an additional key for")
    parser.add_argument("--name", default="default", help="Label for the key (default: 'default')")
    parser.add_argument(
        "--expires-in",
        type=int,
        metavar="DAYS",
        help="Days until the key stops working. Omit for a key that never expires.",
    )
    parser.add_argument("--list", action="store_true", help="List tenants and their keys")
    parser.add_argument("--revoke", metavar="KEY_ID", help="Revoke a key by its id")
    args = parser.parse_args()

    await init_db()

    if args.list:
        await list_all()
    elif args.revoke:
        await revoke(args.revoke)
    elif args.tenant:
        await add_key(args.tenant, args.name, args.expires_in)
    elif args.tenant_name:
        await create_tenant(args.tenant_name, args.name, args.expires_in)
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
