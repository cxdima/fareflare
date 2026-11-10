"""Local command-line tools using explicit configuration."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from fareflare.links import import_link
from fareflare.service import MonitoringService, Reading
from fareflare.store import SQLiteStore


def load_local_config(path: Path) -> dict:
    config = json.loads(path.read_text())
    if config.get("mode") != "local":
        raise ValueError("This command requires a local configuration")
    return config


class ConsoleSink:
    def send(self, delivery: dict) -> bool:
        print(json.dumps({"simulation": True, "alert": delivery}))
        return True


def demo(fixture: Path) -> dict:
    """Run synthetic prices through the real durable pipeline in a temporary DB."""
    sample = json.loads(fixture.read_text())
    now = [int(time.time())]
    with tempfile.TemporaryDirectory(prefix="fareflare-demo-") as directory:
        path = Path(directory) / "demo.sqlite3"
        service = MonitoringService(SQLiteStore(path), lambda: now[0])
        first = service.create_monitor("traveler", sample["url"], "demo-traveler")
        second = service.create_monitor("developer", sample["url"], "demo-developer")
        target_id = first["target_id"]
        for index, amount in enumerate(sample["synthetic_prices_minor"]):
            service.record(
                Reading(target_id, amount, "USD", now[0], "synthetic-demo"), f"demo-{index}"
            )
            # Reopen between collection and delivery to prove state survives a restart.
            service = MonitoringService(SQLiteStore(path), lambda: now[0])
            service.process_events()
            service.deliver_due(ConsoleSink())
            now[0] += 900
        result = {
            "simulation": True,
            "unique_targets": len(service.store.query("targets")),
            "monitors": 2,
            "shared_target": target_id == second["target_id"],
            "observations": len(service.history("traveler", first["id"])),
            "delivered_alerts": sum(
                len(service.list_deliveries(tenant)) for tenant in ("traveler", "developer")
            ),
        }
        print(json.dumps(result))
        return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Isolated flight-monitor development tools")
    parser.add_argument("--config", type=Path, default=Path(".fareflare/config.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create local-only credentials without overwriting configuration")
    inspect = sub.add_parser("inspect", help="Decode a selected-itinerary URL offline")
    inspect.add_argument("url")
    serve = sub.add_parser("serve", help="Run the development API on loopback")
    serve.add_argument("--port", type=int, default=8001)
    sub.add_parser("mcp", help="Run a local stdio MCP client adapter for the API")
    worker = sub.add_parser(
        "worker", help="Run a bounded worker tick; notifications suppressed by default"
    )
    worker.add_argument("--limit", type=int, default=1, choices=range(1, 21))
    worker.add_argument(
        "--deliver-webhooks",
        action="store_true",
        help="Send queued alerts to customer-verified HTTPS webhooks",
    )
    sub.add_parser(
        "deliver-webhooks", help="Deliver queued webhook alerts without collecting prices"
    )
    issue = sub.add_parser(
        "key-create", help="Create a revocable credential in a private output file"
    )
    issue.add_argument("tenant")
    issue.add_argument("output", type=Path)
    revoke = sub.add_parser("key-revoke", help="Revoke one issued credential")
    revoke.add_argument("tenant")
    revoke.add_argument("identifier")
    replay = sub.add_parser(
        "demo", help="Replay explicitly synthetic prices without network access"
    )
    replay.add_argument("--fixture", type=Path, default=Path("examples/demo.json"))
    quote = sub.add_parser(
        "quote", help="Check a public selected-flight price in a fresh anonymous browser"
    )
    quote.add_argument("url", nargs="?", help="Defaults to the example itinerary when omitted")
    collect = sub.add_parser(
        "collect-once", help="Collect due local monitors once and queue alerts; no delivery"
    )
    collect.add_argument("--limit", type=int, choices=range(1, 21), default=5, metavar="1-20")
    for browser_command in (quote, collect, worker):
        browser_command.add_argument("--chrome-binary")
        browser_command.add_argument("--chromedriver")
    args = parser.parse_args(argv)
    if args.command == "init":
        args.config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(args.config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(
                {
                    "mode": "local",
                    "api_keys": {"developer": secrets.token_urlsafe(32)},
                    "database": str(args.config.parent / "monitors.sqlite3"),
                },
                output,
                indent=2,
            )
        print(f"Created {args.config}; service credentials are stored there, not printed.")
        return
    if args.command == "inspect":
        print(json.dumps(import_link(args.url), indent=2))
        return
    if args.command == "demo":
        demo(args.fixture)
        return
    if args.command == "quote":
        from fareflare.public_browser import PublicGoogleFlightsProvider
        from fareflare.public_quotes import QuoteUnavailable

        url = args.url or json.loads(Path("examples/demo.json").read_text())["url"]
        try:
            reading = PublicGoogleFlightsProvider(args.chrome_binary, args.chromedriver).collect(
                import_link(url)
            )
        except QuoteUnavailable as exc:
            print(json.dumps({"ok": False, "error": exc.code}))
            raise SystemExit(2) from None
        except ValueError:
            print(json.dumps({"ok": False, "error": "invalid_link"}))
            raise SystemExit(2) from None
        print(json.dumps({"ok": True, "observation": asdict(reading)}))
        return
    if args.command == "mcp":
        from fareflare.mcp_server import make_server

        # An account API key is sufficient on its own. The local development
        # configuration is only the fallback credential source.
        api_key = os.environ.get("FAREFLARE_API_KEY") or str(
            load_local_config(args.config)["api_keys"]["developer"]
        )
        make_server(os.environ.get("FAREFLARE_API_URL", "http://127.0.0.1:8001"), api_key).run()
        return
    config = load_local_config(args.config)
    service = MonitoringService(SQLiteStore(config["database"]))
    if args.command in ("key-create", "key-revoke"):
        from fareflare.credentials import Credentials

        credentials = Credentials(service.store)
        if args.command == "key-revoke":
            credentials.revoke(args.tenant, args.identifier)
        else:
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as output:
                identifier, key = credentials.issue(args.tenant)
                json.dump({"id": identifier, "api_key": key}, output)
            print(f"Credential written to {args.output}")
        return
    if args.command == "worker":
        from fareflare.public_browser import PublicGoogleFlightsProvider
        from fareflare.webhooks import RoutedSink
        from fareflare.worker import Worker

        sink = RoutedSink(service.webhooks) if args.deliver_webhooks else None
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
    if args.command == "deliver-webhooks":
        from fareflare.webhooks import RoutedSink

        service.process_events()
        print(json.dumps({"delivered": service.deliver_due(RoutedSink(service.webhooks))}))
        return
    if args.command == "collect-once":
        from fareflare.public_browser import PublicGoogleFlightsProvider

        result = service.collect_due(
            PublicGoogleFlightsProvider(args.chrome_binary, args.chromedriver), args.limit
        )
        result["events_processed"] = service.process_events()
        print(json.dumps(result))
        return
    if args.command == "serve":
        import uvicorn

        from fareflare.api import create_app
        from fareflare.credentials import Credentials, RateLimiter
        from fareflare.link_resolver import GoogleLinkResolver
        from fareflare.public_quotes import supported_target

        service = MonitoringService(
            service.store, link_importer=GoogleLinkResolver(), capability_check=supported_target
        )
        app = create_app(
            service,
            config["api_keys"],
            credentials=Credentials(service.store),
            limiter=RateLimiter(service.store),
        )
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
