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
from tests.test_telegram_bot import _call, _labels, _press, native_bot  # noqa: F401

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
    # What a settings page needs to offer the styles and only the switches each one uses.
    assert catalog["default_style"] == "compact"
    assert {style["value"]: style["switches"] for style in catalog["styles"]} == {
        "compact": ["telegram_show_flight_numbers", "telegram_show_times"],
        "detailed": [
            "telegram_show_flight_numbers",
            "telegram_show_times",
            "telegram_show_observed_time",
            "telegram_show_fare",
        ],
        "custom": [],
    }
    assert {item["group"] for item in catalog["placeholders"]["flight_row"]} == {
        "Price",
        "Trip",
        "Flight",
        "Times",
        "More",
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
        compact = client.post(url, json={}, headers=AUTH).json()
        assert compact["message"] == "new_low"
        assert compact["text"].split("\n") == [
            "🔥 New low · $191 (was $199)",
            "DEN → DFW · Mar 14 · UA 414",
            "3:50 PM → 6:54 PM",
        ]
        # The same message as styled lines, so a page can draw it without parsing markup.
        assert compact["lines"][0] == [
            {"text": "🔥 ", "bold": False, "italic": False, "code": False, "link": False},
            {"text": "New low", "bold": True, "italic": False, "code": False, "link": False},
            {"text": " · ", "bold": False, "italic": False, "code": False, "link": False},
            {"text": "$191", "bold": True, "italic": False, "code": False, "link": False},
            {"text": " ", "bold": False, "italic": False, "code": False, "link": False},
            {"text": "(was $199)", "bold": False, "italic": True, "code": False, "link": False},
        ]
        assert (
            "\n".join("".join(run["text"] for run in line) for line in compact["lines"])
            == (compact["text"])
        )
        assert [button["text"] for button in compact["buttons"]] == ["View flight"]

        detailed = client.post(url, json={"telegram_style": "detailed"}, headers=AUTH).json()
        assert detailed["text"].split("\n")[0] == "🔥 New low · $191 (was $199, −$8 · −4%)"
        assert detailed["text"].split("\n")[3] == "United · Economy · Total for 1 adult"

        rebound = client.post(url + "?message=rebound", json={}, headers=AUTH).json()
        assert rebound["text"].startswith("📈 Price rose · $211 (low $191)\n")

        listing = client.post(url + "?message=flight_list", json={}, headers=AUTH).json()
        assert listing["text"].startswith("🛫 DEN → DFW · Mar 14\n• UA 1565 7:05→10:02 AM · $214")
        assert "🔥 at the low" in listing["text"] and listing["buttons"] == []
        assert listing["lines"][1][1] == {
            "text": "UA 1565",
            "bold": False,
            "italic": False,
            "code": True,
            "link": False,
        }

        custom = client.post(
            url + "?message=tracking_started",
            json={
                "telegram_style": "custom",
                "telegram_templates": {"tracking_started": "Watching {route} from {price} {link}"},
            },
            headers=AUTH,
        ).json()
        assert custom["text"] == "Watching DEN → DFW from USD 191.00 Open in Google Flights"
        assert custom["lines"][0][-1]["link"] is True and custom["buttons"] == []
        # No address ever reaches the page as a link target; it only learns that text is linked.
        assert "google.com" not in str(custom["lines"])

        assert client.post(url + "?message=unknown", json={}, headers=AUTH).status_code == 422
        assert client.post(url, json={"telegram_style": "classic"}, headers=AUTH).status_code == 422
        broken = client.post(
            url, json={"telegram_templates": {"new_low": "[{price}"}}, headers=AUTH
        )
        assert broken.status_code == 422
    assert store.get("tenant:alice") == before  # A preview saves nothing.


def test_a_style_saved_before_it_was_removed_reads_as_the_default(service, store):
    service.set_preferences("alice", telegram_show_buttons=False)
    document = store.get("tenant:alice")
    saved = {**document.data["preferences"], "telegram_style": "classic"}
    store.commit([document.update({**document.data, "preferences": saved})])
    with TestClient(create_app(service, {"alice": KEY})) as client:
        current = client.get("/v1/preferences", headers=AUTH).json()
        assert current["telegram_style"] == "compact" and current["telegram_show_buttons"] is False
        # Saving anything else afterwards works, and stores a style that exists.
        assert client.put("/v1/preferences", json={"muted": True}, headers=AUTH).status_code == 200
    assert store.get("tenant:alice").data["preferences"]["telegram_style"] == "compact"


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
        assert catalog["limits"]["characters"] == 800 and "compact" in catalog["presets"]


def test_bot_flight_list_marks_the_low_and_style_menu_previews_the_choice(
    native_bot,  # noqa: F811
    service,
    flight_url,
    clock,
):
    _, tenant, _ = native_bot
    monitor = service.create_monitor(tenant, flight_url, "bot-compact-list")
    observe(service, monitor, clock, 26900, "first")
    observe(service, monitor, clock, 21400, "second")

    styles = _press(native_bot, _call(native_bot, "/settings"), "Message style")
    assert "✓ Compact" in _labels(styles)
    assert "🔥 New low · $191 (was $199)" in styles.text
    assert "🔥 <b>New low</b> · <b>$191</b> <i>(was $199)</i>" in styles.html
    detailed = _press(native_bot, styles, "Detailed")
    assert "Detailed: an example with sample data." in detailed.text
    assert "🔥 New low · $191 (was $199, −$8 · −4%)" in detailed.text
    compact = _press(native_bot, detailed, "Compact")

    listing = _call(native_bot, "/flights")
    assert listing.text.split("\n")[:4] == [
        "Your flights (1)",
        "",
        "🛫 DEN → DFW · Mar 14",
        "• UA 414 · $214 🔥 at the low",
    ]
    assert "<code>UA 414</code>" in listing.html and "<b>$214</b>" in listing.html
    assert "USD" not in listing.text

    observe(service, monitor, clock, 26900, "third")
    assert "• UA 414 · $269 (low $214)" in _call(native_bot, "/flights").text
    detail = _press(native_bot, _call(native_bot, "/flights"), "Manage this flight")
    assert "\n$269 (low $214)\n" in detail.text and "<b>$269</b> (low $214)" in detail.html

    # The custom style is offered in chat only once templates exist.
    assert "Custom" not in _labels(compact) and "Write your own messages" in _labels(compact)
    service.set_preferences(tenant, telegram_templates={"flight_row": "{flights} = {price_short}"})
    menu = _press(native_bot, _call(native_bot, "/settings"), "Message style")
    custom = _press(native_bot, menu, "Custom")
    assert "✓ Custom" in _labels(custom)
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


def test_long_custom_rows_are_paged_and_an_unusable_one_gives_way_to_the_default_list(
    native_bot,  # noqa: F811
    service,
    flight_url,
    clock,
):
    _, tenant, _ = native_bot
    for index in range(12):
        monitor = service.create_monitor(tenant, flight_url, f"long-custom-rows-{index}")
    observe(service, monitor, clock, 26900, "first")
    row = "\n".join(["{route} {flights} {price_short} padding"] * 12)
    service.set_preferences(tenant, telegram_style="custom", telegram_templates={"flight_row": row})
    # Twelve rows of twelve lines are more than one message holds, so the list is paged.
    listing = _call(native_bot, "/flights")
    shown = listing.text.count("padding") // 12
    assert 1 < shown < 12 and f"Flights 1–{shown} of 12" in listing.text
    following = _press(native_bot, listing, "Next flights")
    assert f"Flights {shown + 1}–" in following.text and "padding" in following.text
    # A single row longer than a page allows is not cut short: the default list is used.
    service.set_preferences(tenant, telegram_templates={"flight_row": "{flights} " + "pad " * 190})
    listing = _call(native_bot, "/flights")
    assert "pad" not in listing.text
    assert "🛫 DEN → DFW · Mar 14\n• UA 414 · $269 🔥 at the low" in listing.text
