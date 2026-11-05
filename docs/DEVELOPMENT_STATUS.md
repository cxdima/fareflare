# Fareflare development status

Updated November 5, 2026. Fareflare is a **live, free, invite-only development
release**, published under the [MIT license](../LICENSE).

- Application/API: <https://8jq9j5zhif.execute-api.us-east-1.amazonaws.com>
- Hosted MCP: <https://8jq9j5zhif.execute-api.us-east-1.amazonaws.com/mcp>
- Live configuration: billing disabled; constrained route searches enabled.

The original family application, Google watches, and collection schedule remain
in place. The shared Telegram bot's inbound webhook now routes through Fareflare,
which forwards family commands to the original Lambda. The original application
code and schedule were preserved; the webhook route itself has changed.

## Available capabilities

- **Customer accounts:** single-use invitations, password login, private browser
  sessions, CSRF protection, downloadable recovery codes, named expiring/revocable
  API keys, and password-confirmed account deletion. Recovery invalidates existing
  sessions, keys, OAuth grants, and Telegram bindings. No email reset service or
  payment provider is required.
- **Dashboard, API, and MCP:** shared monitor lifecycle, price history, alert
  policies, observed lows, optional rebound alerts, mute preferences, visible
  collection failures, and delivery retries. Hosted MCP uses the official SDK,
  explicit OAuth consent and PKCE, or customer API keys. The local stdio adapter
  remains available.
- **Selected-flight collection:** anonymous Google Flights browsing for US-English
  economy, one or two adults, USD/JPY, and nonstop one-way or fully selected round
  trips. Flight identity, passenger context, and eligible booking/summary prices
  must agree before recording an observation.
- **Route-search collection:** exact departure/arrival airports and date, one way,
  nonstop, one adult, USD, US-English, and Economy excluding Basic. The collector
  verifies complete price-sorted results and the cheapest matching selected fare.
  Each observation retains the actual flight and booking link. This compares the
  supported Google search results, not every fare available across the market.
- **Notifications:** customer Telegram connections through one-use private-chat
  links, durable dashboard alert history, and customer-owned HTTPS webhooks with
  ownership verification and Standard Webhooks signatures. Explicit webhook
  destinations never fall back to Telegram. Durable per-monitor FIFO delivery,
  retries, and dead-letter recovery provide at-least-once delivery semantics.
- **Operations:** separate API and browser-worker Lambdas, DynamoDB persistence,
  isolated Terraform state, immutable image digests, bounded browser reuse,
  sanitized diagnostics, worker health, and failure alarms. A fast browser startup
  failure receives one fresh-profile retry; a slow initial failure does not.

Customer limits are three monitors per account, a 900-second minimum requested
interval, and 20 distinct shared collection targets. Equivalent target identities
share collection while subscriptions stay private. These limits bound work; they
do not guarantee a polling deadline or zero AWS cost. Billing remains disabled
server-side, and attempts to enable its unfinished integration fail startup.

## Verification and live evidence

| Check | Latest verified result |
| --- | --- |
| Backend checks | 937 tests passed; 91.75% coverage; compile, Pyright, and Ruff passed |
| Dashboard | 10 browser tests passed; frontend build passed |
| Production API/OAuth/MCP | 47 checks passed, including official SDK interoperability |
| AWS selected-flight collection | USD 314 total observed before the final startup-retry update |
| Final deployed route-search smoke | Fresh USD 191 Economy Bundle; F9 2550 at 08:44:36 UTC |
| Shared bot routing | Cutover read back successfully; pending updates preserved |
| Family forwarding | Authenticated empty family update reached the legacy handler without an outgoing message |
| New consumer Telegram price alert | **Not yet verified with a real outgoing alert** |

The quoted fares are historical observations, not current booking guarantees.
The final deployed build passed a new public API/account and scheduled collection
smoke check. Its route monitor briefly exposed the shared target's previous
timeout before receiving a new validated observation; a cached quote was not
counted as fresh collection. The disposable smoke account was deleted afterward.
See [release verification](RELEASE_VERIFICATION.md) for deployed image digests,
timestamps, and the distinction between earlier and final-build observations.

SQLite and Moto DynamoDB tests cover account isolation and transactional races.
Local integrations exercise the API, MCP, browser behavior with recorded evidence,
and actual loopback TLS webhook delivery. Google has also produced intermittent
timeouts and a transient browser startup failure; collection backoff and stale
status remain visible rather than presenting old observations as fresh prices.

The [November 4 production verification](PRODUCTION_VERIFICATION.md) and its
[shadow deployment manifest](deployments/2026-11-04-shadow.json) remain historical
evidence for the earlier comparison release. They are not the active customer
release configuration. Earlier anonymous fixtures and browser-batch experiments
remain under `tests_next/fixtures/` and `docs/research/`.

## Remaining development work

- Verify a real consumer Telegram price alert from collection through receipt.
  Webhook routing and no-message forwarding checks do not establish that result.
- Measure sustained freshness, provider failure rates, browser startup behavior,
  and actual AWS costs. Successful spot checks do not establish production-scale
  reliability, free-tier eligibility, or a fixed notification latency.
- Attach an operator notification destination to CloudWatch alarms and rehearse
  complete application/data recovery. The webhook rollback script has mocked
  coverage; a full live rollback/recovery drill is a separate validation step.
- Validate additional passenger types, connections, cabins, markets, flexible
  dates, nearby airports, and explicit baggage/refund constraints before claiming
  support. Preserve unknown encoded constraints rather than merge distinct fares.
- Plan OAuth client retention before its permanent 1,000-client registration cap
  is reached. Billing and paid plans remain intentionally unfinished and disabled.
- Keep family migration explicit. Family `/mute` controls legacy alerts;
  Fareflare preferences and family-account connections are managed in its dashboard.
  Existing family watches have not silently become customer monitors.

Use [release verification](RELEASE_VERIFICATION.md), the [setup guide](FAREFLARE.md), [operations runbook](OPERATIONS.md), and
[API/webhook notes](NEXT.md) for supported workflows and rollback procedures.
