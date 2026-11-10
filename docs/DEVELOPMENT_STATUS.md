# Fareflare development status

Fareflare is available as a free, open-registration service and as MIT-licensed source.
Billing remains disabled. The current hosted release includes native Telegram
flight controls, focused account settings and the refined Angular/Bootstrap
workspace. See [workspace design verification](UI_REFINEMENT_VERIFICATION.md) for
visual review and release evidence, and [Telegram verification](TELEGRAM_VERIFICATION.md)
for the preceding bot release. Actual Telegram receipt has not been verified.

## Public domain release

The service is now https://fareflare.dev with public signup and 20 monitors per
account. Terraform manages Route 53, ACM and the Regional custom domain. The
Python package and environment keys use `fareflare`/`FAREFLARE_`. Signup-specific
and account-route rate limits supplement existing gateway and API protections.
[Public launch verification](PUBLIC_LAUNCH.md) records migration, security limits,
949 backend tests, 78 frontend tests and 45 live checks. Existing deployment IDs
and stored account data are preserved. Shared collection remains capped at 20
unique targets independently of the per-account monitor limit.

## Current development revision

- **Telegram bot — deployed:** native private-chat
  controls for adding Google Flights links with confirmation, paginated flights
  and recorded prices, pause/resume, retry, confirmed stopping, target-price and
  minimum-drop entry, new-low/rebound rules, muting and message settings. Alerts
  use concise formatted text and validated link buttons. Profile and webhook
  setup tools preserve private rollback snapshots. See the [Telegram guide](TELEGRAM.md)
  for user behavior and [operations](OPERATIONS.md#telegram-configuration) for
  deployment steps. The bot descriptions and private-chat command menu have been
  applied and read back, and the webhook now accepts callback updates.
- **Personal settings:** saved IANA time zones, six regional formats, 12/24-hour
  clocks, Telegram detail options, message styles and templates, silent delivery
  and quiet hours. An explicit message preview
  uses sample data without sending a notification. Existing global/route muting
  remains available. [Account preferences](ACCOUNT_PREFERENCES.md) documents
  defaults, partial updates, time-zone fallback and queue behavior.
- **Interface:** softer sage surfaces, deep green text and themed Bootstrap
  controls. Flight buttons use a large clipped airplane texture. Route, price and
  freshness lead; filters and management details open on demand. Airline artwork
  is contained and spaced consistently. Settings use Display, Notifications,
  Connections and Security sections that retain unsaved drafts. Native pickers,
  mobile alerts and API reference margins follow the shared theme.
- **Frontend stack:** Angular and Bootstrap remain the application stack. The
  standalone API now shares the portal's script-free HTML reference, removing its
  default Swagger/ReDoc applications. [The audit](STACK_AUDIT.md) distinguishes
  that change from the unverified browser-extension detection report.

Local verification completed with **943 backend tests, 92.83% coverage and 78
frontend checks**. The API image passed 39 isolated checks with 63 matching
source/build hashes. Pyright, Ruff, frontend build/types/formatting and the changed
implementation secret scan passed. Actual Playwright MCP review covered desktop
and mobile public, authentication and workspace states; 66 normal-color axe scans
were clean. Two forced-colors contrast flags are documented separately.
All 45 live browser/account checks passed, including 15 accessibility scans and
disposable-account deletion. No browser runtime, CSP, asset or server errors were
recorded.

The reviewed design release changed only the API Lambda image. Readback confirms
its update succeeded, environment and concurrency were preserved, and the worker
and original tracker retained their images and modification times. Billing stays
disabled and registration open. This release did not change bot routing or
send live Telegram messages. Prior [bot](TELEGRAM_VERIFICATION.md) and
[settings](SETTINGS_VERIFICATION.md) releases retain separate verification records.

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

The hosted configuration allows 20 monitors per account, a 900-second minimum
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
