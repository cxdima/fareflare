"""Rules that must hold for every input, checked with generated cases.

The code under test reads text that nobody on the project wrote: templates typed
by an account, links pasted by a person and pages served by a third party.
"""

import base64
import json
import re
from datetime import date, timedelta
from html import unescape
from itertools import pairwise
from urllib.parse import parse_qsl, urlencode, urlsplit

from hypothesis import assume, given
from hypothesis import strategies as st

from fareflare.contracts import Reading, SliceTimes
from fareflare.links import ItineraryMessage, import_link, itinerary_link
from fareflare.message_templates import (
    DIRECTIONAL,
    MAX_PLACEHOLDERS,
    MAX_TEMPLATE_LENGTH,
    Run,
    TemplateError,
    normalize_template,
    parse_template,
    render,
)
from fareflare.preferences import Preferences, clock_time, in_quiet_hours
from fareflare.public_quotes import slice_times
from fareflare.refusals import CHECKS, LinkRefused
from fareflare.service import MonitoringService
from fareflare.telegram_templates import TEMPLATE_KEYS, VOCABULARY, validate_templates
from tests.conftest import EXAMPLE

NAMES = ("price", "route", "note")
VOCABULARY_ = frozenset(NAMES)
SPECIAL = "\\{}[]*_`"
# The only markup the engine may emit; everything else in the HTML must be escaped text.
TAG = re.compile(r'</?(?:b|i|code)>|<a href="[^"<>]*">|</a>')

printable = st.characters(
    exclude_categories=["Cs", "Cc"], exclude_characters=[*DIRECTIONAL, "\x7f"]
)


def quote(text):
    """Write text so the template engine reads every character literally."""
    return "".join("\\" + char if char in SPECIAL else char for char in text)


# --- Strategies -----------------------------------------------------------------------

# What a person fighting the syntax types: mostly markers, so nesting errors are reached.
syntax_soup = st.lists(
    st.sampled_from([*SPECIAL, " ", "\n", "\r", "a", "é", "🔥", "{price}", "{note}", "**", "__"]),
    max_size=60,
).map("".join)
field = st.sampled_from(NAMES).map(lambda name: ((name,), "{" + name + "}"))
literal = st.text(printable, max_size=8).map(lambda text: ((), quote(text)))


def combine(parts):
    """Each part is (placeholder names, template source); keep both when joining."""
    return tuple(name for names, _ in parts for name in names), "".join(s for _, s in parts)


def joined(parts):
    return st.lists(parts, max_size=4).map(combine)


def wrapped(marker, inner):
    return inner.map(lambda part: (part[0], marker + part[1] + marker))


atoms = joined(st.one_of(field, literal))
bold = wrapped("**", atoms)
italic = wrapped("__", joined(st.one_of(field, literal, bold)))
code = wrapped("`", atoms)
# The body of an optional group: at least one placeholder, emphasis closed inside it.
group_body = st.tuples(joined(st.one_of(literal, bold, italic, code)), field, atoms).map(combine)
group = group_body.map(lambda part: (part[0], "[" + part[1] + "]"))
line = joined(st.one_of(field, literal, bold, italic, code, group))
valid_template = (
    st.lists(line, min_size=1, max_size=5)
    .filter(lambda lines: sum(len(names) for names, _ in lines) <= MAX_PLACEHOLDERS)
    .map(lambda lines: "\n".join(source for _, source in lines))
    .filter(lambda source: len(source) <= MAX_TEMPLATE_LENGTH)
)

run = st.builds(
    Run,
    st.text(max_size=12),
    st.booleans(),
    st.booleans(),
    st.booleans(),
    st.none() | st.text(max_size=20),
)
value = st.text(max_size=20) | st.lists(run, max_size=3).map(tuple)
values = st.dictionaries(st.sampled_from(NAMES), value)


def has_value(item):
    text = item if isinstance(item, str) else "".join(part.text for part in item)
    return bool(text.strip())


# --- Templates ------------------------------------------------------------------------


