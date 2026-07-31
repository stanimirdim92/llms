"""CLI: create a tenant and mint or revoke its API keys.

Until Phase 5 adds a registration UI, this is the only way to get a usable key.

    python scripts/create_tenant.py "Acme Corp"              # new tenant + first key
    python scripts/create_tenant.py --tenant <id> --name ci  # extra key for a tenant
    python scripts/create_tenant.py --list
    python scripts/create_tenant.py --revoke <key-id>
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import UTC, datetime

from sqlmodel import select

from app.auth.keys import display_prefix, generate_key, hash_key
from app.auth.models import ApiKey, Tenant
from app.db import get_session, init_db
from app.ids import new_id


async def _mint_key(tenant_id: str, name: str) -> str:
    """Create one key. The plaintext is returned to be printed once and then discarded --
    only its hash is stored, so it cannot be recovered later, only revoked and replaced.
    """
    key = generate_key()
    async with get_session() as session:
        session.add(
            ApiKey(
                id=new_id(),
                tenant_id=tenant_id,
                key_hash=hash_key(key),
                prefix=display_prefix(key),
                name=name,
            )
        )
        await session.commit()
    return key


async def create_tenant(tenant_name: str, key_name: str) -> None:
    tenant_id = new_id()
    async with get_session() as session:
        session.add(Tenant(id=tenant_id, name=tenant_name))
        await session.commit()

    key = await _mint_key(tenant_id, key_name)
    print(f"tenant   {tenant_id}  ({tenant_name})")
    print(f"key      {key}")
    print("\nStore the key now -- it is not recoverable. Send it as the x-api-key header.")


async def add_key(tenant_id: str, key_name: str) -> None:
    async with get_session() as session:
        if await session.get(Tenant, tenant_id) is None:
            print(f"no such tenant: {tenant_id}", file=sys.stderr)
            raise SystemExit(1)

    key = await _mint_key(tenant_id, key_name)
    print(f"key      {key}\n\nStore it now -- it is not recoverable.")


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
            state = f"revoked {key.revoked_at:%Y-%m-%d}" if key.revoked_at else "active"
            last_used = f"{key.last_used_at:%Y-%m-%d}" if key.last_used_at else "never"
            print(f"    {key.id}  {key.prefix}...  {key.name:<12} {state:<20} last used {last_used}")


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
    parser.add_argument("--list", action="store_true", help="List tenants and their keys")
    parser.add_argument("--revoke", metavar="KEY_ID", help="Revoke a key by its id")
    args = parser.parse_args()

    await init_db()

    if args.list:
        await list_all()
    elif args.revoke:
        await revoke(args.revoke)
    elif args.tenant:
        await add_key(args.tenant, args.name)
    elif args.tenant_name:
        await create_tenant(args.tenant_name, args.name)
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
