# Product

<!-- impeccable:product-schema 1 -->

Recorded on 2026-11-10 from the repository (README, docs, shipped copy) and the
owner's redesign brief. No interview was held: the owner asked for work to
continue without check-ins. Lines marked *(inferred)* are read from the code and
copy, not confirmed in conversation.

## Platform

web

## Users

Travelers who already have a specific flight in mind and are waiting for a better
price before booking *(inferred)*. They arrive with a Google Flights tab open,
often on a phone, and come back only when something changes. A second, smaller
audience is developers who want the same monitors through an API, signed
webhooks or an MCP client.

## Product Purpose

Fareflare watches the price of a flight you picked. Paste a Google Flights link,
choose a rule, and it records the price on every check and tells you when it
reaches a new low or drops under your target. Success is a person booking with
confidence because they saw the recorded price history, not a guess.

## Positioning

- No Google account connection and no paid flight-data API: it reads the public
  price of the link you paste.
- Prices are recorded observations with a time stamp, never predictions.
- Open source under MIT; the hosted service at fareflare.dev is free.
- The same monitors are reachable from the dashboard, Telegram, a REST API,
  signed webhooks and remote MCP.

## Operating Context

- Entry: a Google Flights link for a selected itinerary or a supported route search.
- Checks start at 15-minute intervals. A fare can change between checks.
- Alerts arrive in the dashboard, in Telegram once connected, or at a verified webhook.
- Sign-in uses an email address or username and a password. There is no email
  reset: a recovery code shown once at sign-up is the only way back in.
- Booking happens elsewhere. Fareflare links back to the flight.

## Capabilities and Constraints

- Supported: US-English economy, one or two adults, USD or JPY, nonstop one-way
  or fully selected round trip; route searches for exact airports and date.
- Rules: new observed low, below a target price, optional alerts on a rise,
  minimum drop, pause, quiet hours, message styles.
- History by date range with CSV export; gaps in checking are shown as gaps.
- A public status page reports price checks, alerts and the website.
- The site ships a strict content security policy: no inline style attributes,
  no remote fonts or scripts, same-origin assets only.
- Public pages are also served as script-free HTML for crawlers.

## Brand Commitments

- Name: Fareflare. Mark: a wing-shaped F (`web/public/assets/fareflare-mark.png`).
- Voice: plain, direct, sentence case. Example fares are always labeled as examples.
- Never imply market-wide coverage, the cheapest fare, or that every change is caught.
- Owner's visual brief (2026-11-10): big but simple, "designer" pages; an oversized
  grotesk headline with an italic line, a soft lavender field and a phone in the
  hero; a light bento dashboard with bright signal chips and hatched bars;
  scroll-driven image sequences and generated 3D graphics.

## Evidence on Hand

- Real product screens and flows in `web/src/app`.
- Guides and legal copy in `src/fareflare/site_content.py`.
- Airline marks in `web/public/assets/airlines/`.
- No testimonials, customer logos, usage numbers or press. Do not invent any.

## Product Principles

1. Show what was recorded and when. Never present a price as current or guaranteed.
2. One move first: a link goes in, an alert comes out.
3. Say less about the system. A failed check gets one plain sentence.
4. Credentials and irreversible actions are always visibly separate from settings.

## Accessibility & Inclusion

WCAG 2.2 AA, checked with axe in the browser tests. State is never colour alone.
Motion respects `prefers-reduced-motion`. Native controls keep their keyboard behavior.
