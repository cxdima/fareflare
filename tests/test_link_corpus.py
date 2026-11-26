"""Real links people shared, each with its reviewed outcome.

A change to how links are read shows up here as a list of links whose outcome moved.
"""

import json
from pathlib import Path

import pytest

from fareflare.links import import_link
from fareflare.public_quotes import collection_refusal
from fareflare.refusals import LinkRefused

CORPUS = json.loads((Path(__file__).parent / "fixtures/link_corpus.json").read_text())["links"]


def outcome(url):
    try:
        target = import_link(url, allow_search=True)
    except LinkRefused as refusal:
        return {"refused": refusal.check}
    return {"kind": target.get("kind", "itinerary"), "collector": collection_refusal(target)}


@pytest.mark.parametrize("link", CORPUS, ids=[link["id"] for link in CORPUS])
def test_a_shared_link_is_read_as_reviewed(link):
    assert outcome(link["url"]) == link["expected"]


def test_no_shared_link_is_refused_for_what_was_searched():
    # Searching cities, areas or several airports never stops a chosen flight.
    assert all(link["expected"].get("refused") != "searched_places" for link in CORPUS)
