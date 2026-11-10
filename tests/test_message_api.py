"""HTTP, MCP and bot surfaces for message styles and the data behind them."""

import json
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

import fareflare
from fareflare.api import create_app
from fareflare.contracts import Reading
from fareflare.telegram_templates import PRESETS, TEMPLATE_KEYS
from fareflare.webhooks import WebhookSink
from tests.test_hosted_mcp import application, tool
from tests.test_telegram_bot import _call, _press, native_bot  # noqa: F401

KEY = "a" * 40
AUTH = {"Authorization": "Bearer " + KEY}
ROOT = Path(__file__).parents[1]


def observe(service, monitor, clock, amount, run):
    service.record(Reading(monitor["target_id"], amount, "USD", clock[0], "test-fixture"), run)
    service.process_events()
    clock[0] += 900


def test_catalog_requires_a_credential_and_lists_presets_and_placeholders(service):
    with TestClient(create_app(service, {"alice": KEY})) as client:
        assert client.get("/v1/preferences/telegram-templates").status_code == 401
        catalog = client.get("/v1/preferences/telegram-templates", headers=AUTH).json()
    assert [item["key"] for item in catalog["templates"]] == list(TEMPLATE_KEYS)
    assert catalog["presets"] == {style: dict(value) for style, value in PRESETS.items()}
    assert {"price_short", "change_summary", "link"} <= {
        item["name"] for item in catalog["placeholders"]["new_low"]
    }


def test_templates_round_trip_and_reject_mistakes_with_a_readable_reason(service, store):
    templates = {"new_low": "{emoji} **{price_short}**[ ({change_summary})]\n{route}"}
    with TestClient(create_app(service, {"alice": KEY})) as client:
        saved = client.put(
            "/v1/preferences",
            json={"telegram_style": "custom", "telegram_templates": templates},
            headers=AUTH,
        )
        assert saved.status_code == 200
        assert saved.json()["telegram_templates"] == templates
        assert client.get("/v1/preferences", headers=AUTH).json()["telegram_style"] == "custom"
        # Other settings are untouched by a later partial update.
        client.put("/v1/preferences", json={"diagnostics": True}, headers=AUTH)
        current = client.get("/v1/preferences", headers=AUTH).json()
        assert current["telegram_templates"] == templates and current["diagnostics"] is True

        rejected = client.put(
            "/v1/preferences",
            json={"telegram_templates": {"new_low": "{price.__class__}"}},
            headers=AUTH,
        )
        assert rejected.status_code == 422
        detail = rejected.json()["detail"]
        assert detail[0]["loc"][-1] == "telegram_templates"
        assert "New low: Unknown placeholder {price.__class__}" in detail[0]["msg"]
        assert client.get("/v1/preferences", headers=AUTH).json()["telegram_templates"] == templates


def test_preview_renders_each_message_with_unsaved_templates(service, store):
    before = store.get("tenant:alice")
    with TestClient(create_app(service, {"alice": KEY})) as client:
        url = "/v1/preferences/telegram-preview"
        classic = client.post(url, json={"telegram_style": "classic"}, headers=AUTH).json()
        assert classic["message"] == "new_low"
        assert "📉 New low!  $191  (was $199, −$8 · −4%)" in classic["text"]
        assert [button["text"] for button in classic["buttons"]] == []

        rebound = client.post(
            url + "?message=rebound", json={"telegram_style": "classic"}, headers=AUTH
        ).json()
        assert "📈 Rebounding  $211  (was at low $191, +$20)" in rebound["text"]

        listing = client.post(
            url + "?message=flight_list", json={"telegram_style": "classic"}, headers=AUTH
        ).json()
        assert listing["text"].startswith("Example flight list — sample data\n\n🛫 DEN → DFW")
        assert "🔥 at the low" in listing["text"] and listing["buttons"] == []

        custom = client.post(
            url + "?message=tracking_started",
            json={
                "telegram_style": "custom",
                "telegram_templates": {"tracking_started": "Watching {route} from {price}"},
            },
            headers=AUTH,
        ).json()
        assert custom["text"].endswith("Watching DEN → DFW from USD 191.00")

        assert client.post(url + "?message=unknown", json={}, headers=AUTH).status_code == 422
        broken = client.post(
            url, json={"telegram_templates": {"new_low": "[{price}"}}, headers=AUTH
        )
        assert broken.status_code == 422
    assert store.get("tenant:alice") == before  # A preview saves nothing.


def test_alerts_record_what_they_are_compared_with(service, flight_url, clock):
    monitor = service.create_monitor("alice", flight_url, "comparison-data")
    observe(service, monitor, clock, 50000, "first")
    observe(service, monitor, clock, 45000, "second")
    observe(service, monitor, clock, 47000, "third")
    observe(service, monitor, clock, 44000, "fourth")
    with TestClient(create_app(service, {"alice": KEY})) as client:
        alerts = client.get("/v1/alerts", headers=AUTH).json()["items"]
        view = client.get("/v1/monitors/" + monitor["id"], headers=AUTH).json()
    by_amount = {item["observation"]["amount_minor"]: item for item in alerts}
    assert by_amount[50000]["reason"] == "tracking_started"
    assert by_amount[50000]["previous"] == {"price_minor": None, "low_minor": None}
    assert by_amount[45000]["previous"] == {"price_minor": 50000, "low_minor": 50000}
    # The low is the monitor's own low, not merely the previous reading.
    assert by_amount[44000]["previous"] == {"price_minor": 47000, "low_minor": 45000}
    assert view["collection_failures"] == 0 and "rule_state" not in view


