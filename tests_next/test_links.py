import base64
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from fareflare.links import InvalidLink, ItineraryMessage, import_link


def change_token(url, change):
    params = parse_qs(urlsplit(url).query)
    message = ItineraryMessage()
    token = params["tfs"][0]
    message.ParseFromString(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    change(message)
    params["tfs"] = [base64.urlsafe_b64encode(message.SerializeToString()).decode().rstrip("=")]
    return "https://www.google.com/travel/flights?" + urlencode(params, doseq=True)


def test_real_user_link_decodes_without_explicit_trip_type(flight_url):
    target = import_link(flight_url)
    assert target["segments"] == [{"date": "2027-03-14", "legs": [{
        "origin": "DEN", "destination": "DFW", "date": "2027-03-14", "airline": "UA", "number": "414"}]}]
    assert (target["adults"], target["cabin"], target["currency"]) == (1, 1, "USD")
    assert import_link(target["url"])["id"] == target["id"]


def test_query_order_path_and_account_selection_do_not_change_target(flight_url):
    params = parse_qs(urlsplit(flight_url).query)
    reordered = "https://google.com/travel/flights/booking?" + urlencode(sorted(params.items(), reverse=True), doseq=True)
    assert import_link(flight_url)["id"] == import_link(reordered + "&authuser=2")["id"]


def test_unknown_query_and_protobuf_fields_are_preserved_conservatively(flight_url):
    assert import_link(flight_url)["id"] != import_link(flight_url + "&futureFareOption=1")["id"]
    params = parse_qs(urlsplit(flight_url).query)
    token = params["tfs"][0]
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    # Future varint field 100, value 1. It must survive parsing/serialization.
    raw += b"\xa0\x06\x01"
    params["tfs"] = [base64.urlsafe_b64encode(raw).decode().rstrip("=")]
    changed = "https://www.google.com/travel/flights?" + urlencode(params, doseq=True)
    target = import_link(changed)
    assert target["id"] != import_link(flight_url)["id"]
    assert import_link(target["url"])["id"] == target["id"]


@pytest.mark.parametrize("url", [
    "http://www.google.com/travel/flights?tfs=AA", "https://evil.example/travel/flights?tfs=AA",
    "https://google.com.evil.example/travel/flights?tfs=AA",
    "https://www.google.com@evil.example/travel/flights?tfs=AA",
    "https://user@www.google.com/travel/flights?tfs=AA",
    "https://www.google.com:123/travel/flights?tfs=AA",
    "https://www.google.com:bad/travel/flights?tfs=AA",
    "https://www.google.com\\@evil.example/travel/flights?tfs=AA",
    "https://www.google.com/travel/flights?tfs=AA\n",
    "https://www.google.com/travel/flights?tfs=AA#fragment",
    "https://www.google.com/url?q=https://evil.example",
    "https://www.google.com/travel/flights/s/abc",
    "https://www.google.com/travel/flights?q=DEN+DFW",
    "https://www.google.com/travel/flights?tfs=%%%%",
    "https://www.google.com/travel/flights?tfs=AAAA",
    "https://www.google.com/travel/flights?tfs=AA&tfs=BB", "", "x" * 8193,
])
def test_unsupported_or_hostile_links_fail_without_network(url):
    with pytest.raises(InvalidLink):
        import_link(url)


@pytest.mark.parametrize("mutation", [
    lambda m: m.segments[0].ClearField("legs"),
    lambda m: setattr(m.segments[0], "date", "not-a-date"),
    lambda m: setattr(m.segments[0].legs[0], "origin", "SEA"),
    lambda m: setattr(m.segments[0].legs[0], "number", ""),
    lambda m: setattr(m.segments[0].legs[0], "date", "2027-03-18"),
    lambda m: setattr(m, "cabin", 9), lambda m: setattr(m, "trip", 3),
    lambda m: m.passengers.append(2),
    lambda m: setattr(m, "currency", "EUR"),
])
def test_incomplete_or_unsupported_itinerary_is_rejected(flight_url, mutation):
    with pytest.raises(InvalidLink):
        import_link(change_token(flight_url, mutation))


def test_round_trip_requires_return_selection(flight_url):
    def add_return(m):
        m.trip = 1
        segment = m.segments.add(date="2027-03-21")
        segment.origins.add(kind=1, code="DFW")
        segment.destinations.add(kind=1, code="DEN")
        segment.legs.add(origin="DFW", destination="DEN", date="2027-03-21", airline="UA", number="415")
    target = import_link(change_token(flight_url, add_return))
    assert len(target["segments"]) == 2
    partial = change_token(target["url"], lambda m: m.segments[1].ClearField("legs"))
    with pytest.raises(InvalidLink):
        import_link(partial)