@given(syntax_soup | st.text(max_size=200))
def test_any_text_is_a_template_or_a_reported_mistake(text):
    try:
        parse_template(text, VOCABULARY_)
    except TemplateError as error:
        assert str(error)
        return
    render(text, {}, VOCABULARY_)  # What is accepted can always be rendered.


@given(valid_template, values)
def test_rendered_html_carries_exactly_the_plain_text_and_only_known_markup(template, values):
    rendered = render(template, values, VOCABULARY_)
    remainder = TAG.sub("", rendered.html)
    # No value, however hostile, contributes a tag of its own.
    assert "<" not in remainder and ">" not in remainder
    assert unescape(remainder) == rendered.text
    open_tags = []
    for tag in TAG.findall(rendered.html):
        name = tag.strip("</>").split(" ")[0]
        if tag.startswith("</"):
            assert open_tags and open_tags.pop() == name
        else:
            assert "code" not in open_tags and (name != "code" or not open_tags)
            open_tags.append(name)
    assert not open_tags


@given(valid_template, values)
def test_rendered_text_is_tidy_and_reports_only_placeholders_that_showed(template, values):
    rendered = render(template, values, VOCABULARY_)
    lines = rendered.text.split("\n")
    assert all(line == line.rstrip() for line in lines)
    assert rendered.text == "" or (lines[0] and lines[-1])
    assert all(first or second for first, second in pairwise(lines))
    assert rendered.used <= {name for name, item in values.items() if has_value(item)}


@given(group_body, values)
def test_an_optional_group_is_all_or_nothing(body, values):
    names, source = body
    grouped = render("[" + source + "]", values, VOCABULARY_)
    if all(has_value(values.get(name, "")) for name in names):
        assert grouped == render(source, values, VOCABULARY_)
    else:
        assert grouped.text == grouped.html == "" and not grouped.used


@given(st.text(printable, max_size=60))
def test_every_character_can_be_written_literally(text):
    rendered = render(quote(text), {}, VOCABULARY_)
    assert rendered.text == text.rstrip()
    assert unescape(rendered.html) == rendered.text


@given(syntax_soup | st.text(max_size=200))
def test_normalizing_a_template_twice_changes_nothing_more(text):
    once = normalize_template(text)
    assert normalize_template(once) == once


@given(st.sampled_from(TEMPLATE_KEYS), valid_template | syntax_soup)
def test_a_stored_template_validates_to_itself(key, text):
    # Rename the generic placeholders to ones every Telegram template offers.
    text = text.replace("{note}", "{route}").replace("{price}", "{date}")
    try:
        stored = validate_templates({key: text})
    except TemplateError:
        assume(False)
    assert validate_templates(stored) == stored
    parse_template(stored[key], VOCABULARY[key])


# --- Links ----------------------------------------------------------------------------

_EXAMPLE_URL = json.loads(EXAMPLE.read_text())["url"]
_QUERY = dict(parse_qsl(urlsplit(_EXAMPLE_URL).query))
_TOKEN = base64.urlsafe_b64decode(_QUERY["tfs"] + "=" * (-len(_QUERY["tfs"]) % 4))


def _with_token(raw: bytes) -> str:
    token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return urlsplit(_EXAMPLE_URL)._replace(query=urlencode({**_QUERY, "tfs": token})).geturl()


@st.composite
def damaged_token(draw):
    """The example itinerary with a few bytes changed, removed or inserted."""
    raw = bytearray(_TOKEN)
    for _ in range(draw(st.integers(1, 4))):
        position = draw(st.integers(0, len(raw) - 1))
        action = draw(st.sampled_from(["digit", "change", "remove", "insert"]))
        if action == "digit":
            # Another date or flight number: the kind of change that still imports.
            digits = [index for index, byte in enumerate(raw) if 48 <= byte <= 57]
            raw[draw(st.sampled_from(digits))] = draw(st.integers(48, 57))
        elif action == "change":
            raw[position] = draw(st.integers(0, 255))
        elif action == "remove" and len(raw) > 1:
            del raw[position]
        else:
            raw.insert(position, draw(st.integers(0, 255)))
    return bytes(raw)


