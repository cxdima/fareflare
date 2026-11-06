"""Run the customer application locally and issue private, single-use invitations."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from fareflare.accounts import Accounts
from fareflare.product_config import ProductConfig
from fareflare.store import DynamoStore, SQLiteStore


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fareflare account and server tools")
    parser.add_argument("--database", type=Path, default=Path(".next/product.sqlite3"))
    parser.add_argument("--public-url", default=os.environ.get("FAREFLARE_PUBLIC_URL", "http://127.0.0.1:8001"))
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Serve the built dashboard, API and MCP on loopback")
    serve.add_argument("--port", type=int, default=8001)
    serve.add_argument("--static-dir", type=Path, default=Path("web/dist"))
    worker = sub.add_parser("worker", help="Collect a bounded batch and deliver verified customer alerts")
    worker.add_argument("--limit", type=int, choices=range(1, 21), default=5)
    worker.add_argument("--chrome-binary")
    worker.add_argument("--chromedriver")
    invite = sub.add_parser("invite", help="Write one invitation to a new private file")
    invite.add_argument("output", type=Path)
    invite.add_argument("--table", help="Explicit deployed product table; omit for local SQLite")
    invite.add_argument("--aws-account", help="Required account-ID guard when writing to AWS")
    invite.add_argument("--region", default="us-east-1")
    args = parser.parse_args(argv)
    config = replace(ProductConfig.from_env(), public_url=args.public_url.rstrip("/"))
    if args.command == "invite" and args.table:
        import boto3
        if not args.aws_account or boto3.client("sts", region_name=args.region).get_caller_identity()["Account"] != args.aws_account:
            raise ValueError("AWS account must match --aws-account before issuing a deployed invitation")
        store = DynamoStore(args.table, region=args.region)
    else:
        args.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        store = SQLiteStore(args.database)
    if args.command == "invite":
        # Open exclusively before consuming a database write; never replace an existing secret.
        args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            invitation = Accounts(store, config).create_invite()
            invitation["url"] = config.public_url + "/?invite=" + quote(invitation["token"], safe="")
            json.dump(invitation, output)
        print(f"Invitation written to {args.output}; expires in seven days.")
        return
    if args.command == "serve" and not (args.static_dir / "index.html").is_file():
        raise ValueError("Build the dashboard first: npm --prefix web ci && npm --prefix web run build")
    import uvicorn

    from fareflare.link_resolver import GoogleLinkResolver
    from fareflare.portal import create_portal
    from fareflare.public_quotes import supported_target
    from fareflare.service import MonitoringService
    service = MonitoringService(store, link_importer=GoogleLinkResolver(allow_search=config.search_enabled), capability_check=supported_target,
                                monitor_limit=config.monitor_limit, min_interval_seconds=config.min_interval_seconds,
                                global_target_limit=config.global_target_limit)
    if args.command == "worker":
        from fareflare.product_telegram import InboxSink
        from fareflare.public_browser import PublicGoogleFlightsProvider
        from fareflare.webhooks import RoutedSink
        from fareflare.worker import Worker
        sink = RoutedSink(service.webhooks, InboxSink(Accounts(store, config)))
        print(json.dumps(Worker(service, PublicGoogleFlightsProvider(args.chrome_binary, args.chromedriver), sink)
                         .tick(max_targets=args.limit)))
        return
    uvicorn.run(create_portal(service, config, static_dir=args.static_dir), host="127.0.0.1", port=args.port,
                access_log=False)


if __name__ == "__main__":
    main()
