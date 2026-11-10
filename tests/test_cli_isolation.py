import json
import os
from pathlib import Path

import pytest

from fareflare.cli import demo, load_local_config, main

ROOT = Path(__file__).parents[1]


def test_local_init_creates_private_config_without_overwriting(tmp_path, capsys):
    config = tmp_path / "next" / "config.json"
    main(["--config", str(config), "init"])
    raw = config.read_text()
    data = load_local_config(config)
    assert len(data["api_keys"]["developer"]) >= 32
    assert data["api_keys"]["developer"] not in capsys.readouterr().out
    assert config.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        main(["--config", str(config), "init"])
    assert config.read_text() == raw


def test_configuration_cannot_enable_live_mode(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"mode":"production"}')
    with pytest.raises(ValueError):
        load_local_config(config)


def test_synthetic_demo_is_explicit_and_does_not_use_external_credentials(monkeypatch, capsys):
    monkeypatch.setenv("S3_BUCKET", "production-do-not-use")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "production-do-not-use")
    result = demo(ROOT / "examples" / "demo.json")
    assert result == {
        "simulation": True,
        "unique_targets": 1,
        "monitors": 2,
        "shared_target": True,
        "observations": 4,
        "delivered_alerts": 6,
    }
    assert "production-do-not-use" not in capsys.readouterr().out


def test_inspection_works_without_configuration(flight_url, tmp_path, capsys):
    main(["--config", str(tmp_path / "missing.json"), "inspect", flight_url])
    data = json.loads(capsys.readouterr().out)
    assert data["segments"][0]["legs"][0]["number"] == "414"


def test_cli_serve_and_mcp_only_use_next_configuration(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    main(["--config", str(config), "init"])
    called = []
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: called.append(kw))
    main(["--config", str(config), "serve", "--port", "8123"])
    assert called[0]["host"] == "127.0.0.1"
    assert called[0]["port"] == 8123
    from mcp.server.mcpserver import MCPServer

    monkeypatch.setattr(MCPServer, "run", lambda self: called.append("mcp"))
    monkeypatch.delenv("FAREFLARE_API_KEY", raising=False)
    monkeypatch.delenv("FAREFLARE_API_URL", raising=False)
    main(["--config", str(config), "mcp"])
    assert called[-1] == "mcp"
    assert (
        "TELEGRAM_BOT_TOKEN" not in os.environ
        or os.environ["TELEGRAM_BOT_TOKEN"] != "production-do-not-use"
    )


def test_quote_cli_returns_live_adapter_result_without_configuration(
    monkeypatch, flight_url, capsys
):
    from fareflare.public_browser import PublicGoogleFlightsProvider
    from fareflare.service import Reading

    monkeypatch.setattr(
        PublicGoogleFlightsProvider,
        "collect",
        lambda self, target: Reading(
            target["id"], 30900, "USD", 123, "test-browser", "Economy", "total"
        ),
    )
    main(["quote", flight_url])
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] and result["observation"]["fare_name"] == "Economy"


def test_quote_cli_reports_sanitized_failure(monkeypatch, flight_url, capsys):
    from fareflare.public_browser import PublicGoogleFlightsProvider
    from fareflare.public_quotes import QuoteUnavailable

    def unavailable(self, target):
        raise QuoteUnavailable("challenge")

    monkeypatch.setattr(PublicGoogleFlightsProvider, "collect", unavailable)
    with pytest.raises(SystemExit) as caught:
        main(["quote", flight_url])
    assert caught.value.code == 2
    assert json.loads(capsys.readouterr().out) == {"ok": False, "error": "challenge"}
    with pytest.raises(SystemExit):
        main(["quote", "https://example.com/"])
    assert json.loads(capsys.readouterr().out)["error"] == "invalid_link"


def test_collect_once_updates_local_monitors_but_never_delivers(
    tmp_path, monkeypatch, flight_url, capsys
):
    from fareflare.public_browser import PublicGoogleFlightsProvider
    from fareflare.service import MonitoringService, Reading
    from fareflare.store import SQLiteStore

    config = tmp_path / "config.json"
    main(["--config", str(config), "init"])
    capsys.readouterr()
    data = load_local_config(config)
    service = MonitoringService(SQLiteStore(data["database"]))
    monitor = service.create_monitor("developer", flight_url, "collect-test")
    monkeypatch.setattr(
        PublicGoogleFlightsProvider,
        "collect",
        lambda self, target: Reading(
            target["id"], 30900, "USD", int(service.clock()), "test-browser", "Economy", "total"
        ),
    )
    main(["--config", str(config), "collect-once", "--limit", "1"])
    result = json.loads(capsys.readouterr().out)
    assert result == {"collected": 1, "failed": 0, "skipped": 0, "events_processed": 1}
    assert service.get_monitor("developer", monitor["id"])["latest"]["amount_minor"] == 30900
    assert service.list_deliveries("developer")[0]["status"] == "pending"
