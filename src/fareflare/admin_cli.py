"""Make, unmake and recover admins. The admin panel cannot do any of this.

Running it needs the database's own credentials: AWS access to the DynamoDB table
for a deployed service, or the SQLite file for a local one. That is what keeps the
admin role out of reach of anyone who only has a browser.

    python -m fareflare.admin_cli --table gfpt-next-production bootstrap admin@fareflare.dev
    python -m fareflare.admin_cli --database .fareflare/product.sqlite3 list
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

from fareflare.accounts import Accounts
from fareflare.product_config import ProductConfig
from fareflare.store import DynamoStore, SQLiteStore, Store


def _store(args: argparse.Namespace) -> Store:
    if args.table:
        return DynamoStore(args.table, region=args.region)
    return SQLiteStore(args.database)


def _when(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%d %H:%M UTC")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fareflare admin access")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--table", help="DynamoDB table of a deployed service")
    where.add_argument("--database", type=Path, default=Path(".fareflare/product.sqlite3"))
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap = sub.add_parser(
        "bootstrap", help="Create an admin that must choose a password at first sign-in"
    )
    bootstrap.add_argument("email")
    bootstrap.add_argument(
        "--temporary-password", help="The first password; a random one is printed if omitted"
    )
    bootstrap.add_argument("--minutes", type=int, default=30, choices=range(5, 1441))
    bootstrap.add_argument(
        "--reclaim",
        action="store_true",
        help="Take over an existing account at this address, removing its credentials",
    )
    grant = sub.add_parser("grant", help="Make an existing account an admin")
    grant.add_argument("email")
    revoke = sub.add_parser("revoke", help="Remove the admin role from an account")
    revoke.add_argument("email")
    reset = sub.add_parser(
        "reset-password", help="Give an account a temporary password to replace at sign-in"
    )
    reset.add_argument("email")
    reset.add_argument("--temporary-password")
    reset.add_argument("--minutes", type=int, default=30, choices=range(5, 1441))
    sub.add_parser("list", help="List admins")
    args = parser.parse_args(argv)

    accounts = Accounts(_store(args), ProductConfig())
    try:
        if args.command == "bootstrap":
            password = args.temporary_password or secrets.token_urlsafe(9)
            result = accounts.create_admin(
                args.email, password, args.minutes * 60, reclaim=args.reclaim
            )
            verb = "Reclaimed" if result["reclaimed"] else "Created"
            print(f"{verb} admin {result['account']['email']} ({result['account']['id']}).")
            if not args.temporary_password:
                print(f"Temporary password: {password}")
            print(
                f"Sign in before {_when(result['expires_at'])}. You will choose a new password,"
                " then set up two-step sign-in or a passkey to open the admin panel."
            )
        elif args.command in ("grant", "revoke"):
            account = accounts.set_admin(args.email, args.command == "grant")
            state = "is now an admin" if account["admin"] else "is no longer an admin"
            print(f"{account['email'] or account['username']} {state}.")
        elif args.command == "reset-password":
            password = args.temporary_password or secrets.token_urlsafe(9)
            result = accounts.set_temporary_password_by_name(
                args.email, password, args.minutes * 60
            )
            if not args.temporary_password:
                print(f"Temporary password: {password}")
            print(f"Every browser was signed out. Sign in before {_when(result['expires_at'])}.")
        else:
            print(json.dumps(accounts.admins(), indent=2))
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
