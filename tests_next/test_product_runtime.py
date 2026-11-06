from fastapi.testclient import TestClient

from fareflare import product_runtime, runtime
from fareflare.accounts import Accounts
from fareflare.product_telegram import InboxSink
from fareflare.webhooks import RoutedSink


def test_application_composition_loads_product_limits_and_built_assets(store, tmp_path, monkeypatch):
    monkeypatch.setenv("FAREFLARE_PUBLIC_URL", "https://app.example.com")
    monkeypatch.setenv("FAREFLARE_TABLE", "fareflare-tests")
    monkeypatch.setenv("LAMBDA_TASK_ROOT", str(tmp_path))
    monkeypatch.delenv("FAREFLARE_CUSTOMER_TELEGRAM_SECRET_ARN", raising=False)
    monkeypatch.setattr(product_runtime, "DynamoStore", lambda *args, **kwargs: store)
    assets = tmp_path / "web" / "assets"
    assets.mkdir(parents=True)
    (tmp_path / "web" / "index.html").write_text("<!doctype html><title>Fareflare</title>")
    (assets / "app-deadbeef.js").write_text("void 0;")
    (tmp_path / "web" / "favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    app = product_runtime.build_application()
    with TestClient(app, base_url="https://app.example.com") as client:
        config = client.get("/v1/config").json()
        assert config["limits"]["monitors"] == 20 and config["billing_enabled"] is False
        assert client.get("/").status_code == 200
        assert client.get("/").headers["cache-control"] == "no-store"
        assert "immutable" in client.get("/assets/app-deadbeef.js").headers["cache-control"]
        assert client.get("/favicon.svg").status_code == 200
        assert client.get("/assets/../../.env").status_code == 404


def test_customer_worker_defaults_to_durable_inbox_without_a_bot_secret(store, monkeypatch):
    monkeypatch.setenv("FAREFLARE_TABLE", "fareflare-tests")
    monkeypatch.setenv("FAREFLARE_DELIVERY", "product")
    monkeypatch.delenv("FAREFLARE_CUSTOMER_TELEGRAM_SECRET_ARN", raising=False)
    monkeypatch.setattr(runtime, "DynamoStore", lambda *args, **kwargs: store)
    worker = runtime.build_worker()
    assert isinstance(worker.sink, RoutedSink)
    assert isinstance(worker.sink.default, InboxSink)
    accounts = Accounts(store)
    customer = accounts.register("alice", "a long integration test password", accounts.create_invite()["token"])
    assert worker.sink.send({"tenant": customer["account"]["id"]})
