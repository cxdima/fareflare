# Fareflare development status

Fareflare is available as a free, invite-only service and as MIT-licensed source.
Billing remains disabled. The current hosted release includes personal settings
and the softer Bootstrap theme. See [personal settings verification](SETTINGS_VERIFICATION.md)
for image digests, local checks and the completed production verification.

## Current development revision

- **Telegram bot — implementation pending verification:** native private-chat
  controls for adding Google Flights links with confirmation, paginated flights
  and recorded prices, pause/resume, retry, confirmed stopping, target-price and
  minimum-drop entry, new-low/rebound rules, muting and message settings. Alerts
  use concise formatted text and validated link buttons. Profile and webhook
  setup tools preserve private rollback snapshots. See the [Telegram guide](TELEGRAM.md)
  for user behavior and [operations](OPERATIONS.md#telegram-configuration) for
  deployment steps. These changes are not covered by the prior release counts below.
- **Personal settings:** saved IANA time zones, six regional formats, 12/24-hour
  clocks, Telegram detail options and silent delivery. An explicit message preview
  uses sample data without sending a notification. Existing global/route muting
  remains available. [Account preferences](ACCOUNT_PREFERENCES.md) documents
  defaults, partial updates, time-zone fallback and queue behavior.
- **Interface:** softer sage surfaces, deep green text, centrally themed Bootstrap
  buttons, plane icons for flight actions, underlined active navigation and a
  grouped account/sign-out area. The workspace layout remains unchanged.
- **Frontend stack:** Angular and Bootstrap remain the application stack. The
  standalone API now shares the portal's script-free HTML reference, removing its
  default Swagger/ReDoc applications. [The audit](STACK_AUDIT.md) distinguishes
  that change from the unverified browser-extension detection report.

Local verification completed with **761 backend tests, 92.58% coverage and 72
frontend checks**. The API and worker images passed 60 isolated checks with exact
source/build hashes. All **32 production checks** passed, including nine
accessibility scans, persistent preferences and disposable-account cleanup.
Loading-state regressions cover accessible refresh labels and navigation while
initial requests are pending.

## Previously verified capabilities

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