def test_webhook_body_of_an_alert_queued_by_an_older_release_is_unchanged(
    service, flight_url, clock
):
    sent = []

    class Transport:
        def send(self, url, payload, headers):
            sent.append(json.loads(payload))
            return True

    service.webhooks.transport = Transport()
    monitor = service.create_monitor("alice", flight_url, "legacy-body")
    endpoint = service.webhooks.register("alice", "https://hooks.example.com/prices", "legacy-hook")
    document = service.store.get("webhook:" + endpoint["id"])
    service.store.commit([document.update({**document.data, "status": "active"})])
    delivery = {
        "id": "b" * 64,
        "tenant": "alice",
        "monitor_id": monitor["id"],
        "reason": "new_low",
        "observation": {"amount_minor": 1, "currency": "USD", "observed_at": clock[0]},
        "itinerary": {"segments": []},
        "webhook_id": endpoint["id"],
        "webhook_generation": 1,
    }
    assert WebhookSink(service.webhooks).send(delivery)
    assert set(sent[0]["data"]) == {"monitor_id", "reason", "observation", "itinerary"}
    assert WebhookSink(service.webhooks).send(
        {**delivery, "previous": {"price_minor": 2, "low_minor": 2}}
    )
    assert sent[1]["data"]["previous"] == {"price_minor": 2, "low_minor": 2}


def test_mcp_can_read_and_set_message_templates(service):
    with TestClient(application(service)) as client:
        result = tool(
            client,
            "set_preferences",
            {
                "settings": {
                    "telegram_style": "custom",
                    "telegram_templates": {"rebound": "{emoji} {route} {price_short}"},
                    "telegram_show_buttons": False,
                }
            },
        )
        assert result["structuredContent"]["telegram_style"] == "custom"
        current = tool(client, "get_preferences")["structuredContent"]
        assert current["telegram_templates"] == {"rebound": "{emoji} {route} {price_short}"}
        assert current["telegram_show_buttons"] is False and current["diagnostics"] is False
        catalog = tool(client, "get_message_templates")["structuredContent"]
        assert catalog["limits"]["characters"] == 800 and "classic" in catalog["presets"]


def test_bot_flight_list_marks_the_low_and_style_menu_previews_the_choice(
    native_bot,  # noqa: F811
    service,
    flight_url,
    clock,
):
    _, tenant, _ = native_bot
    monitor = service.create_monitor(tenant, flight_url, "bot-classic-list")
    observe(service, monitor, clock, 26900, "first")
    observe(service, monitor, clock, 21400, "second")

    styles = _press(native_bot, _call(native_bot, "/settings"), "Message style")
    assert "✓ Detailed" in [
        button["text"] for row in styles.reply_markup["inline_keyboard"] for button in row
    ]
    classic = _press(native_bot, styles, "Classic with emoji")
    assert "Current style: Classic with emoji" in classic.text
    assert "📉 New low!  $191  (was $199, −$8 · −4%)" in classic.text
    assert "<b>New low!</b>" in classic.html

    listing = _call(native_bot, "/flights")
    assert "🛫 DEN → DFW  Mar 14, 2027" in listing.text
    assert "  • UA 414 · $214 🔥 at the low" in listing.text
    assert "<code>UA 414</code>" in listing.html and "<b>$214</b>" in listing.html

    observe(service, monitor, clock, 26900, "third")
    assert "  • UA 414 · $269 (low $214)" in _call(native_bot, "/flights").text
    detail = _press(native_bot, _call(native_bot, "/flights"), "DEN → DFW · Mar 14, 2027 · UA 414")
    assert "Lowest recorded: USD 214.00" in detail.text

    # The custom style is offered in chat only once templates exist.
    labels = [button["text"] for row in classic.reply_markup["inline_keyboard"] for button in row]
    assert "Custom" not in labels and "Write your own messages" in labels
    service.set_preferences(tenant, telegram_templates={"flight_row": "{flights} = {price_short}"})
    menu = _press(native_bot, _call(native_bot, "/settings"), "Message style")
    custom = _press(native_bot, menu, "Custom")
    assert "Current style: Custom" in custom.text
    assert "UA 414 = $269" in _call(native_bot, "/flights").text


def test_empty_flight_list_keeps_its_guidance(native_bot):  # noqa: F811
    listing = _call(native_bot, "/flights")
    assert "No flights yet. Paste a Google Flights link to start watching." in listing.text


def test_one_version_number_is_published_everywhere(service):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    web = json.loads((ROOT / "web" / "package.json").read_text())["version"]
    assert fareflare.__version__ == project == web
    with TestClient(create_app(service, {"alice": KEY})) as client:
        assert client.get("/openapi.json").json()["info"]["version"] == project


def test_flight_list_that_would_not_fit_one_message_uses_compact_rows(
    native_bot,  # noqa: F811
    service,
    flight_url,
    clock,
    monkeypatch,
):
    _, tenant, _ = native_bot
    monitor = service.create_monitor(tenant, flight_url, "long-custom-rows")
    observe(service, monitor, clock, 26900, "first")
    row = "\n".join(["{route} {flights} {price} padding"] * 12)
    service.set_preferences(tenant, telegram_style="custom", telegram_templates={"flight_row": row})
    assert _call(native_bot, "/flights").text.count("padding") == 12
    # With several such flights the list would exceed one message.
    monkeypatch.setattr("fareflare.telegram_bot._LIST_BUDGET", 200)
    listing = _call(native_bot, "/flights")
    assert "padding" not in listing.text
    assert "DEN → DFW · Mar 14, 2027 · UA 414 · USD 269.00" in listing.text