@given(st.one_of(damaged_token().map(_with_token), st.binary(max_size=80).map(_with_token)))
def test_a_link_is_refused_politely_or_imported_to_a_stable_itinerary(url):
    try:
        target = import_link(url)
    except LinkRefused as error:
        # Only a known check, never a crash or an unexplained refusal.
        assert error.check in CHECKS and str(error)
        return
    # Importing the canonical link again gives the same itinerary.
    again = import_link(target["url"])
    assert again == target


_IATA = st.text("ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=3, max_size=3)


@st.composite
def itineraries(draw):
    """A one-way or round trip of nonstop flights, as Google encodes a chosen itinerary."""
    origin, destination = draw(st.lists(_IATA, min_size=2, max_size=2, unique=True))
    out = draw(st.dates(min_value=date(2027, 1, 1), max_value=date(2027, 12, 1)))
    flight = st.builds(
        lambda airline, number: (airline, str(number)),
        st.sampled_from(["UA", "AA", "DL", "WN", "B6"]),
        st.integers(1, 9999),
    )
    directions = [(origin, destination, out)]
    if draw(st.booleans()):
        directions.append((destination, origin, out + timedelta(draw(st.integers(0, 30)))))
    segments = []
    for start, end, day in directions:
        airline, number = draw(flight)
        leg = {"origin": start, "destination": end, "airline": airline, "number": number}
        segments.append({"date": day.isoformat(), "legs": [leg]})
    return {
        "segments": segments,
        "adults": draw(st.integers(1, 9)),
        "cabin": draw(st.integers(1, 4)),
        "currency": draw(st.sampled_from(["USD", "JPY", "EUR"])),
    }


def _link(itinerary, **params):
    url = itinerary_link(
        itinerary["segments"],
        adults=itinerary["adults"],
        cabin=itinerary["cabin"],
        currency=itinerary["currency"],
    )
    return url + "".join(f"&{name}={value}" for name, value in params.items())


# Context that never changes a price, in the forms Google and browsers add it.
_CONTEXT = st.dictionaries(
    st.sampled_from(
        ["hl", "tfu", "authuser", "client", "biw", "sa", "ved", "source", "sxsrf", "utm_source"]
    ),
    st.text("abcdefXYZ0123456789-_", min_size=1, max_size=12),
    max_size=6,
)
_PLACE = st.one_of(
    st.just((2, "/m/0f2rq")), st.just((3, "/g/11b6gq9ggb")), st.tuples(st.just(1), _IATA)
)


def _search_from(url, segment_places):
    """The same link, as if the search had named other places."""
    params = dict(parse_qsl(urlsplit(url).query))
    message = ItineraryMessage()
    message.ParseFromString(
        base64.urlsafe_b64decode(params["tfs"] + "=" * (-len(params["tfs"]) % 4))
    )
    for segment, (origins, destinations) in zip(message.segments, segment_places, strict=False):
        legs = segment.legs
        for field, places, airport in (
            ("origins", origins, legs[0].origin),
            ("destinations", destinations, legs[-1].destination),
        ):
            segment.ClearField(field)
            # Places of unknown airports, beside the flight's own airport.
            for kind, code in [*places, (1, airport)]:
                getattr(segment, field).add(kind=kind, code=code)
    params["tfs"] = base64.urlsafe_b64encode(message.SerializeToString()).decode().rstrip("=")
    return "https://www.google.com/travel/flights?" + urlencode(params)


@given(
    itineraries(),
    _CONTEXT,
    st.lists(st.tuples(st.lists(_PLACE, max_size=2), st.lists(_PLACE, max_size=2)), max_size=2),
)
def test_a_flight_has_one_identity_however_its_link_was_found(itinerary, context, places):
    plain = import_link(_link(itinerary))
    # Importing a target's own address gives back exactly that target.
    assert import_link(plain["url"]) == plain
    found = import_link(_search_from(_link(itinerary, **context), places))
    assert found["id"] == plain["id"]
    assert import_link(found["url"]) == found


@given(itineraries(), st.data())
def test_every_price_defining_change_is_a_different_target(itinerary, data):
    plain = import_link(_link(itinerary))
    segments = json.loads(json.dumps(itinerary["segments"]))
    leg = segments[0]["legs"][0]
    change = data.draw(
        st.sampled_from(["number", "day", "adults", "cabin", "currency", "country", "unknown"])
    )
    changed = {**itinerary, "segments": segments}
    params = {}
    if change == "number":
        leg["number"] = str(int(leg["number"]) % 9999 + 1)
    elif change == "day":
        later = date.fromisoformat(segments[-1]["date"]) + timedelta(days=1)
        segments[-1]["date"] = later.isoformat()
        segments[-1]["legs"][0]["date"] = later.isoformat()
    elif change in ("adults", "cabin"):
        changed[change] = itinerary[change] % (9 if change == "adults" else 4) + 1
    elif change == "currency":
        changed["currency"] = "GBP"
    elif change == "country":
        params["gl"] = "CA"
    else:
        params["futureFareOption"] = data.draw(st.text("abc123", min_size=1, max_size=8))
    assert import_link(_link(changed, **params))["id"] != plain["id"]


@given(st.text(max_size=120))
def test_arbitrary_text_is_never_mistaken_for_a_link(text):
    try:
        import_link(text)
    except LinkRefused:
        return
    raise AssertionError("Random text was accepted as a Google Flights link")


# --- Flight times ---------------------------------------------------------------------

H12 = Preferences(hour_cycle="h12")
clock = st.builds(
    lambda hour, minute: f"{hour:02d}:{minute:02d}", st.integers(0, 23), st.integers(0, 59)
)


def _travel_time(minutes):
    hours, rest = divmod(minutes, 60)
    return " ".join(
        part for part in (f"{hours} hr" * bool(hours), f"{rest} min" * bool(rest)) if part
    )


@given(clock, clock, st.integers(0, 3), st.none() | st.integers(1, 24 * 60))
def test_a_direction_written_the_way_people_read_it_is_parsed_back_exactly(
    departs, arrives, offset, duration
):
    arrival = clock_time(arrives, H12) + (f"+{offset}" if offset else "")
    travel = f"Travel time: {_travel_time(duration)}\n" if duration else ""
    section = f"{clock_time(departs, H12)}Dallas\xa0(DFW)\n{travel}{arrival}Denver\xa0(DEN)"
    assert slice_times(section, "DFW", "DEN") == SliceTimes(departs, arrives, offset, duration)


noise = st.text(max_size=3) | st.sampled_from(
    ["+1", "+ 2", "Travel time: ", "2 hr", "16 min", "99 hr", "\xa0", "\n", " ", "Nonstop", "7"]
)
page_part = st.lists(
    st.one_of(clock.map(lambda value: clock_time(value, H12)), noise, noise), max_size=4
).map("".join)
# Both airports in order, with anything at all around and between them.
page_section = st.tuples(page_part, page_part, page_part).map(
    lambda parts: f"{parts[0]}(DFW){parts[1]}(DEN){parts[2]}"
)


@given(page_section | st.text(max_size=80))
def test_whatever_a_page_says_a_parsed_schedule_is_one_the_service_accepts(section):
    times = slice_times(section, "DFW", "DEN")
    if times is not None:
        reading = Reading("target", 100, "USD", 0, "generated", schedule=(times,))
        MonitoringService._verify_schedule({"segments": [{}]}, reading)


# --- Quiet hours ----------------------------------------------------------------------


@given(
    clock,
    clock,
    st.integers(0, 2_000_000_000),
    st.sampled_from([None, "America/Chicago", "Asia/Kolkata", "Europe/Kyiv", "Pacific/Chatham"]),
)
def test_a_window_and_its_reverse_split_every_day_between_them(start, end, moment, zone):
    assume(start != end)
    quiet = Preferences(quiet_hours=f"{start}-{end}", time_zone=zone)
    reverse = Preferences(quiet_hours=f"{end}-{start}", time_zone=zone)
    # Every moment is in exactly one of the two, in any time zone and across DST.
    assert in_quiet_hours(quiet, moment) != in_quiet_hours(reverse, moment)
