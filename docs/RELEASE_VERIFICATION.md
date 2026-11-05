# Fareflare development release verification

Verified on **2026-11-05 UTC**. This record describes the invite-only development
release at <https://8jq9j5zhif.execute-api.us-east-1.amazonaws.com>, including the
final browser-startup retry update. It supersedes the November 4 shadow report
for current customer functionality. See [setup](FAREFLARE.md) and
[operations and rollback](OPERATIONS.md).

## Deployed configuration

- Billing disabled; invite-only registration; MIT-licensed code.
- Dashboard, REST API, and OAuth-capable remote MCP at `/mcp` (20 tools).
- Three monitors per account, minimum requested interval 900 seconds, 20 distinct
  shared collection targets. The dispatcher wakes every minute and collects up
  to five due targets. These are development capacity limits, not timing guarantees.
- Selected-itinerary collection and constrained route-search collection enabled.
  Search supports exact airports/date, one way, nonstop, one adult, USD,
  US-English, and economy excluding Basic.
- Default delivery uses a connected Telegram account or the dashboard inbox;
  explicitly selected, verified webhooks use signed delivery with durable retries.

Immutable deployed images in account `851725466918`, region `us-east-1`:

| Repository | Image digest |
| --- | --- |
| `gfpt-next-production-api` | `sha256:3b348d32bb8e0cfb42ddcb0d4495c44191797be30e7f427bfb7f3b97c03916e1` |
| `gfpt-next-production` | `sha256:12b348b355bf26af6a0ac4c96bd68c3cedb4a66f280e892794c72abf1da7589d` |

The final Terraform plan updated only these two Lambda image references. Apply
completed successfully, and AWS readback matched both digests.

## Verification performed

| Check | Result |
| --- | --- |
| `make next-check` | Compile, Pyright, Ruff, and **937 tests passed**; **91.75%** next-generation backend coverage |
| Dashboard build and Playwright | **10 tests passed**, including the real local FastAPI/SQLite portal, keyboard/accessibility checks, and mobile layout |
| Frontend production dependency audit | Zero reported vulnerabilities at verification time |
| Terraform | Formatting and validation passed; saved deployment plan reviewed |
| Production dashboard | Signup, secure session, monitor creation, API/MCP settings, Telegram availability, account deletion; no observed CSP/runtime errors or axe violations |
| Production OAuth/MCP | **47 checks passed** using the official MCP SDK: consent/PKCE, tool calls, refresh rotation, replay rejection, revocation, and audience isolation |
| Final deployed API smoke | Invite signup, CSRF enforcement, API-key creation/revocation, repeated warm MCP calls, discovery, and fresh scheduled collection passed |
| Packaging | ARM64 API password hashing and static assets checked; browser worker started and closed Chrome with a read-only root and bounded temporary storage |

Production evidence files and disposable credentials are retained privately under
ignored `.next/`; they are not part of the public repository. Smoke accounts were
deleted after verification. Webhook signatures, ownership verification, SSRF
controls, retries, and ordering were exercised locally; this release did not send
a live alert to an external customer webhook.

## Actual scheduled price observations

For DEN–DFW on March 14, 2027:

- **08:11:23 UTC:** selected United itinerary, **USD 314 Economy**, verified by
  the scheduled AWS worker before the final startup-retry update.
- **08:14:34 UTC:** route-search result, **USD 191 Economy Bundle**, Frontier
  **F9 2550**, verified in AWS before that update.
- **08:44:36 UTC:** the final deployed build collected a **new USD 191 Economy
  Bundle observation for F9 2550**, after a public API smoke account created its
  monitor. Identity, passenger count, and fare eligibility evidence all passed.
  The response retained the actual selected offer and booking URL.

The final route test saw the shared target's previous `timeout` state before the
new observation arrived. Earlier rollout runs also encountered a fast browser
startup failure and selected-summary/search-results timeouts. One fresh-profile
retry now handles fast startup failures; page failures still back off and remain
visible. A cached price alone was never counted as fresh collection evidence.

## Existing family service and Telegram

AWS readback confirmed the original `gfpricetracker` Lambda image and last-modified
timestamp remained unchanged. Its schedule remains enabled at `rate(15 minutes)`.
Original application source was not changed.

The shared bot's webhook now points to Fareflare. Existing family commands are
forwarded to the original handler. Authenticated empty-message forwarding and
duplicate handling were verified without sending a chat message. The actual
cutover preserved pending updates; final Telegram readback showed zero pending
updates and no webhook error. A private rollback snapshot exists, but a live
rollback was not performed.

**A real new customer Telegram price alert has not yet been verified.** Connect
from the dashboard and verify delivery during onboarding. Family `/mute` controls
the original tracker; Fareflare alert preferences are managed separately.

## Preview limitations

This release records the lowest eligible price it observes within supported
Google Flights searches. It cannot establish the market-wide minimum or detect
every short-lived drop between checks. Google page changes and timeouts can delay
collection; there is no availability or notification-latency SLA.

Broader itinerary coverage, sustained capacity/cost measurements, an operator
notification destination for alarms, and a production recovery drill remain
necessary before an unrestricted or paid launch. Billing intentionally refuses
startup if enabled until a payment integration is implemented. The current release
is ready for invited development use, not a claim of paid-service readiness.
