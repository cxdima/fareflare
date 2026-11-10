# API, MCP, and delivery

Fareflare exposes the same account-owned monitors through its dashboard, HTTP API,
and MCP. Start with [local setup](FAREFLARE.md); use [operations](OPERATIONS.md) for
AWS deployment. The HTTP API serves its route reference at `/docs` and its complete
schema at `/openapi.json`.

## API, MCP, and credentials

Both interfaces expose creation, listing, history, pause/resume/cancel, alert
inspection/retry, collection retry, policy updates, and account preferences.
Preferences include global/route muting, regional formats and Telegram message
options. `PUT /v1/preferences` preserves omitted fields; MCP exposes
`get_preferences` and `set_preferences`. See the [complete preference contract](ACCOUNT_PREFERENCES.md).
Monitor, history and alert lists return `next_cursor`; follow it with the same endpoint.
Monitor pages also include `active_count`: account quota usage across all pages,
including paused monitors and excluding stopped or expired monitors with released quota.
Lows mean lowest observed since that monitor began tracking.
Collection timestamps do not prove when Google's upstream fare last refreshed.

The local MCP adapter is stdio, using the official SDK; it calls the API and owns no scheduler.
Set `FAREFLARE_API_URL` and `FAREFLARE_API_KEY` for a different API. Remote URLs
require HTTPS. The deployed customer application also exposes hosted MCP at `/mcp`
with OAuth/PKCE or a customer API key; see [API and MCP setup](FAREFLARE.md#api-mcp-and-notifications).

Create a named API key in **API & MCP**. Its secret is shown once; save it in your
client's secret store. Send it as `Authorization: Bearer YOUR_API_KEY`. Keys expire
after 90 days and can be revoked from the dashboard. Browser sessions use HttpOnly
cookies and CSRF protection. Account recovery invalidates existing API keys.

Creation requests require an 8–128 character `Idempotency-Key`. Reuse the same key
when retrying an unchanged request after a network failure. Deduplication records
last 30 days. API limits do not replace public-ingress protection or measured
collection capacity.

The route reference is script-free HTML shared by the standalone API and hosted
portal. `/openapi.json` remains available for clients and tooling; Swagger UI and
ReDoc are not served. See the [frontend stack audit](STACK_AUDIT.md).

## Customer webhooks

The API's `/docs` page and MCP expose the same workflow:

1. `POST /v1/webhooks` with `{"url":"https://your-host.example/prices"}` and an
   `Idempotency-Key`. Save the returned `signing_secret` privately; it is returned
   only on initial creation. A replay returns metadata without the secret. If the
   original response is lost, delete the endpoint and register a replacement.
2. Configure the receiver to verify Standard Webhooks signatures. Call
   `POST /v1/webhooks/{id}/challenge`. A signed `webhook.verification` event reaches
   the receiver with `data.token` and `data.expires_at`. A 2xx response alone does
   not activate the destination, and the API never returns the token.
3. Submit that token to `POST /v1/webhooks/{id}/verify` as `{"token":"..."}` within
   ten minutes. Challenges have a 60-second cooldown and five verification attempts.
4. Create a monitor with the usual URL/policy and `"webhook_id":"<verified-id>"`.
   The selected endpoint is immutable for that monitor. To change destinations,
   create a replacement monitor and cancel the old one.
5. Run the product worker against the same local database, or enable scheduled
   product delivery in your deployment:

   ```bash
   PYTHONPATH=src .venv/bin/python -m fareflare.product_cli worker --limit 5
   ```

Destinations must be public HTTPS URLs on port 443. Each attempt checks every DNS
answer and connects to a validated IP while retaining certificate/hostname checks.
Redirects and environment proxies are disabled. DNS/socket work has a total deadline;
response bodies are not downloaded. Ten non-deleted endpoints are allowed per tenant.

Alerts use `type: "flight.price_alert"`; `data` contains `monitor_id`, `reason`,
`observation`, `itinerary`, and `previous`. `previous.price_minor` and
`previous.low_minor` are the monitor's own last price and lowest price before this
observation, or `null` for its first; an alert queued by an earlier release omits
`previous`. Prices retain their currency, minor units, and timestamp. A monitor
read from `GET /v1/monitors` carries the same running low as `low_minor`, `null`
until its first price is recorded.
`observation.schedule` lists the airport-local departure and arrival clock times
for each direction (`departs`, `arrives` as 24-hour `HH:MM`, `arrival_day_offset`,
`duration_minutes`), or is `null` when they could not be read with certainty.
The `webhook-id`, `webhook-timestamp`, and `webhook-signature` headers follow
[Standard Webhooks](https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md).
Use `fareflare.webhook_http.verify_webhook(secret, raw_body, headers)` or a compatible
library. Verify raw bytes before parsing, check timestamp freshness, and durably
deduplicate `webhook-id`. The event body and ID remain stable across retries;
the signature timestamp is refreshed. Acknowledge with 2xx after durable acceptance.

`GET /v1/alerts` exposes status/attempt counts and the selected `webhook_id`.
Five failed attempts produce a dead letter; `POST /v1/alerts/{id}/retry` redrives it.
`POST /v1/webhooks/{id}/disable` suppresses queued alerts from the old endpoint
generation. A new challenge/verification can reactivate the same URL. Old dead
letters still require redrive, which suppresses them and unblocks later alerts.
`DELETE /v1/webhooks/{id}` permanently retires it and removes its signing secret.
A request already in flight can finish after disabling. Explicit webhook deliveries
never fall back to Telegram. URLs are immutable; register a new endpoint to replace one.

Endpoint secrets are private application records, covered by DynamoDB encryption
at rest and local SQLite file permissions. API list/get/history responses exclude
them. Deployed delivery must be explicitly enabled in Terraform.

## Collection cost and batching

Fareflare collects public Google Flights pages directly. Shared targets avoid duplicate checks for
identical pricing inputs. Customer-specific policies and notification destinations
do not create extra targets.

`PublicGoogleFlightsProvider.batch()` reuses one anonymous browser for compatible
targets, up to 20 attempts. It resets page/cookies/storage between targets, opens a
new browser when pricing context changes, and discards a failed session. Every quote
still passes itinerary/party/currency/fare validation. The worker closes Chrome
before processing notifications and reports `browser_launches`/`browser_reuses`.
When Google shows its own error page in place of a flight, the collector loads the
same link again, at most twice, and reports the count as `page_reloads`.
A browser that dies as it starts or as the link loads is replaced once, with a new
empty profile, and counted as `browser_restarts`.
In Lambda, Chromium runs without its sandbox and zygote and with renderers in their
own processes; `--single-process` crashed the first launch after a slow start.
The time budget can stop a batch before its requested target limit.

The bounded local experiment in [the batch evidence](research/collector-batch-2026-11-05.json)
validated two itineraries with one launch and one reuse in 9.456 seconds. The
disposable-browser comparison included a timeout, so it does not establish a
speedup ratio or production cost. The constrained route-search collector is documented in the setup guide. Batching
does not broaden the inputs either collector supports.

## Durable pipeline and patterns

`contracts.py` owns provider-independent values and ports. `MonitoringService`
acts as the application facade; `DeliveryOutbox` owns ordered delivery. Browser,
SQLite/DynamoDB, Telegram, HTTP, and MCP are adapters. Pure alert functions implement
rule strategies; explicit state transitions make retries idempotent. The durable
observation/event/outbox chain implements fan-out without in-memory callbacks.

Only a monitor's queue head can be sent. Failure retries that head, and a dead letter
blocks later alerts until its owner retries it. Other monitors continue. A crash
between external acceptance and durable acknowledgment can produce a duplicate;
messages carry a stable alert ID. Customer intent survives collection failures.
A collector must finish inside its lease; late writes are rejected.

History and completed delivery records expire after 365 days; processed events after
seven days. DynamoDB applies TTL asynchronously. Local SQLite exposes
`purge_expired(now)` for bounded maintenance. Pending/dead-letter work is retained.
The account application defaults to three monitors per account and 20 shared
targets. Store-level caps also constrain subscriber fan-out. Measure capacity and
resource costs before increasing these limits.
