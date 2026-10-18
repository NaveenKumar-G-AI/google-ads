from __future__ import annotations

import argparse
import os
from uuid import UUID

from recovery.internal_admin import PlatformOperatorRole


def main() -> None:
    parser=argparse.ArgumentParser(description="Grant/revoke a Recovery OS platform operator using the privileged migration DB role.")
    parser.add_argument("user_id")
    parser.add_argument("role",choices=[x.value for x in PlatformOperatorRole])
    parser.add_argument("--revoke",action="store_true")
    parser.add_argument("--reason",required=True)
    args=parser.parse_args()
    dsn=os.environ.get("RECOVERY_MIGRATION_DATABASE_URL","").strip()
    if not dsn:
        raise SystemExit("RECOVERY_MIGRATION_DATABASE_URL is required; never use the web API database role for operator bootstrap")
    if len(args.reason.strip())<8:
        raise SystemExit("reason must contain at least 8 characters")
    user_id=UUID(args.user_id)
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(dsn,row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM recovery.app_users WHERE id=%s",(user_id,))
        if cur.fetchone() is None:
            raise SystemExit("application user does not exist; the user must sign in once before platform access can be granted")
        cur.execute(
            "INSERT INTO recovery.platform_operator_events(user_id,operator_role,event_type,reason,actor) VALUES (%s,%s,%s,%s,%s)",
            (user_id,args.role,"revoked" if args.revoke else "granted",args.reason.strip(),"maintenance-cli"),
        )
    print(f"platform operator {'revoked' if args.revoke else 'granted'} for {user_id}")


if __name__=="__main__":
    main()
