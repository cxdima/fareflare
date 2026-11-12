"""Run the customer application and its worker locally."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

from fareflare.accounts import Accounts
from fareflare.mailer import FileMailer, mailer_from_env
from fareflare.passwords import breach_check_from_env
from fareflare.product_config import ProductConfig
from fareflare.store import SQLiteStore


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fareflare account and server tools")
    parser.add_argument("--database", type=Path, default=Path(".fareflare/product.sqlite3"))
    parser.add_argument(
        "--public-url", default=os.environ.get("FAREFLARE_PUBLIC_URL", "http://localhost:8001")
    )
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Serve the built dashboard, API and MCP on loopback")
    serve.add_argument("--port", type=int, default=8001)
    serve.add_argument("--static-dir", type=Path, default=Path("web/dist"))
    worker = sub.add_parser(
        "worker", help="Collect a bounded batch and deliver verified customer alerts"
    )
    worker.add_argument("--limit", type=int, choices=range(1, 21), default=5)
    worker.add_argument("--chrome-binary")
    worker.add_argument("--chromedriver")
    args = parser.parse_args(argv)
    config = replace(ProductConfig.from_env(), public_url=args.public_url.rstrip("/"))
    if config.public_url.startswith("http://localhost:"):
        # Passkeys need a domain name, so localhost is canonical and 127.0.0.1 redirects to it.
        config = replace(config, additional_hosts=(*config.additional_hosts, "127.0.0.1"))
    args.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    store = SQLiteStore(args.database)
    if args.command == "serve" and not (args.static_dir / "index.html").is_file():
        raise ValueError(
            "Build the dashboard first: npm --prefix web ci && npm --prefix web run build"
        )
    import uvicorn

    from fareflare.link_resolver import GoogleLinkResolver
    from fareflare.portal import create_portal
    from fareflare.public_quotes import supported_target
    from fareflare.service import MonitoringService

    service = MonitoringService(
        store,
        link_importer=GoogleLinkResolver(allow_search=config.search_enabled),
        capability_check=supported_target,
        monitor_limit=config.monitor_limit,
        min_interval_seconds=config.min_interval_seconds,
        global_target_limit=config.global_target_limit,
    )
    if args.command == "worker":
        from fareflare.product_telegram import InboxSink
        from fareflare.public_browser import PublicGoogleFlightsProvider
        from fareflare.webhooks import RoutedSink
        from fareflare.worker import Worker

        sink = RoutedSink(service.webhooks, InboxSink(Accounts(store, config)))
        print(
            json.dumps(
                Worker(
                    service,
                    PublicGoogleFlightsProvider(args.chrome_binary, args.chromedriver),
                    sink,
                ).tick(max_targets=args.limit)
            )
        )
        return
    # Without a configured provider, account email (resets and confirmations) is
    # written to private files in .fareflare/outbox so the links can be opened.
    mailer = mailer_from_env() or FileMailer(args.database.parent / "outbox")
    accounts = Accounts(store, config, mailer=mailer, breached=breach_check_from_env())
    uvicorn.run(
        create_portal(service, config, accounts, static_dir=args.static_dir),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
