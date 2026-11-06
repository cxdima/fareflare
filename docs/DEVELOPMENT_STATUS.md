# Fareflare development status

Fareflare is available as a free, invite-only service and as MIT-licensed source.
Billing remains disabled. The current interface and release checks are documented
in [website verification](WEBSITE_VERIFICATION.md).

## Available

- **Accounts:** invitations, password login, HttpOnly sessions, recovery codes,
  expiring/revocable API keys, and password-confirmed deletion.
- **Monitoring:** selected itineraries and constrained route searches, price
  history with 7-day/30-day filters, scoped low/high/change comparisons, CSV
  export, observed-low/threshold/rebound rules, pause/mute controls, visible
  collection failures, and retries. Monitor search/status filters apply to loaded
  pages; more monitors can be loaded explicitly.
- **Integrations:** HTTP API, hosted OAuth/PKCE MCP, Telegram connections, and
  verified HTTPS webhooks with Standard Webhooks signatures.
- **Delivery:** durable per-monitor ordering, retries, stable event IDs, and
  dead-letter recovery. Delivery is at least once.
- **Website:** Angular/Bootstrap dashboard, public guides, crawlable initial HTML,
  matching JSON-LD, canonical/social metadata, sitemap, and RSS. Account forms
  provide inline validation, password visibility controls, and pending feedback.
- **Operations:** separate API and browser-worker Lambdas, DynamoDB persistence,
  explicit Terraform state configuration, bounded browser reuse, worker health,
  sanitized diagnostics, and failure alarms.

Collector navigation and evidence waits now share a 100-second budget within the
120-second collection lease. Transiently incomplete fare evidence can settle
within that budget; identity, currency, and fare checks still apply. This improves
handling of page updates without expanding supported flight coverage or raising
the configured polling frequency.

The hosted configuration allows three monitors per account, a 900-second minimum
requested interval, and 20 shared collection targets. These limits constrain work;
they do not guarantee a polling deadline or zero infrastructure cost. See
[setup](FAREFLARE.md) for exact flight coverage.

## Evidence

Backend tests cover account isolation, transaction races, quote validation,
idempotency, and delivery failures with SQLite and Moto DynamoDB. Browser tests
exercise the built portal under its actual CSP, including account lifecycle,
keyboard interaction, narrow-screen layout, and accessibility checks.

Scheduled AWS checks have recorded validated selected-flight and route-search
observations. [Collector and integration verification](RELEASE_VERIFICATION.md)
records those samples and their limits. A successful sample is not sustained
reliability evidence.

## Remaining work before unrestricted access

- Verify a consumer Telegram price alert from collection through actual receipt.
  A successful connection flow alone does not establish end-to-end delivery.
- Measure sustained freshness, provider failure rates, browser startup behavior,
  and AWS cost under multiple active accounts.
- Attach an operator destination to CloudWatch alarms and rehearse complete data
  recovery and application rollback.
- Validate additional passenger types, connections, cabins, markets, flexible
  dates, nearby airports, and explicit baggage/refund constraints before enabling them.
- Define OAuth client retention before the permanent 1,000-client cap is reached.

Payments are intentionally out of scope for the free development service. Enabling
the billing flag fails startup until a payment integration is implemented.
