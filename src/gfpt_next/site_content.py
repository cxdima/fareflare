"""Shared editorial content and server-rendered discovery metadata.

This registry feeds both initial HTML and Angular's public pages. It contains only
project-authored text; request parameters never become content or canonical URLs.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from html import escape

from gfpt_next.product_config import ProductConfig

GITHUB_URL = "https://github.com/cxdima/google-flights-price-tracker"
PUBLISHED = "2026-11-05"
SOCIAL_IMAGE = "/assets/window-seat.jpg"
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
    route_status = ("Route searches are enabled on this installation." if config.search_enabled
                    else "Route searches are not enabled on this installation; use a selected itinerary.")
    return (
        Page("/", "Fareflare — flight price alerts, on your terms",
             "Track supported Google Flights links with Fareflare. Free development access, Telegram alerts, an API, and MCP. Open-source under MIT.",
             "Flight price tracking · Open source", "Good fares don’t wait until midnight.",
             "Keep an eye on the flight you want. Fareflare watches its price and lets you know when it finds a new low.", (
                 Section("A link. A watch. A heads-up.", (
                     "Copy a supported Google Flights link, add it to your watchlist, and choose how you want to hear about observed price drops.",
                     "Fareflare checks public flight prices with its own browser. You do not hand over access to your Google account.")),
                 Section("Choose where the alert lands.", (
                     "Connect Telegram for a personal alert, use the dashboard, or send signed events to your own webhook. Developers can use the same monitors through the API and MCP.",)),
                 Section("Built for a dad who kept missing the drop.", (
                     "Fareflare began as a shared Telegram bot for a father and son. A nightly price email was too late for a fare that fell and rebounded during the day. The project keeps that practical purpose: show the price we actually observed and make the next step clear.",)),
                 Section("A small, honest preview.", (
                     f"Development access is free and {access}. Each account can keep {config.monitor_limit} monitors, with a minimum requested interval of {minutes} minutes. Failed checks and backoff can make the gap longer.",
                     "An observed low is the lowest eligible price Fareflare has seen since monitoring began. It is not a guarantee of the market’s lowest price or of catching every short-lived drop."),
                     links=(Link("Read the field notes", "/guides"), Link("Explore the source", GITHUB_URL))),
             )),
        Page("/about", "Why Fareflare exists — Fareflare",
             "The story behind Fareflare: a father-and-son flight tracker, built to make observed fare drops useful and shared as open-source software.",
             "The project", "A small tool, built for a real trip.",
             "Fareflare started with a dad watching flight prices and a son who wanted to help him catch a better fare.", (
                 Section("The email arrived after the opportunity.", (
                     "In the family’s experience, a nightly price email could arrive after a fare had already risen again. A price chart was useful, but knowing about a drop while it was still available mattered more.",
                     "The first version watched a shared Google account and sent changes to a Telegram bot used by two people. Fareflare’s customer application now starts with a public Google Flights link, so customers do not need to share Google credentials.")),
                 Section("What we are building.", (
                     "One place to watch a supported itinerary, understand the prices actually observed, and choose where an alert goes. The dashboard, API, and MCP share the same account and monitors.",
                     "The collection runs on our own browser infrastructure. Fareflare does not buy a subscription to a flight-data API and resell it. Hosting and browser collection still use resources, so development capacity is deliberately small.")),
                 Section("Open source, with clear limits.", (
                     "Project code is available under the MIT license. You can inspect it, contribute, and run your own instance. Dependencies retain their own licenses.",
                     "Fareflare is an independent project, not affiliated with Google, an airline, or a booking agency. It does not issue tickets. A quote can change before you reach the airline or booking provider."),
                     links=(Link("Source and contributions", GITHUB_URL), Link("Development documentation", GITHUB_URL + "/blob/codex/link-monitoring/docs/FAREFLARE.md"))),
             )),
        Page("/guides", "Field notes on flight tracking — Fareflare",
             "Practical Fareflare guides: choose a supported Google Flights link, read an observed price alert, and connect API, MCP, or webhooks.",
             "Field notes", "Make the next price drop useful.",
             "Straightforward notes on choosing a flight to watch, reading an alert, and connecting your own tools."),
        Page("/guides/reading-flight-price-alerts", "What a flight price alert actually tells you — Fareflare",
             "Understand observed lows, stale quotes, passenger totals, and what to check before booking after a Fareflare price alert.",
             "Reading the price", "What a flight price alert actually tells you",
             "A lower number is a useful signal. The time, itinerary, and fare behind it are what make it actionable.", (
                 Section("Start with the observation time.", (
                     "Fareflare records a price only after checking the flight identity, passenger context, and eligible fare. The observation timestamp tells you when that comparison happened. It is not a live reservation or a promise that the same fare remains available.",
                     f"The current minimum requested interval is {minutes} minutes. Browser failures, provider changes, and retry backoff can make observations further apart. If a fare falls and rebounds entirely between successful checks, Fareflare cannot report the unseen price.")),
                 Section("A new low has a starting point.", (
                     "An observed low means the lowest eligible price recorded since this monitor started. It does not describe all previous fares, every airline, or every booking source in the market.",
                     "A selected-itinerary monitor compares the same supported itinerary over time. A route-search monitor can find a different matching flight as the cheapest result. Open the observed offer and check the flight number and times before deciding.")),
                 Section("Compare the same thing.", (
                     "Look at the currency, passenger count, fare name, and whether the displayed amount is the trip total. Two offers with different baggage or ticket conditions are not interchangeable just because their headline prices look close.",
                     "The supported route-search mode excludes Basic fares. That is one explicit selection rule, not a claim that every included fare has the same baggage, change, or refund terms. Read the airline’s actual conditions before booking."),
                     bullets=("Confirm the departure date and airports.", "Check the passenger count, currency, and total payable amount.",
                              "Review the actual included baggage and ticket conditions.", "Follow the observed offer and confirm the price again with the booking provider.")),
                 Section("An error is different from a higher price.", (
                     "A failed collection does not create a new price observation. Fareflare shows the last verified price with its age and the collection error. A stale price should not be interpreted as a fresh quote.",
                     "Choose alert preferences that fit your decision. You can watch observed lows, set a threshold, and mute alerts without pretending a monitoring tool can know when a fare will reach its final minimum."),
                     links=(Link("Choose a supported flight link", "/guides/choosing-a-flight-link"), Link("Open your watchlist", "/app"))),
             ), "guide", PUBLISHED, PUBLISHED, 4),
        Page("/guides/choosing-a-flight-link", "Choose a Google Flights link to watch — Fareflare",
             "Learn when to use a selected itinerary or a supported route search, and which passenger, airport, currency, and fare settings Fareflare supports.",
             "Getting started", "Choose the flight you actually mean.",
             "A selected flight and a route search answer different questions. Start with the one that matches your travel plans.", (
                 Section("Watch a selected itinerary when the flight matters.", (
                     "Choose the flights you want in Google Flights, then copy the resulting link. A selected-itinerary monitor is useful when the departure time, airline, or return flight is part of your decision.",
                     "Current selected-itinerary collection supports US-English economy, one or two adults, USD or JPY, and nonstop one-way trips or fully selected round trips. For a round trip, choose both the outbound and return flight before copying the link. An incomplete selection is not the same itinerary.")),
                 Section("Watch a route when several flights would work.", (
                     "A route-search monitor compares the eligible results for a supported search and keeps the actual matching flight with each observation. The cheapest matching result may be a different flight on the next successful check.",
                     "Supported route searches use exact departure and arrival airports, an exact date, one way, nonstop, one adult, USD, US-English, and economy excluding Basic. Flexible dates, nearby-airport searches, and unrestricted combinations are outside this preview.", route_status)),
                 Section("Keep the link and the expectations together.", (
                     "Paste the complete Google Flights link into Fareflare. The service checks the encoded selection and rejects unsupported inputs explicitly. Removing parts of the URL to make it shorter can remove the very constraints you meant to track.",
                     "No customer Google account access is required. Fareflare collects anonymous public prices. You should not paste Google cookies, passwords, recovery codes, or any other account credentials into a monitor."),
                     bullets=("Pick the supported locale, currency, passenger count, and cabin.", "For a selected round trip, complete both flight selections.",
                              "Copy the full link and add it to your watchlist.", "Check the monitor’s first verified observation before relying on its alerts.")),
                 Section("If the first check fails.", (
                     "Read the collection status. An unsupported itinerary needs a different supported selection. A temporary browser or page failure may be retried after backoff. Neither result should be replaced with a guessed price.",
                     "You can pause or cancel a monitor from the dashboard. A cancelled monitor releases your account’s monitor capacity; shared collection can continue if another subscriber still watches the same target."),
                     links=(Link("Understand the next alert", "/guides/reading-flight-price-alerts"), Link("Sign in", "/login"))),
             ), "guide", PUBLISHED, PUBLISHED, 4),
        Page("/guides/api-mcp-webhooks", "Connect Fareflare with API, MCP, and webhooks — Fareflare",
             "Use a revocable API key, connect an MCP client with OAuth, or receive verified signed webhook events from your Fareflare monitors.",
             "For builders", "Your monitors, in the tools you use.",
             "The API, MCP, and dashboard operate on the same account. Pick the interface that fits the job.", (
                 Section("Use the API for direct application calls.", (
                     "Create a named API key in API & MCP settings. Copy its secret when it is shown; later listings show the key’s metadata, not the secret. Keep it on your server or in a secret store, and revoke it when an integration no longer needs access.",
                     "Send the key as a Bearer credential. Creation requests for monitors and webhook endpoints also need an Idempotency-Key. Reuse the same key for a retry of the same request after a network failure; generate a new key for a new action."),
                     code='curl "$FAREFLARE_ORIGIN/v1/monitors" \\\n  -H "Authorization: Bearer $FAREFLARE_API_KEY"',
                     links=(Link("API reference", "/docs"), Link("OpenAPI schema", "/openapi.json"))),
                 Section("Use MCP for an assistant or compatible client.", (
                     "The hosted MCP address is this site’s origin followed by /mcp. Clients that support OAuth can discover the authorization server, ask you to sign in, and request explicit consent. PKCE protects the authorization exchange. Review the requested client before approving it.",
                     "For a client that supports custom request headers, a customer API key can also be sent as a Bearer credential. OAuth access tokens are scoped to MCP; they are not REST API keys. Connected applications can be revoked from your account settings.")),
                 Section("Use webhooks when a change should trigger work.", (
                     "Register an HTTPS endpoint you control and complete the ownership verification before using it as an alert destination. Keep the signing secret private. Your receiver should verify the Standard Webhooks signature against the raw request body before processing an event.",
                     "Delivery is at least once. Deduplicate by the event ID, make processing idempotent, and return success only after accepting the event durably. A temporary failure can be retried; repeated failures remain visible for investigation and retry.",
                     "A monitor explicitly routed to a webhook does not silently fall back to Telegram. Choose the destination deliberately and inspect delivery history when debugging."),
                     links=(Link("Webhook protocol and examples", GITHUB_URL + "/blob/codex/link-monitoring/docs/NEXT.md#customer-webhooks"),)),
                 Section("Treat observations as observations.", (
                     "Prices are integer minor units in the API: USD 123.45 is 12345. Use the currency and observation timestamp together, follow pagination cursors, and respect Retry-After responses instead of repeatedly retrying a busy service.",
                     "API access does not remove collection limits or make a stored observation live. Build the age of the quote and any collection failure into your own interface. Development access is free; no payment credentials are required.")),
             ), "guide", PUBLISHED, PUBLISHED, 5),
        Page("/developers", "Flight tracking API and MCP — Fareflare",
             "Build on Fareflare’s shared monitors with a REST API, OAuth-enabled MCP, and verified signed webhooks. Open source, with free development access.",
             "For developers", "A flight watch you can build on.",
             "Use the dashboard to get started. Use the same monitors through an API, an MCP client, or signed webhook events.", (
                 Section("A small, consistent surface.", (
                     "Create and manage monitors, read price observations, set alert preferences, and inspect deliveries. The REST API and MCP share the same application service and account boundaries.",
                     "No customer Google credentials or paid flight-data subscription is required. Hosted development access is free, with the same monitor and collection limits as the dashboard."),
                     links=(Link("Read the API reference", "/docs"), Link("Download OpenAPI", "/openapi.json"))),
                 Section("Choose the connection.", bullets=(
                     "REST API: named, revocable Bearer API keys and idempotent creation requests.",
                     "MCP: OAuth with consent and PKCE, or a customer API key for compatible clients.",
                     "Webhooks: verified HTTPS endpoints, signed events, durable retries, and stable event IDs."),
                     links=(Link("Integration guide", "/guides/api-mcp-webhooks"),)),
                 Section("Inspect it. Run it. Improve it.", (
                     "The MIT-licensed repository includes the application, browser worker, tests, and deployment instructions. The hosted preview is one installation; you can operate your own.",
                     "Check the supported collection scope before building around it. Recorded prices are observations with timestamps, not bookable inventory or a guarantee of market-wide availability."),
                     links=(Link("View the GitHub repository", GITHUB_URL), Link("Choose supported inputs", "/guides/choosing-a-flight-link"))),
             )),
        Page("/privacy", "Privacy and data in the development preview — Fareflare",
             "What Fareflare stores, how account and notification data are used, and what account deletion means in the development preview.",
             "Development preview", "Your account and the data it uses.",
             "This page describes the current application’s data handling. Read it before connecting an account or integration.", (
                 Section("Data needed to run the service.", (
                     "Fareflare stores your username, password hash, account status, and authentication records. Session, invitation, recovery, API, and OAuth credentials are stored as hashes where they are used for authentication. A browser session uses an HttpOnly cookie.",
                     "Your monitors contain flight links, the selections derived from them, alert preferences, and notification history. Equivalent collection targets and price observations can be shared across subscribers; each account’s subscriptions and settings remain private.")),
                 Section("Connections you choose.", (
                     "Connecting Telegram associates your private Telegram chat with your Fareflare account so the bot can deliver alerts. Registering a webhook stores its endpoint and delivery configuration, including a signing secret needed to sign events.",
                     "Fareflare uses AWS for hosting and storage. Google Flights is contacted to collect public prices; Telegram is contacted if you connect the bot. A configured webhook receives the events you route to it. Fareflare does not require your Google account credentials.")),
                 Section("Sessions, diagnostics, and deletion.", (
                     "The application uses its session cookie to keep you signed in and a CSRF token for state-changing browser requests. It does not include an advertising tracker or third-party analytics script. Service logs can contain request metadata, errors, and operational identifiers.",
                     "Deleting your account requires your password, revokes account access, stops future monitoring and delivery for that account, and removes its Telegram association. Shared observations, operational records, and backups are managed separately; deletion does not promise immediate erasure of every historical record.")),
                 Section("Keep private details out of public issues.", (
                     "Use account settings to revoke keys, disconnect applications, or delete your account. The GitHub repository accepts product questions and bug reports, but it is public. Never post passwords, invitations, recovery codes, API keys, or private Telegram details there.",),
                     links=(Link("Account settings", "/app#settings"), Link("Project repository", GITHUB_URL))),
             )),
        Page("/terms", "Using the development preview — Fareflare",
             "Understand Fareflare’s free development access, supported use, observed-price limitations, and open-source license.",
             "Development preview", "What to expect from Fareflare.",
             "Fareflare is a flight-monitoring tool in active development. It is not an airline, booking agent, or ticket seller.", (
                 Section("Free development access.", (
                     f"Hosted access is currently free and {access}; billing is disabled. Capacity limits apply, including {config.monitor_limit} monitors per account and a {minutes}-minute minimum requested collection interval. These limits can change as the project develops.",
                     "There is no availability or notification-latency guarantee. Collection can fail or be delayed, and a price can change before an alert arrives or before you reach a booking provider.")),
                 Section("Use it for information, then verify.", (
                     "An observed low is the lowest eligible price the service has recorded for a monitor, not proof of the cheapest ticket anywhere in the market. Always verify the itinerary, passengers, currency, fare conditions, and final price with the airline or booking provider.",
                     "Fareflare is independent of Google and the airlines. Their names identify the sources or flights being discussed; they do not imply endorsement or a commercial relationship.")),
                 Section("Respect account and service boundaries.", (
                     "Keep your credentials private, connect only integrations you control, and do not attempt to access another account’s data or bypass capacity limits. Use the documented API and respect rate-limit responses.",
                     "Project code is available under the MIT license, including its warranty disclaimer. Dependencies and third-party services have their own terms. The code license does not grant access to anyone else’s account or third-party data."),
                     links=(Link("Read the MIT license", GITHUB_URL + "/blob/codex/link-monitoring/LICENSE"), Link("Privacy and data", "/privacy"))),
             )),
    )


def content_document(config: ProductConfig) -> dict:
    return {"github_url": GITHUB_URL, "product_name": config.product_name,
            "pages": [asdict(page) for page in public_pages(config)]}


def structured_data(page: Page, config: ProductConfig) -> dict:
    origin = config.public_url.rstrip("/")
    canonical = origin + page.path
    organization = {"@type": "Organization", "@id": origin + "/#organization", "name": config.product_name,
                    "url": origin + "/", "sameAs": [GITHUB_URL],
                    "logo": origin + "/assets/fareflare-mark.png"}
    graph: list[dict] = [organization,
        {"@type": "WebSite", "@id": origin + "/#website", "name": config.product_name,
         "url": origin + "/", "publisher": {"@id": organization["@id"]}, "inLanguage": "en-US"},
        {"@type": "WebPage", "@id": canonical + "#webpage", "url": canonical,
         "name": page.title, "description": page.description,
         "isPartOf": {"@id": origin + "/#website"}, "inLanguage": "en-US"}]
    if page.path in ("/", "/developers"):
        graph.append({"@type": "SoftwareApplication", "@id": origin + "/#application",
                      "name": config.product_name, "url": origin + "/", "applicationCategory": "TravelApplication",
                      "operatingSystem": "Web browser", "isAccessibleForFree": True,
                      "description": "Open-source flight price monitoring with free development access, a dashboard, API, MCP, and alert integrations.",
                      "license": GITHUB_URL + "/blob/codex/link-monitoring/LICENSE",
                      "publisher": {"@id": organization["@id"]}})
    if page.kind == "guide":
        graph.append({"@type": "BlogPosting", "@id": canonical + "#article", "headline": page.headline,
                      "description": page.description, "mainEntityOfPage": {"@id": canonical + "#webpage"},
                      "author": {"@type": "Organization", "name": config.product_name, "url": origin + "/about"},
                      "publisher": {"@id": organization["@id"]}, "datePublished": page.published,
                      "dateModified": page.modified, "inLanguage": "en-US", "isAccessibleForFree": True})
    if page.path != "/":
        crumbs = [{"@type": "ListItem", "position": 1, "name": "Home", "item": origin + "/"}]
        if page.kind == "guide":
            crumbs.append({"@type": "ListItem", "position": 2, "name": "Field notes", "item": origin + "/guides"})
        crumbs.append({"@type": "ListItem", "position": len(crumbs) + 1, "name": page.headline, "item": canonical})
        graph.append({"@type": "BreadcrumbList", "@id": canonical + "#breadcrumbs", "itemListElement": crumbs})
    return {"@context": "https://schema.org", "@graph": graph}


def render_body(page: Page, config: ProductConfig) -> str:
    """Escaped, useful HTML for the same content Angular will render."""
    sections = []
    for section in page.sections:
        body = "".join("<p>" + escape(p) + "</p>" for p in section.paragraphs)
        if section.bullets:
            body += "<ul>" + "".join("<li>" + escape(p) + "</li>" for p in section.bullets) + "</ul>"
        if section.code:
            body += "<pre><code>" + escape(section.code) + "</code></pre>"
        if section.links:
            body += "<p>" + " · ".join('<a href="' + escape(link.href, quote=True) + '">' + escape(link.label) + "</a>" for link in section.links) + "</p>"
        sections.append("<section><h2>" + escape(section.heading) + "</h2>" + body + "</section>")
    if page.path == "/guides":
        sections.append("<ul>" + "".join('<li><a href="' + guide.path + '">' + escape(guide.headline) +
                                        "</a><p>" + escape(guide.description) + "</p></li>"
                                        for guide in public_pages(config) if guide.kind == "guide") + "</ul>")
    byline = ("<p>By " + escape(config.product_name) + ' · <time datetime="' + str(page.published) + '">' +
              str(page.published) + "</time></p>" if page.kind == "guide" else "")
    article_open = "<article>" if page.kind == "guide" else ""
    article_close = "</article>" if page.kind == "guide" else ""
    return ('<a class="skip-link" href="#main-content">Skip to content</a>'
            '<header class="site-header"><div class="public-container site-header-inner">'
            '<a class="brand" href="/">' + escape(config.product_name) + '</a><nav class="site-nav" aria-label="Main navigation">'
            '<a href="/guides">Field notes</a><a href="/developers">Developers</a><a href="/about">Our story</a>'
            '<a href="/login">Sign in</a></nav></div></header>'
            '<main id="main-content" class="public-container public-article">' + article_open + '<p class="eyebrow">' + escape(page.eyebrow) +
            '</p><h1>' + escape(page.headline) + '</h1><p class="lead">' + escape(page.intro) + '</p>' + byline +
            "".join(sections) + article_close + '</main><footer class="public-footer"><div class="public-container">'
            '<a href="/privacy">Privacy</a> · <a href="/terms">Preview terms</a> · <a href="' + GITHUB_URL + '">GitHub</a>'
            '</div></footer>')


def render_document(shell: str, page: Page, config: ProductConfig, nonce: str, *, indexable: bool = True) -> str:
    """Add per-request metadata without reflecting query strings or untrusted HTML."""
    canonical = config.public_url.rstrip("/") + page.path
    # The build shell is trusted, but replace stale static SEO tags deterministically.
    shell = re.sub(r"<title\b[^>]*>.*?</title\s*>", "", shell, flags=re.I | re.S)
    shell = re.sub(r'<meta\b[^>]*(?:name|property)=[\"\'](?:description|robots|og:[^\"\']*|twitter:[^\"\']*)[\"\'][^>]*>', "", shell, flags=re.I)
    shell = re.sub(r'<link\b[^>]*rel=[\"\']canonical[\"\'][^>]*>', "", shell, flags=re.I)
    metadata = ('<title>' + escape(page.title) + '</title><meta name="description" content="' + escape(page.description, quote=True) + '">'
                '<meta name="robots" content="' + ('index, follow' if indexable else 'noindex, nofollow') + '">'
                '<link rel="canonical" href="' + escape(canonical, quote=True) + '">')
    for key, value in (("og:type", "article" if page.kind == "guide" else "website"), ("og:title", page.title),
                       ("og:description", page.description), ("og:url", canonical), ("og:site_name", config.product_name),
                       ("og:image", config.public_url.rstrip("/") + SOCIAL_IMAGE), ("og:image:width", "1280"),
                       ("og:image:height", "853"), ("og:image:alt", "A view of clouds through an aircraft window")):
        metadata += '<meta property="' + key + '" content="' + escape(value, quote=True) + '">'
    metadata += '<meta name="twitter:card" content="summary_large_image">'
    metadata += '<link rel="alternate" type="application/rss+xml" title="Fareflare field notes" href="/feed.xml">'
    if indexable:
        # JSON string escaping alone does not protect a script element's HTML parser.
        payload = json.dumps(structured_data(page, config), ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        metadata += '<script type="application/ld+json" nonce="' + nonce + '">' + payload + '</script>'
    if "</head>" in shell:
        shell = shell.replace("</head>", metadata + "</head>", 1)
    else:
        shell = '<!doctype html><html lang="en"><head><meta charset="utf-8">' + metadata + '</head><body><app-root></app-root></body></html>'
    body = render_body(page, config) if indexable else ('<main id="main-content" class="public-container public-article"><h1>' + escape(page.headline) + '</h1><p>' + escape(page.intro) + '</p><noscript>Enable JavaScript to use the account application.</noscript></main>')
    root = '<app-root ngCspNonce="' + nonce + '">' + body + '</app-root>'
    if re.search(r"<app-root\b", shell, re.I):
        shell = re.sub(r"<app-root\b[^>]*>.*?</app-root\s*>", lambda _: root, shell, count=1, flags=re.I | re.S)
    else:
        shell = re.sub(r'<div\s+id=[\"\']root[\"\'][^>]*>.*?</div>', lambda _: root, shell, count=1, flags=re.I | re.S)
    return shell


def private_page(path: str) -> Page:
    return Page(path, "Your account — Fareflare", "Manage your Fareflare account and monitors.",
                "Your account", "Your Fareflare account", "Sign in to manage your monitors and connections.")


def sitemap(config: ProductConfig) -> str:
    origin = config.public_url.rstrip("/")
    entries = "".join("<url><loc>" + escape(origin + page.path) + "</loc>" +
                      ("<lastmod>" + page.modified + "</lastmod>" if page.modified else "") + "</url>"
                      for page in public_pages(config))
    return '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + entries + '</urlset>'


def feed(config: ProductConfig) -> str:
    origin = config.public_url.rstrip("/")
    items = "".join("<item><title>" + escape(page.headline) + "</title><link>" + escape(origin + page.path) +
                    "</link><guid>" + escape(origin + page.path) + "</guid><description>" + escape(page.description) +
                    "</description></item>" for page in public_pages(config) if page.kind == "guide")
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>' +
            escape(config.product_name) + ' field notes</title><link>' + escape(origin + "/guides") +
            '</link><description>Practical notes on flight-price monitoring and integrations.</description>' +
            '<language>en-US</language>' + items + '</channel></rss>')
