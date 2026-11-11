"""Shared editorial content and server-rendered discovery metadata.

This registry feeds both initial HTML and Angular's public pages. It contains only
project-authored text; request parameters never become content or canonical URLs.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from html import escape

from fareflare.product_config import ProductConfig

GITHUB_URL = "https://github.com/cxdima/fareflare"
PUBLISHED = "2026-11-05"
SOCIAL_IMAGE = "/assets/social.jpg"
PRIVATE_PATHS = frozenset({"/app", "/login", "/register", "/recover"})


@dataclass(frozen=True)
class Link:
    label: str
    href: str


@dataclass(frozen=True)
class Section:
    heading: str
    paragraphs: tuple[str, ...] = ()
    bullets: tuple[str, ...] = ()
    links: tuple[Link, ...] = ()
    code: str | None = None


@dataclass(frozen=True)
class Page:
    path: str
    title: str
    description: str
    eyebrow: str
    headline: str
    intro: str
    sections: tuple[Section, ...] = ()
    kind: str = "page"
    published: str | None = None
    modified: str | None = None
    read_minutes: int | None = None


def public_pages(config: ProductConfig) -> tuple[Page, ...]:
    """Keep factual capability and capacity copy tied to runtime configuration."""
    minutes = config.min_interval_seconds // 60
    access = "invite-only" if config.registration_mode == "invite" else "open"
    route_status = (
        "Route searches are enabled on this installation."
        if config.search_enabled
        else "Route searches are not enabled on this installation; use a selected itinerary."
    )
    return (
        Page(
            "/",
            "Fareflare — flight price alerts",
            "Track supported Google Flights links and receive price alerts through Telegram, webhooks, API, or MCP. Open-source flight monitoring under MIT.",
            "Flight price alerts",
            "Know when your flight price drops",
            "Add a Google Flights link, choose your alert, and follow the prices Fareflare records for your trip.",
            (
                Section(
                    "Start with your flight link",
                    (
                        "Copy a supported Google Flights link and add it to your monitors. Track a selected itinerary or compare flights on a supported route search.",
                        "Fareflare checks public prices with its own browser. You do not need to share access to your Google account.",
                    ),
                ),
                Section(
                    "Choose when to hear from us",
                    (
                        "Get an alert for a new observed low or a price below your target. Connect Telegram, read alerts in your account, or send signed events to your own webhook.",
                    ),
                ),
                Section(
                    "See the price and when it was checked",
                    (
                        "Each observation includes the itinerary, currency, and time of collection. Price history shows what Fareflare has recorded since monitoring began. A failed check never becomes a guessed price.",
                    ),
                ),
                Section(
                    "Connect your tools",
                    (
                        "Use the same monitors through the REST API and MCP. The MIT-licensed source includes the website, collection worker, tests, and deployment instructions.",
                    ),
                    links=(Link("Read the guides", "/guides"), Link("View on GitHub", GITHUB_URL)),
                ),
            ),
        ),
        Page(
            "/about",
            "About Fareflare",
            "Fareflare is an open-source flight price tracker with Telegram alerts, price history, an API, MCP, and signed webhooks.",
            "About",
            "About Fareflare",
            "Fareflare helps you follow flight prices and act on the changes that matter to you.",
            (
                Section(
                    "What Fareflare does",
                    (
                        "Add a supported Google Flights link to monitor a selected itinerary or route search. Fareflare checks public prices, records successful observations, and sends alerts according to your preferences.",
                        "The website, API, and MCP use the same account and monitors. You can send alerts to Telegram or a verified webhook without giving Fareflare access to your Google account.",
                    ),
                ),
                Section(
                    "Access and capacity",
                    (
                        f"Hosted access is currently free and {access}. Each account can keep {config.monitor_limit} monitors, with a minimum requested interval of {minutes} minutes. Failed checks and backoff can make the gap longer.",
                        "An observed low is the lowest eligible price recorded since monitoring began. Fareflare cannot guarantee the market’s lowest price or catch changes that happen entirely between checks.",
                    ),
                ),
                Section(
                    "Open source",
                    (
                        "The project is available under the MIT license. Inspect the code, report a problem, contribute a change, or run your own instance. Dependencies retain their own licenses.",
                        "Fareflare collects prices using its own browser infrastructure rather than a paid flight-data subscription. Self-hosting still requires computing resources.",
                    ),
                    links=(
                        Link("Source and contributions", GITHUB_URL),
                        Link("Setup guide", GITHUB_URL + "/blob/main/docs/FAREFLARE.md"),
                    ),
                ),
                Section(
                    "Independent flight monitoring",
                    (
                        "Fareflare is independent of Google, airlines, and booking agencies. It does not sell tickets. Confirm the itinerary, fare conditions, and current price with your booking provider before purchasing.",
                    ),
                ),
            ),
        ),
        Page(
            "/guides",
            "Flight monitoring guides — Fareflare",
            "Learn how to choose a supported Google Flights link, read a price alert, and connect Fareflare through API, MCP, or webhooks.",
            "Guides",
            "Get more from your flight monitors",
            "Practical instructions for tracking a flight, understanding its prices, and connecting your tools.",
        ),
        Page(
            "/guides/reading-flight-price-alerts",
            "What a flight price alert actually tells you — Fareflare",
            "Understand observed lows, stale quotes, passenger totals, and what to check before booking after a Fareflare price alert.",
            "Reading the price",
            "What a flight price alert actually tells you",
            "A lower number is a useful signal. The time, itinerary, and fare behind it are what make it actionable.",
            (
                Section(
                    "Start with the observation time",
                    (
                        "Fareflare records a price only after checking the flight identity, passenger context, and eligible fare. The observation timestamp tells you when that comparison happened. It is not a live reservation or a promise that the same fare remains available.",
                        f"The current minimum requested interval is {minutes} minutes. Browser failures, provider changes, and retry backoff can make observations further apart. If a fare falls and rebounds entirely between successful checks, Fareflare cannot report the unseen price.",
                    ),
                ),
                Section(
                    "A new low has a starting point",
                    (
                        "An observed low means the lowest eligible price recorded since this monitor started. It does not describe all previous fares, every airline, or every booking source in the market.",
                        "A selected-itinerary monitor compares the same supported itinerary over time. A route-search monitor can find a different matching flight as the cheapest result. Open the observed offer and check the flight number and times before deciding.",
                    ),
                ),
                Section(
                    "Explore the observations behind the price",
                    (
                        "Open Price history on a monitor and choose All loaded, Past 7 days, or Past 30 days. The latest, lowest, highest, and change figures apply only to loaded observations within that range. Load earlier observations when available to extend the comparison. Lowest in view is not a claim about every price the monitor has ever recorded.",
                        "The chart places prices at their observation times and stops its line across gaps longer than twice the requested check interval. It does not estimate prices for missed checks. The table shows the recorded totals and, for route searches, the matching flight when recorded.",
                        "Export CSV saves the rows currently in view, most recent first, with UTC timestamps and amounts in integer minor units. For USD, 19100 means $191.00; for JPY, 19100 means 19,100 yen. The currency and fare fields help you compare like for like.",
                    ),
                ),
                Section(
                    "Compare the same thing",
                    (
                        "Look at the currency, passenger count, fare name, and whether the displayed amount is the trip total. Two offers with different baggage or ticket conditions are not interchangeable just because their headline prices look close.",
                        "The supported route-search mode excludes Basic fares. That is one explicit selection rule, not a claim that every included fare has the same baggage, change, or refund terms. Read the airline’s actual conditions before booking.",
                    ),
                    bullets=(
                        "Confirm the departure date and airports.",
                        "Check the passenger count, currency, and total payable amount.",
                        "Review the actual included baggage and ticket conditions.",
                        "Follow the observed offer and confirm the price again with the booking provider.",
                    ),
                ),
                Section(
                    "An error is different from a higher price",
                    (
                        "A failed collection does not create a new price observation. Fareflare shows the last verified price with its age and the collection error. A stale price should not be interpreted as a fresh quote.",
                        "Choose alert preferences that fit your decision. You can watch observed lows, set a threshold, and mute alerts without pretending a monitoring tool can know when a fare will reach its final minimum.",
                    ),
                    links=(
                        Link("Choose a supported flight link", "/guides/choosing-a-flight-link"),
                        Link("Open your watchlist", "/app"),
                    ),
                ),
            ),
            "guide",
            PUBLISHED,
            PUBLISHED,
            5,
        ),
        Page(
            "/guides/choosing-a-flight-link",
            "Choose a Google Flights link to watch — Fareflare",
            "Learn when to use a selected itinerary or a supported route search, and which passenger, airport, currency, and fare settings Fareflare supports.",
            "Getting started",
            "Choose a flight link to monitor",
            "A selected flight and a route search answer different questions. Start with the one that matches your travel plans.",
            (
                Section(
                    "Watch a selected itinerary when the flight matters",
                    (
                        "Choose the flights you want in Google Flights, then copy the resulting link. A selected-itinerary monitor is useful when the departure time, airline, or return flight is part of your decision.",
                        "Current selected-itinerary collection supports US-English economy, one or two adults, USD or JPY, and nonstop one-way trips or fully selected round trips. For a round trip, choose both the outbound and return flight before copying the link. An incomplete selection is not the same itinerary.",
                    ),
                ),
                Section(
                    "Watch a route when several flights would work",
                    (
                        "A route-search monitor compares the eligible results for a supported search and keeps the actual matching flight with each observation. The cheapest matching result may be a different flight on the next successful check.",
                        "Supported route searches use exact departure and arrival airports, an exact date, one way, nonstop, one adult, USD, US-English, and economy excluding Basic. Flexible dates, nearby-airport searches, and unrestricted combinations are not supported.",
                        route_status,
                    ),
                ),
                Section(
                    "Keep the link and the expectations together",
                    (
                        "Paste the complete Google Flights link into Fareflare. The service checks the encoded selection and rejects unsupported inputs explicitly. Removing parts of the URL to make it shorter can remove the very constraints you meant to track.",
                        "No customer Google account access is required. Fareflare collects anonymous public prices. You should not paste Google cookies, passwords, recovery codes, or any other account credentials into a monitor.",
                    ),
                    bullets=(
                        "Pick the supported locale, currency, passenger count, and cabin.",
                        "For a selected round trip, complete both flight selections.",
                        "Copy the full link and add it to your watchlist.",
                        "Check the monitor’s first verified observation before relying on its alerts.",
                    ),
                ),
                Section(
                    "If the first check fails",
                    (
                        "Read the collection status. An unsupported itinerary needs a different supported selection. A temporary browser or page failure may be retried after backoff. Neither result should be replaced with a guessed price.",
                        "You can pause or cancel a monitor from the dashboard. A cancelled monitor releases your account’s monitor capacity; shared collection can continue if another subscriber still watches the same target.",
                    ),
                    links=(
                        Link("Understand the next alert", "/guides/reading-flight-price-alerts"),
                        Link("Sign in", "/login"),
                    ),
                ),
            ),
            "guide",
            PUBLISHED,
            PUBLISHED,
            4,
        ),
        Page(
            "/guides/api-mcp-webhooks",
            "Connect Fareflare with API, MCP, and webhooks — Fareflare",
            "Use a revocable API key, connect an MCP client with OAuth, or receive verified signed webhook events from your Fareflare monitors.",
            "For builders",
            "Connect the API, MCP, and webhooks",
            "The API, MCP, and dashboard operate on the same account. Pick the interface that fits the job.",
            (
                Section(
                    "Use the API for direct application calls",
                    (
                        "Create a named API key in API & MCP settings. Copy its secret when it is shown; later listings show the key’s metadata, not the secret. Keep it on your server or in a secret store, and revoke it when an integration no longer needs access.",
                        "Send the key as a Bearer credential. Creation requests for monitors and webhook endpoints also need an Idempotency-Key. Reuse the same key for a retry of the same request after a network failure; generate a new key for a new action.",
                    ),
                    code='curl "$FAREFLARE_ORIGIN/v1/monitors" \\\n  -H "Authorization: Bearer $FAREFLARE_API_KEY"',
                    links=(Link("API reference", "/docs"), Link("OpenAPI schema", "/openapi.json")),
                ),
                Section(
                    "Use MCP for an assistant or compatible client",
                    (
                        "The hosted MCP address is this site’s origin followed by /mcp. Clients that support OAuth can discover the authorization server, ask you to sign in, and request explicit consent. PKCE protects the authorization exchange. Review the requested client before approving it.",
                        "For a client that supports custom request headers, a customer API key can also be sent as a Bearer credential. OAuth access tokens are scoped to MCP; they are not REST API keys. Connected applications can be revoked from your account settings.",
                    ),
                ),
                Section(
                    "Use webhooks when a change should trigger work",
                    (
                        "Register an HTTPS endpoint you control and complete the ownership verification before using it as an alert destination. Keep the signing secret private. Your receiver should verify the Standard Webhooks signature against the raw request body before processing an event.",
                        "Delivery is at least once. Deduplicate by the event ID, make processing idempotent, and return success only after accepting the event durably. A temporary failure can be retried; repeated failures remain visible for investigation and retry.",
                        "A monitor explicitly routed to a webhook does not silently fall back to Telegram. Choose the destination deliberately and inspect delivery history when debugging.",
                    ),
                    links=(
                        Link(
                            "Webhook protocol and examples",
                            GITHUB_URL + "/blob/main/docs/INTEGRATIONS.md#customer-webhooks",
                        ),
                    ),
                ),
                Section(
                    "Treat observations as observations",
                    (
                        "Prices are integer minor units in the API: USD 123.45 is 12345. Use the currency and observation timestamp together, follow pagination cursors, and respect Retry-After responses instead of repeatedly retrying a busy service.",
                        "API access does not remove collection limits or make a stored observation live. Build the age of the quote and any collection failure into your own interface. No payment credentials are required.",
                    ),
                ),
            ),
            "guide",
            PUBLISHED,
            PUBLISHED,
            5,
        ),
        Page(
            "/developers",
            "Flight tracking API and MCP — Fareflare",
            "Build on Fareflare’s shared monitors with a REST API, OAuth-enabled MCP, and verified signed webhooks. Open-source flight monitoring.",
            "For developers",
            "Build with Fareflare",
            "Use the dashboard to get started. Use the same monitors through an API, an MCP client, or signed webhook events.",
            (
                Section(
                    "Manage flights and alerts",
                    (
                        "Create and manage monitors, read price observations, set alert preferences, and inspect deliveries. The REST API and MCP share the same application service and account boundaries.",
                        "No customer Google credentials or paid flight-data subscription is required. The same monitor and collection limits apply to the website and integrations.",
                    ),
                    links=(
                        Link("Read the API reference", "/docs"),
                        Link("Download OpenAPI", "/openapi.json"),
                    ),
                ),
                Section(
                    "Choose an interface",
                    bullets=(
                        "REST API: named, revocable Bearer API keys and idempotent creation requests.",
                        "MCP: OAuth with consent and PKCE, or a customer API key for compatible clients.",
                        "Webhooks: verified HTTPS endpoints, signed events, durable retries, and stable event IDs.",
                    ),
                    links=(Link("Integration guide", "/guides/api-mcp-webhooks"),),
                ),
                Section(
                    "Run it yourself or contribute",
                    (
                        "The MIT-licensed repository includes the application, browser worker, tests, and deployment instructions. You can operate your own installation.",
                        "Check the supported collection scope before building around it. Recorded prices are observations with timestamps, not bookable inventory or a guarantee of market-wide availability.",
                    ),
                    links=(
                        Link("View the GitHub repository", GITHUB_URL),
                        Link("Choose supported inputs", "/guides/choosing-a-flight-link"),
                    ),
                ),
            ),
        ),
        Page(
            "/status",
            "System status — Fareflare",
            "See whether Fareflare's price checks, alerts and website are working right now, with the last 24 hours of price checks.",
            "Status",
            "System status",
            "Whether price checks, alerts and the website are working right now.",
            (
                Section(
                    "What this page reports",
                    (
                        "Fareflare records each scheduled price-check run. This page shows when checks last ran, how many of the last 24 hours' checks recorded a price, and how many alerts were sent.",
                        "A check that cannot finish is retried within a couple of minutes, so a few failed checks an hour are normal. The page reports trouble when checks stop running or most of them fail.",
                    ),
                ),
            ),
        ),
        Page(
            "/privacy",
            "Privacy and data — Fareflare",
            "What Fareflare stores, how account and notification data are used, and what account deletion means.",
            "Privacy",
            "Your account data",
            "This page describes the current application’s data handling. Read it before connecting an account or integration.",
            (
                Section(
                    "Data needed to run the service",
                    (
                        "Fareflare stores your sign-in name, password hash, account status, and authentication records. The sign-in name is a username or, if you choose, an email address. An address is kept only as the name you sign in with: Fareflare does not verify it, does not send email to it, and does not share it. Session, invitation, recovery, API, and OAuth credentials are stored as hashes where they are used for authentication. A browser session uses an HttpOnly cookie.",
                        "Your monitors contain flight links, the selections derived from them, alert preferences, and notification history. Equivalent collection targets and price observations can be shared across subscribers; each account’s subscriptions and settings remain private.",
                    ),
                ),
                Section(
                    "Connections you choose",
                    (
                        "Connecting Telegram associates your private Telegram chat with your Fareflare account so you can manage flights and receive alerts. Button actions and pending confirmations expire after 15 minutes. Command replies may be retained for up to two days to retry failed delivery; storage cleanup can occur later. Registering a webhook stores its endpoint and delivery configuration, including a signing secret needed to sign events.",
                        "Fareflare uses AWS for hosting and storage. Google Flights is contacted to collect public prices; Telegram is contacted if you connect the bot. A configured webhook receives the events you route to it. Fareflare does not require your Google account credentials.",
                    ),
                ),
                Section(
                    "Sessions, diagnostics, and deletion",
                    (
                        "The application uses its session cookie to keep you signed in and a CSRF token for state-changing browser requests. It does not include an advertising tracker or third-party analytics script. Service logs can contain request metadata, errors, and operational identifiers.",
                        "Deleting your account requires your password, revokes account access, stops future monitoring and delivery for that account, and removes its Telegram association. Shared observations, operational records, and backups are managed separately; deletion does not promise immediate erasure of every historical record.",
                    ),
                ),
                Section(
                    "Keep private details out of public issues",
                    (
                        "Use account settings to revoke keys, disconnect applications, or delete your account. The GitHub repository accepts product questions and bug reports, but it is public. Never post passwords, invitations, recovery codes, API keys, or private Telegram details there.",
                    ),
                    links=(
                        Link("Account settings", "/app#settings"),
                        Link("Project repository", GITHUB_URL),
                    ),
                ),
            ),
        ),
        Page(
            "/terms",
            "Terms of use — Fareflare",
            "Understand Fareflare’s access limits, supported use, observed-price limitations, and open-source license.",
            "Terms",
            "Using Fareflare",
            "Fareflare monitors flight prices. It is not an airline, booking agent, or ticket seller.",
            (
                Section(
                    "Access and availability",
                    (
                        f"Hosted access is currently free and {access}; billing is disabled. Capacity limits apply, including {config.monitor_limit} monitors per account and a {minutes}-minute minimum requested collection interval. These limits can change as the project develops.",
                        "There is no availability or notification-latency guarantee. Collection can fail or be delayed, and a price can change before an alert arrives or before you reach a booking provider.",
                    ),
                ),
                Section(
                    "Use it for information, then verify",
                    (
                        "An observed low is the lowest eligible price the service has recorded for a monitor, not proof of the cheapest ticket anywhere in the market. Always verify the itinerary, passengers, currency, fare conditions, and final price with the airline or booking provider.",
                        "Fareflare is independent of Google and the airlines. Their names identify the sources or flights being discussed; they do not imply endorsement or a commercial relationship.",
                    ),
                ),
                Section(
                    "Respect account and service boundaries",
                    (
                        "Keep your credentials private, connect only integrations you control, and do not attempt to access another account’s data or bypass capacity limits. Use the documented API and respect rate-limit responses.",
                        "Project code is available under the MIT license, including its warranty disclaimer. Dependencies and third-party services have their own terms. The code license does not grant access to anyone else’s account or third-party data.",
                    ),
                    links=(
                        Link("Read the MIT license", GITHUB_URL + "/blob/main/LICENSE"),
                        Link("Privacy and data", "/privacy"),
                    ),
                ),
            ),
        ),
    )


def content_document(config: ProductConfig) -> dict:
    return {
        "github_url": GITHUB_URL,
        "product_name": config.product_name,
        "pages": [asdict(page) for page in public_pages(config)],
    }


def structured_data(page: Page, config: ProductConfig) -> dict:
    origin = config.public_url.rstrip("/")
    canonical = origin + page.path
    organization = {
        "@type": "Organization",
        "@id": origin + "/#organization",
        "name": config.product_name,
        "url": origin + "/",
        "sameAs": [GITHUB_URL],
        "logo": origin + "/assets/fareflare-mark.png?v=3",
    }
    graph: list[dict] = [
        organization,
        {
            "@type": "WebSite",
            "@id": origin + "/#website",
            "name": config.product_name,
            "url": origin + "/",
            "publisher": {"@id": organization["@id"]},
            "inLanguage": "en-US",
        },
        {
            "@type": "WebPage",
            "@id": canonical + "#webpage",
            "url": canonical,
            "name": page.title,
            "description": page.description,
            "isPartOf": {"@id": origin + "/#website"},
            "inLanguage": "en-US",
        },
    ]
    if page.path in ("/", "/developers"):
        graph.append(
            {
                "@type": "SoftwareApplication",
                "@id": origin + "/#application",
                "name": config.product_name,
                "url": origin + "/",
                "applicationCategory": "TravelApplication",
                "operatingSystem": "Web browser",
                "isAccessibleForFree": True,
                "description": "Open-source flight price monitoring with a dashboard, API, MCP, and alert integrations.",
                "license": GITHUB_URL + "/blob/main/LICENSE",
                "publisher": {"@id": organization["@id"]},
            }
        )
    if page.kind == "guide":
        graph.append(
            {
                "@type": "BlogPosting",
                "@id": canonical + "#article",
                "headline": page.headline,
                "description": page.description,
                "mainEntityOfPage": {"@id": canonical + "#webpage"},
                "author": {
                    "@type": "Organization",
                    "name": config.product_name,
                    "url": origin + "/about",
                },
                "publisher": {"@id": organization["@id"]},
                "datePublished": page.published,
                "dateModified": page.modified,
                "inLanguage": "en-US",
                "isAccessibleForFree": True,
            }
        )
    if page.path != "/":
        crumbs = [{"@type": "ListItem", "position": 1, "name": "Home", "item": origin + "/"}]
        if page.kind == "guide":
            crumbs.append(
                {"@type": "ListItem", "position": 2, "name": "Guides", "item": origin + "/guides"}
            )
        crumbs.append(
            {
                "@type": "ListItem",
                "position": len(crumbs) + 1,
                "name": page.headline,
                "item": canonical,
            }
        )
        graph.append(
            {
                "@type": "BreadcrumbList",
                "@id": canonical + "#breadcrumbs",
                "itemListElement": crumbs,
            }
        )
    return {"@context": "https://schema.org", "@graph": graph}


def render_body(page: Page, config: ProductConfig) -> str:
    """Escaped, useful HTML for the same content Angular will render."""
    sections = []
    for section in page.sections:
        body = "".join("<p>" + escape(p) + "</p>" for p in section.paragraphs)
        if section.bullets:
            body += (
                "<ul>" + "".join("<li>" + escape(p) + "</li>" for p in section.bullets) + "</ul>"
            )
        if section.code:
            body += "<pre><code>" + escape(section.code) + "</code></pre>"
        if section.links:
            body += (
                '<div class="article-links">'
                + "".join(
                    '<a href="' + escape(link.href, quote=True) + '">' + escape(link.label) + "</a>"
                    for link in section.links
                )
                + "</div>"
            )
        sections.append("<section><h2>" + escape(section.heading) + "</h2>" + body + "</section>")
    if page.path == "/guides":
        sections.append(
            "<ul>"
            + "".join(
                '<li><a href="'
                + guide.path
                + '">'
                + escape(guide.headline)
                + "</a><p>"
                + escape(guide.description)
                + "</p></li>"
                for guide in public_pages(config)
                if guide.kind == "guide"
            )
            + "</ul>"
        )
    byline = (
        '<p class="article-meta"><span>By '
        + escape(config.product_name)
        + '</span><time datetime="'
        + str(page.published)
        + '">'
        + str(page.published)
        + "</time></p>"
        if page.kind == "guide"
        else ""
    )
    article_open = "<article>" if page.kind == "guide" else ""
    article_close = "</article>" if page.kind == "guide" else ""
    return (
        '<a class="skip-link" href="#main-content">Skip to content</a>'
        '<header class="site-header"><div class="public-container site-header-inner">'
        '<a class="brand" href="/">'
        + escape(config.product_name)
        + '</a><nav class="site-nav" aria-label="Main navigation">'
        '<a href="/guides">Guides</a><a href="/developers">Developers</a><a href="/about">About</a>'
        '<a href="/login">Sign in</a></nav></div></header>'
        '<main id="main-content" class="public-container public-article">'
        + article_open
        + "<h1>"
        + escape(page.headline)
        + '</h1><p class="lead">'
        + escape(page.intro)
        + "</p>"
        + byline
        + "".join(sections)
        + article_close
        + '</main><footer class="public-footer"><div class="public-container">'
        '<nav class="footer-links" aria-label="Footer"><a href="/privacy">Privacy</a><a href="/terms">Terms</a><a href="'
        + GITHUB_URL
        + '">GitHub</a></nav>'
        "</div></footer>"
    )


def render_document(
    shell: str, page: Page, config: ProductConfig, nonce: str, *, indexable: bool = True
) -> str:
    """Add per-request metadata without reflecting query strings or untrusted HTML."""
    canonical = config.public_url.rstrip("/") + page.path
    # The build shell is trusted, but replace stale static SEO tags deterministically.
    shell = re.sub(r"<title\b[^>]*>.*?</title\s*>", "", shell, flags=re.I | re.S)
    shell = re.sub(
        r"<meta\b[^>]*(?:name|property)=[\"\'](?:description|robots|og:[^\"\']*|twitter:[^\"\']*)[\"\'][^>]*>",
        "",
        shell,
        flags=re.I,
    )
    shell = re.sub(r"<link\b[^>]*rel=[\"\']canonical[\"\'][^>]*>", "", shell, flags=re.I)
    metadata = (
        "<title>"
        + escape(page.title)
        + '</title><meta name="description" content="'
        + escape(page.description, quote=True)
        + '">'
        '<meta name="robots" content="'
        + ("index, follow" if indexable else "noindex, nofollow")
        + '">'
        '<link rel="canonical" href="' + escape(canonical, quote=True) + '">'
    )
    for key, value in (
        ("og:type", "article" if page.kind == "guide" else "website"),
        ("og:title", page.title),
        ("og:description", page.description),
        ("og:url", canonical),
        ("og:site_name", config.product_name),
        ("og:image", config.public_url.rstrip("/") + SOCIAL_IMAGE),
        ("og:image:width", "1200"),
        ("og:image:height", "630"),
        (
            "og:image:alt",
            "White paper planes in flight on a lavender backdrop, one of them lime green",
        ),
    ):
        metadata += '<meta property="' + key + '" content="' + escape(value, quote=True) + '">'
    metadata += '<meta name="twitter:card" content="summary_large_image">'
    metadata += '<link rel="alternate" type="application/rss+xml" title="Fareflare guides" href="/feed.xml">'
    if indexable:
        # JSON string escaping alone does not protect a script element's HTML parser.
        payload = (
            json.dumps(structured_data(page, config), ensure_ascii=False)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
        )
        metadata += (
            '<script type="application/ld+json" nonce="' + nonce + '">' + payload + "</script>"
        )
    if "</head>" in shell:
        shell = shell.replace("</head>", metadata + "</head>", 1)
    else:
        shell = (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            + metadata
            + "</head><body><app-root></app-root></body></html>"
        )
    body = (
        render_body(page, config)
        if indexable
        else (
            '<main id="main-content" class="public-container public-article"><h1>'
            + escape(page.headline)
            + "</h1><p>"
            + escape(page.intro)
            + "</p><noscript>Enable JavaScript to use the account application.</noscript></main>"
        )
    )
    root = '<app-root ngCspNonce="' + nonce + '">' + body + "</app-root>"
    if re.search(r"<app-root\b", shell, re.I):
        shell = re.sub(
            r"<app-root\b[^>]*>.*?</app-root\s*>", lambda _: root, shell, count=1, flags=re.I | re.S
        )
    else:
        shell = re.sub(
            r"<div\s+id=[\"\']root[\"\'][^>]*>.*?</div>",
            lambda _: root,
            shell,
            count=1,
            flags=re.I | re.S,
        )
    return shell


def private_page(path: str) -> Page:
    return Page(
        path,
        "Your account — Fareflare",
        "Manage your Fareflare account and monitors.",
        "Your account",
        "Your Fareflare account",
        "Sign in to manage your monitors and connections.",
    )


def sitemap(config: ProductConfig) -> str:
    origin = config.public_url.rstrip("/")
    entries = "".join(
        "<url><loc>"
        + escape(origin + page.path)
        + "</loc>"
        + ("<lastmod>" + page.modified + "</lastmod>" if page.modified else "")
        + "</url>"
        for page in public_pages(config)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + entries
        + "</urlset>"
    )


def feed(config: ProductConfig) -> str:
    origin = config.public_url.rstrip("/")
    items = "".join(
        "<item><title>"
        + escape(page.headline)
        + "</title><link>"
        + escape(origin + page.path)
        + "</link><guid>"
        + escape(origin + page.path)
        + "</guid><description>"
        + escape(page.description)
        + "</description></item>"
        for page in public_pages(config)
        if page.kind == "guide"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>'
        + escape(config.product_name)
        + " guides</title><link>"
        + escape(origin + "/guides")
        + "</link><description>Practical notes on flight-price monitoring and integrations.</description>"
        + "<language>en-US</language>"
        + items
        + "</channel></rss>"
    )
