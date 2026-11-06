"""Route observations retain actual selected flights through API and alert delivery."""
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fareflare.api import create_app
from fareflare.link_resolver import GoogleLinkResolver
from fareflare.links import InvalidLink, import_link
from fareflare.public_quotes import PageEvidence
from fareflare.search_quotes import SearchPageEvidence, verified_search_reading
from fareflare.service import MonitoringService


def test_route_price_history_and_alerts_keep_actual_offer(store, clock):
    fixture = json.loads((Path(__file__).parent / "fixtures/search_nonstop_oneway_usd.json").read_text())
    service = MonitoringService(store, lambda: clock[0], link_importer=GoogleLinkResolver(allow_search=True))
    key = "a" * 40
    with TestClient(create_app(service, {"alice": key})) as client:
        headers = {"Authorization": "Bearer " + key}
        response = client.post("/v1/monitors", headers={**headers, "Idempotency-Key": "create-search-route"},
                               json={"url": fixture["search"]["url"]})
        assert response.status_code == 202, response.text
        monitor = response.json()
        assert monitor["target"]["kind"] == "search"
        assert monitor["target"]["segments"][0]["legs"][0]["airline"] is None
        target = import_link(fixture["search"]["url"], allow_search=True)
        selected = import_link(fixture["booking"]["url"])
        reading = verified_search_reading(target, SearchPageEvidence(**fixture["search"]), selected,
                                          PageEvidence(**fixture["booking"]), clock[0])
        assert service.record(reading, "verified-search") is True
        assert service.record(reading, "verified-search") is False
        service.process_events()
        latest = client.get("/v1/monitors/" + monitor["id"], headers=headers).json()["latest"]
        offer = latest["observed_offer"]
        assert offer["segments"][0]["legs"][0]["number"] == "2550"
        assert offer["url"] == selected["url"]
        history = client.get("/v1/monitors/" + monitor["id"] + "/history", headers=headers).json()["items"]
        assert history[0]["observed_offer"] == offer
        alerts = client.get("/v1/alerts", headers=headers).json()["items"]
        assert alerts[0]["observation"]["observed_offer"] == offer
        delivery = store.get("delivery:" + alerts[0]["id"]).data
        assert delivery["itinerary"]["segments"][0]["legs"][0]["number"] == "2550"
        assert delivery["itinerary"]["url"] == selected["url"]


def test_search_requires_verified_offer_and_checks_itinerary_binding(store, clock):
    fixture = json.loads((Path(__file__).parent / "fixtures/search_nonstop_oneway_usd.json").read_text())
    service = MonitoringService(store, lambda: clock[0], link_importer=GoogleLinkResolver(allow_search=True))
    service.create_monitor("alice", fixture["search"]["url"], "search-failure-tests")
    target = import_link(fixture["search"]["url"], allow_search=True)
    selected = import_link(fixture["booking"]["url"])
    reading = verified_search_reading(target, SearchPageEvidence(**fixture["search"]), selected,
                                      PageEvidence(**fixture["booking"]), clock[0])
    for invalid in (replace(reading, observed_offer=None), replace(reading, evidence=None),
                    replace(reading, observed_offer=replace(reading.observed_offer, adults=2)),
                    replace(reading, observed_offer=replace(reading.observed_offer, target_id="a" * 64))):
        with pytest.raises(ValueError):
            service.record(invalid, "invalid-search")


def test_search_is_disabled_by_default(store, clock):
    fixture = json.loads((Path(__file__).parent / "fixtures/search_nonstop_oneway_usd.json").read_text())
    with pytest.raises(InvalidLink):
        MonitoringService(store, lambda: clock[0]).create_monitor("alice", fixture["search"]["url"], "disabled-search")
