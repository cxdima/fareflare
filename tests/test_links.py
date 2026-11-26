import base64
import json
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from fareflare.links import ItineraryMessage, import_link, itinerary_link, parameter_kind
from fareflare.public_quotes import collection_refusal
from fareflare.refusals import LinkRefused

FIXTURES = Path(__file__).parent / "fixtures"
SAFARI_CITY = FIXTURES / "selected_city_safari.json"


def change_token(url, change):
    params = parse_qs(urlsplit(url).query)
    message = ItineraryMessage()
    token = params["tfs"][0]
    message.ParseFromString(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    change(message)
    params["tfs"] = [base64.urlsafe_b64encode(message.SerializeToString()).decode().rstrip("=")]
    return "https://www.google.com/travel/flights?" + urlencode(params, doseq=True)


def refused(url, **options):
    with pytest.raises(LinkRefused) as caught:
        import_link(url, **options)
    return caught.value.check


def test_real_user_link_decodes_without_explicit_trip_type(flight_url):
    target = import_link(flight_url)
    assert target["segments"] == [
        {
            "date": "2027-03-14",
            "legs": [
                {
                    "origin": "DEN",
                    "destination": "DFW",
                    "date": "2027-03-14",
                    "airline": "UA",
                    "number": "414",
                }
            ],
        }
    ]
    assert (target["adults"], target["cabin"], target["currency"]) == (1, 1, "USD")
    assert import_link(target["url"]) == target


# Targets stored in production before link intake was split into facts and context.
# Their links carry no browser, tracking or view parameters, so they keep their ids.
STORED_IDS = {
    "public_booking_usd": "dc70a9ce724a3cd58b7b55b98737ef657b64cf3fd74ccb30bbc1ec81905f4b93",
    "selected_jpy": "912f9f9b0171acfa2bc72c695bd85e069a2312abcfb167fca9b1c20e894aabb8",
    "selected_roundtrip": "d35b177d021ea22b78176a4afa534f6e2ba633e909b0fcdf90f8ed32ee30e3a9",
    "selected_two_adults": "71bbb648af86237fc64c3c9bf0190dcb44dda0ecd6a1c24475c04535c9d4d29e",
}


@pytest.mark.parametrize("name", sorted(STORED_IDS))
def test_a_stored_target_keeps_its_identity(name):
    url = json.loads((FIXTURES / f"{name}.json").read_text())["page"]["url"]
    assert import_link(url)["id"] == STORED_IDS[name]


def test_a_flight_found_by_searching_a_city_in_safari_is_watchable():
    target = import_link(json.loads(SAFARI_CITY.read_text())["url"])
    assert target["segments"] == [
        {
            "date": "2027-01-10",
            "legs": [
                {
                    "origin": "DEN",
                    "destination": "DFW",
                    "date": "2027-01-10",
                    "airline": "UA",
                    "number": "414",
                }
            ],
        }
    ]
    assert (target["currency"], target["market"]) == ("USD", "US")
    # Safari's account index, browser name and booking session are left behind.
    assert sorted(target["provider_query"]) == ["curr", "gl", "hl", "tfs"]
    assert target["provider_query"]["hl"] == "en-US"
    assert collection_refusal(target) is None
    assert import_link(target["url"]) == target


def test_what_never_changes_a_price_is_left_out_of_the_target(flight_url):
    noisy = (
        flight_url.replace("hl=en-US", "hl=ru")
        + "&authuser=2&client=safari&sa=X&ved=0CAUQ2I8E&source=flre_fli_share"
        + "&utm_campaign=sharing&tfu=CmxDalJJYW5Ca01X"
    )
    assert import_link(noisy) == import_link(flight_url)
    assert {parameter_kind(name) for name in ("hl", "tfu", "client", "ved", "utm_x")} == {
        "language",
        "view",
        "browser",
        "tracking",
    }


def test_unknown_query_and_protobuf_fields_are_preserved_conservatively(flight_url):
    future = import_link(flight_url + "&futureFareOption=1")
    assert future["id"] != import_link(flight_url)["id"]
    assert future["provider_query"]["futureFareOption"] == "1"
    params = parse_qs(urlsplit(flight_url).query)
    token = params["tfs"][0]
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    # Future varint field 100, value 1. It must survive parsing/serialization.
    raw += b"\xa0\x06\x01"
    params["tfs"] = [base64.urlsafe_b64encode(raw).decode().rstrip("=")]
    changed = "https://www.google.com/travel/flights?" + urlencode(params, doseq=True)
    target = import_link(changed)
    assert target["id"] != import_link(flight_url)["id"]
    assert import_link(target["url"]) == target


def test_a_repeated_parameter_is_refused_only_when_it_is_kept(flight_url):
    assert import_link(flight_url + "&sa=X&sa=Y&hl=fr") == import_link(flight_url)
    assert refused(flight_url + "&gsas=2") == "repeated_parameter"
    assert refused(flight_url + "&curr=USD") == "repeated_parameter"


def test_the_country_and_currency_are_read_in_either_case(flight_url):
    lower = flight_url.replace("gl=US", "gl=us").replace("curr=USD", "curr=usd")
    assert import_link(lower) == import_link(flight_url)
    for country in ("u5", "usa", "", "ßß"):
        assert refused(flight_url.replace("gl=US", "gl=" + country)) == "codes"
    assert refused(flight_url.replace("curr=USD", "curr=U5D")) == "codes"


def test_google_on_another_country_domain_needs_a_stated_location(flight_url):
    german = flight_url.replace("www.google.com", "www.google.de")
    assert import_link(german) == import_link(flight_url)
    assert import_link(flight_url.replace("www.google.com", "www.google.co.uk")) == import_link(
        flight_url
    )
    # Without gl the page is for Germany, not the United States.
    assert refused(german.replace("&gl=US", "")) == "country"
    assert import_link(flight_url.replace("&gl=US", ""))["market"] == "US"


def _searched(origins, destinations):
    def change(message):
        segment = message.segments[0]
        for field, places in (("origins", origins), ("destinations", destinations)):
            segment.ClearField(field)
            for kind, code in places:
                getattr(segment, field).add(kind=kind, code=code)

    return change


@pytest.mark.parametrize(
    ("origins", "destinations"),
    [
        ([(1, "DEN")], [(2, "/m/0f2rq")]),  # Dallas, the city
        ([(1, "DEN")], [(3, "/m/0f2rq")]),  # the same place, as Google also marks it
        ([(2, "/m/02cl1")], [(1, "DFW")]),  # Denver, the city
        ([(1, "BOS"), (1, "DEN")], [(1, "DAL"), (1, "DFW")]),  # several airports
        ([(1, "BOS"), (2, "/g/11b6gq9ggb")], [(1, "DFW")]),  # airports and a city
    ],
)
def test_a_flight_has_one_identity_whatever_was_searched(flight_url, origins, destinations):
    target = import_link(change_token(flight_url, _searched(origins, destinations)))
    airports = import_link(flight_url)
    assert target["id"] == airports["id"]
    # The address keeps the search the person made; only the identity is shared.
    assert target["provider_query"]["tfs"] != airports["provider_query"]["tfs"]
    assert import_link(target["url"]) == target


@pytest.mark.parametrize(
    ("origins", "destinations"),
    [
        ([(1, "BOS")], [(1, "DFW")]),  # airports only, none of them the flight's
        ([(1, "DEN")], [(1, "DAL"), (1, "IAH")]),
        ([], [(1, "DFW")]),
        ([(2, "DEN")], [(1, "DFW")]),  # a place needs its Knowledge Graph id
        ([(3, "DEN")], [(1, "DFW")]),
        ([(1, "/m/02cl1")], [(1, "DFW")]),
        ([(2, "/m/02CL1")], [(1, "DFW")]),
        ([(4, "/m/02cl1")], [(1, "DFW")]),  # an unknown kind of place
        ([(0, "DEN")], [(1, "DFW")]),
    ],
)
def test_a_search_that_cannot_hold_the_flight_is_refused(flight_url, origins, destinations):
    assert refused(change_token(flight_url, _searched(origins, destinations))) == "searched_places"


def test_a_link_built_from_an_itinerary_selects_exactly_those_flights(flight_url):
    target = import_link(flight_url)
    rebuilt = import_link(
        itinerary_link(target["segments"], adults=2, cabin=3, currency="EUR"),
    )
    assert rebuilt["segments"] == target["segments"]
    assert (rebuilt["adults"], rebuilt["cabin"], rebuilt["currency"]) == (2, 3, "EUR")
    # Out and back, with a connection: a leg without a date flies on its segment's day.
    out = {
        "date": "2027-03-14",
        "legs": [
            {"origin": "DEN", "destination": "ORD", "airline": "UA", "number": "1"},
            {"origin": "ORD", "destination": "DFW", "airline": "UA", "number": "2"},
        ],
    }
    back = {
        "date": "2027-03-21",
        "legs": [{"origin": "DFW", "destination": "DEN", "airline": "UA", "number": "3"}],
    }
    both = import_link(itinerary_link([out, back]))
    assert [segment["date"] for segment in both["segments"]] == ["2027-03-14", "2027-03-21"]
    assert [
        [leg["airline"] + leg["number"] for leg in segment["legs"]] for segment in both["segments"]
    ] == [["UA1", "UA2"], ["UA3"]]
    assert all(leg["date"] == "2027-03-14" for leg in both["segments"][0]["legs"])
    assert (both["adults"], both["cabin"], both["currency"]) == (1, 1, "USD")
    assert collection_refusal(both) == "connections"


def test_query_order_and_path_do_not_change_target(flight_url):
    params = parse_qs(urlsplit(flight_url).query)
    reordered = "https://google.com/travel/flights/booking?" + urlencode(
        sorted(params.items(), reverse=True), doseq=True
    )
    assert import_link(flight_url) == import_link(reordered)


@pytest.mark.parametrize(
    ("url", "check"),
    [
        ("", "empty"),
        ("x" * 8193, "too_long"),
        ("https://www.google.com\\@evil.example/travel/flights?tfs=AA", "characters"),
        ("https://www.google.com/travel/flights?tfs=AA\n", "characters"),
        ("https://www.google.com:bad/travel/flights?tfs=AA", "malformed"),
        ("http://www.google.com/travel/flights?tfs=AA", "not_https"),
        ("hello", "not_https"),
        ("https://evil.example/travel/flights?tfs=AA", "not_google"),
        ("https://google.com.evil.example/travel/flights?tfs=AA", "not_google"),
        ("https://www.google.com@evil.example/travel/flights?tfs=AA", "not_google"),
        ("https://www.google.com:123/travel/flights?tfs=AA", "not_google"),
        ("https://user@www.google.com/travel/flights?tfs=AA", "credentials"),
        ("https://www.google.com/travel/flights?tfs=AA#fragment", "fragment"),
        ("https://www.google.com/travel/flights/s/abc", "shared_link"),
        ("https://www.google.com/url?q=https://evil.example", "not_flights_page"),
        ("https://www.google.com/travel/explore?tfs=AA", "not_flights_page"),
        ("https://www.google.evil/travel/flights?tfs=AA", "not_google"),
        ("https://www.google.com/travel/flights/deals", "flights_page"),
        ("https://www.google.com/travel/flights/saves?hl=en&gl=mx", "flights_page"),
        ("https://www.google.com/flights?hl=en#flt=DEN.DFW.2027-03-14", "flights_page"),
        ("https://www.google.com/travel/flights?q=DEN+DFW", "no_flights"),
        ("https://www.google.com/travel/flights", "no_flights"),
        ("https://www.google.com/travel/flights?tfs=%%%%", "token"),
        ("https://www.google.com/travel/flights?tfs=AAAA", "token_undecodable"),
        ("https://www.google.com/travel/flights?tfs=AA&tfs=BB", "repeated_parameter"),
        (
            "https://www.google.com/travel/flights?" + "&".join(f"p{n}=1" for n in range(41)),
            "query",
        ),
    ],
)
def test_unsupported_or_hostile_links_fail_without_network(url, check):
    assert refused(url) == check


def _add_return(origin="DFW", destination="DEN"):
    def change(message):
        message.trip = 1
        segment = message.segments.add(date="2027-03-21")
        segment.origins.add(kind=1, code=origin)
        segment.destinations.add(kind=1, code=destination)
        segment.legs.add(
            origin=origin, destination=destination, date="2027-03-21", airline="UA", number="415"
        )

    return change


def _connect(message):
    leg = message.segments[0].legs[0]
    second = message.segments[0].legs.add()
    second.CopyFrom(leg)
    second.origin, second.destination, second.number = "ORD", "DFW", "2"
    leg.destination = "ORD"


@pytest.mark.parametrize(
    ("mutation", "check"),
    [
        (lambda m: m.segments[0].ClearField("legs"), "no_flights"),
        (lambda m: setattr(m.segments[0], "date", "not-a-date"), "date"),
        (lambda m: setattr(m.segments[0], "date", "2027-02-30"), "date"),
        (lambda m: setattr(m.segments[0].legs[0], "origin", "SEA"), "searched_places"),
        (lambda m: setattr(m.segments[0].legs[0], "number", ""), "leg"),
        (lambda m: setattr(m.segments[0].legs[0], "airline", "ua"), "leg"),
        (lambda m: setattr(m.segments[0].legs[0], "date", "2027-03-18"), "leg_date"),
        (lambda m: setattr(m.segments[0].legs[0], "date", "someday"), "leg_date"),
        (lambda m: setattr(m, "cabin", 9), "cabin_missing"),
        (lambda m: setattr(m, "trip", 3), "multi_city"),
        (lambda m: setattr(m, "trip", 1), "segments"),
        (lambda m: setattr(m, "trip", 7), "segments"),
        (lambda m: m.passengers.append(2), "children"),
        (lambda m: m.ClearField("passengers"), "passengers_missing"),
        (lambda m: m.passengers.extend([1] * 9), "adults"),
        (lambda m: setattr(m, "currency", "EUR"), "currency_mismatch"),
        (
            lambda m: [m.segments[0].legs.add().CopyFrom(m.segments[0].legs[0]) for _ in range(4)],
            "too_many_legs",
        ),
        (
            lambda m: (_connect(m), setattr(m.segments[0].legs[1], "origin", "MDW")),
            "connection_mismatch",
        ),
        (_add_return("DFW", "ORD"), "open_jaw"),
    ],
)
def test_an_incomplete_or_unreadable_itinerary_names_its_fault(flight_url, mutation, check):
    assert refused(change_token(flight_url, mutation)) == check


def test_a_connection_imports_and_is_refused_by_the_collector(flight_url):
    target = import_link(change_token(flight_url, _connect))
    assert [leg["destination"] for leg in target["segments"][0]["legs"]] == ["ORD", "DFW"]
    assert collection_refusal(target) == "connections"


@pytest.mark.parametrize("position", ["origin", "segment date", "currency"])
def test_a_token_with_undecodable_text_is_refused_rather_than_crashing(flight_url, position):
    # A proto2 text field holding bytes that are not UTF-8 parses, but as bytes.
    token = parse_qs(urlsplit(flight_url).query)["tfs"][0]
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    marker = {"origin": b"DEN", "segment date": b"2027", "currency": b"USD"}[position]
    assert raw.count(marker) >= 1
    damaged = raw.replace(marker, b"\x80" + marker[1:], 1)
    url = flight_url.replace(token, base64.urlsafe_b64encode(damaged).decode().rstrip("="))
    assert refused(url) == "token_undecodable"


def test_round_trip_requires_return_selection(flight_url):
    target = import_link(change_token(flight_url, _add_return()))
    assert len(target["segments"]) == 2
    partial = change_token(target["url"], lambda m: m.segments[1].ClearField("legs"))
    assert refused(partial) == "return_missing"
    # With route searches on, a search for a round trip is outside what they cover.
    search = change_token(
        target["url"], lambda m: [segment.ClearField("legs") for segment in m.segments]
    )
    assert refused(search) == "no_flights"
    assert refused(search, allow_search=True) == "search_shape"
