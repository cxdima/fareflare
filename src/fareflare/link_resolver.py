"""Bounded resolution of Google's share links; never fetch an arbitrary URL."""

from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx

from fareflare.links import InvalidLink, import_link

_SHARED = re.compile(r"https://(?:www\.)?google\.com/travel/flights/s/[A-Za-z0-9_-]{1,128}\Z")


class GoogleLinkResolver:
    def __init__(self, transport=None, *, allow_search: bool = False):
        self.transport = transport
        self.allow_search = allow_search

    def __call__(self, url: str) -> dict:
        if not _SHARED.fullmatch(url):
            return import_link(url, allow_search=self.allow_search)
        # Only this fixed host/path can reach the network. Do not use ambient proxies,
        # cookies, credentials, HTML redirects, or Location values before validation.
        with httpx.Client(
            timeout=3, follow_redirects=False, trust_env=False, transport=self.transport
        ) as client:
            for _ in range(3):
                try:
                    with client.stream(
                        "GET",
                        url,
                        headers={
                            "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/146.0.0.0 Safari/537.36",
                            "Accept-Language": "en-US,en;q=0.9",
                        },
                    ) as response:
                        if response.status_code not in (301, 302, 303, 307, 308):
                            raise InvalidLink(
                                "Shared link did not resolve to a selected itinerary."
                            )
                        location = response.headers.get("location", "")
                        if not location or len(location) > 8192:
                            raise InvalidLink("Invalid shared-link redirect.")
                        resolved = urljoin(url, location)
                        if not _SHARED.fullmatch(resolved):
                            return import_link(resolved, allow_search=self.allow_search)
                        url = resolved
                except httpx.HTTPError:
                    raise InvalidLink(
                        "Shared link resolution failed; retry or paste the full link."
                    ) from None
        raise InvalidLink("Too many shared-link redirects.")
