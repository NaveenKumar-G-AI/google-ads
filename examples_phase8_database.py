from __future__ import annotations

import argparse
import os
from uuid import UUID

from recovery.db import PostgresRecoveryRepository


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply Phase-8 PostgreSQL migrations and optionally initialize one tenant."
    )
    parser.add_argument("--migrate", action="store_true")
    parser.add_argument("--tenant-id", help="UUID for the tenant to create/verify")
    parser.add_argument("--tenant-slug")
    parser.add_argument("--tenant-name")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("Set DATABASE_URL in the environment. Do not put DB passwords in source code.")

    repo = PostgresRecoveryRepository(dsn)

    if args.migrate:
        applied = repo.apply_migrations()
        print("Applied migrations:", ", ".join(applied) if applied else "none (already current)")

    supplied = [args.tenant_id, args.tenant_slug, args.tenant_name]
    if any(supplied) and not all(supplied):
        raise SystemExit("--tenant-id, --tenant-slug and --tenant-name must be supplied together")
    if all(supplied):
        tenant_id = UUID(args.tenant_id)
        repo.ensure_tenant(
            tenant_id=tenant_id,
            slug=args.tenant_slug,
            display_name=args.tenant_name,
        )
        print(f"Tenant ready: {tenant_id}")


if __name__ == "__main__":
    main()
