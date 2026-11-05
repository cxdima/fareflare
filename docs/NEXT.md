# Link-based monitoring

Development lives in the sibling `google-flights-price-tracker-next` worktree on
`codex/link-monitoring`. Production work in the existing AWS account is authorized.
The running family tracker remains usable during the transition. Existing
`AGENTS.md`, family application code, Google watches, and the family schedule are
preserved. The shared Telegram webhook now enters Fareflare and forwards family
commands to the original handler. The customer development release is live, free,
and invite-only; see the [current setup guide](FAREFLARE.md) and
[operations runbook](OPERATIONS.md). The [November 4 production verification](PRODUCTION_VERIFICATION.md)
describes the earlier notification-suppressed comparison release.

Read [implementation status](DEVELOPMENT_STATUS.md) for verified capabilities,
results, and remaining release gates. [The architecture review](ARCHITECTURE_REVIEW.md)
records the original findings and rationale; several of its prototype gaps are now fixed.

## Local development

```bash
make next-install
make next-init         # Exclusive creation; never overwrites existing credentials.
make next-demo         # Synthetic prices; temporary database, no external services.
make next-webhook-demo # API onboarding, signed alerts and durable retry; synthetic, offline.
make next-serve        # Authenticated API on 127.0.0.1:8001; /docs for API reference.
make next-mcp          # Stdio MCP adapter while the API is running.
make next-quote        # Anonymous live quote of the example itinerary.
make next-collect      # One collection pass; queue alerts without sending them.
make next-worker       # One bounded pass; explicitly suppress its queued alerts.
make next-check       # Compile, types, lint, legacy + new tests, >=80% new-code coverage.
```

Use Python 3.12. `.next/config.json` stores local credentials and the SQLite path
with private permissions. API requests use a bearer key; creation also requires
an 8–128 character `Idempotency-Key`. Keys have a 30-day request-deduplication window.
Public API ingestion accepts full selected-itinerary URLs and Google `/flights/s/`
share links. Import itself remains offline; only the restricted resolver performs network I/O.

The CLI's `inspect URL` decodes a full link offline. `quote URL` checks a public
booking page; no Google account, watch registration, or Telegram message is involved.
The importer can represent more itineraries than the currently validated collector.
The configured API checks collector capabilities before accepting a monitor.

## API, MCP, and credentials

Both interfaces expose creation, listing, history, pause/resume/cancel, alert
inspection/retry, collection retry, policy updates, and global/route muting.
History and alert lists return `next_cursor`; follow it with the same endpoint.
Lows mean lowest observed since monitoring began, or a verified imported baseline.
Collection timestamps do not prove when Google's upstream fare last refreshed.

The local MCP adapter is stdio, using the official SDK; it calls the API and owns no scheduler.
Set `GFPT_NEXT_API_URL` and `GFPT_NEXT_API_KEY` for a different API. Remote URLs
require HTTPS. The deployed customer application also exposes hosted MCP at `/mcp`
with OAuth/PKCE or a customer API key; see [API and MCP setup](FAREFLARE.md#api-mcp-and-notifications).

Issue a revocable local key into a new private file:

```bash
PYTHONPATH=src .venv/bin/python -m gfpt_next.cli key-create alice .next/alice-key.json
PYTHONPATH=src .venv/bin/python -m gfpt_next.cli key-revoke alice CREDENTIAL_ID
```

New keys expire after 90 days; only their hashes are stored. Issue a replacement
before revoking the old key. Initial config-file keys remain bootstrap credentials;
remove them from `api_keys` and restart the API after migrating clients to issued keys.
Authenticated requests are limited to 120/minute per tenant. Limits do not substitute
for public-ingress abuse protection or measured commercial capacity.

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
5. Run a local collector and delivery worker, or deliver previously queued alerts:

   ```bash
   PYTHONPATH=src .venv/bin/python -m gfpt_next.cli worker --limit 5 --deliver-webhooks
   PYTHONPATH=src .venv/bin/python -m gfpt_next.cli deliver-webhooks
   ```

The existing `make next-worker` still suppresses notifications. Do not use shadow
mode when intending to deliver a queued alert: suppression is terminal.

Destinations must be public HTTPS URLs on port 443. Each attempt checks every DNS
answer and connects to a validated IP while retaining certificate/hostname checks.
Redirects and environment proxies are disabled. DNS/socket work has a total deadline;
response bodies are not downloaded. Ten non-deleted endpoints are allowed per tenant.

Alerts use `type: "flight.price_alert"`; `data` contains `monitor_id`, `reason`,
`observation`, and `itinerary`. Prices retain their currency, minor units, and timestamp.
The `webhook-id`, `webhook-timestamp`, and `webhook-signature` headers follow
[Standard Webhooks](https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md).
Use `gfpt_next.webhook_http.verify_webhook(secret, raw_body, headers)` or a compatible
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
them. Production delivery remains suppressed until explicitly configured.

## Collection cost and batching

Flight collection is operated by this project; paid flight-data APIs are excluded
from the implementation plan. Existing shared targets avoid duplicate checks for
identical pricing inputs. Customer-specific policies and notification destinations
do not create extra targets.

`PublicGoogleFlightsProvider.batch()` reuses one anonymous browser for compatible
targets, up to 20 attempts. It resets page/cookies/storage between targets, opens a
new browser when pricing context changes, and discards a failed session. Every quote
still passes itinerary/party/currency/fare validation. The worker closes Chrome
before processing notifications and reports `browser_launches`/`browser_reuses`.
The time budget can stop a batch before its requested target limit.

The bounded local experiment in [the batch evidence](research/collector-batch-2026-11-05.json)
validated two itineraries with one launch and one reuse in 9.456 seconds. The
disposable-browser comparison included a timeout, so it does not establish a
speedup ratio or production cost. Search-result collection and structured-response
optimisation remain separate work; this change does not claim they are implemented.

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
The prototype permits 100 non-cancelled monitors per tenant and 1,000 subscribers per
target; capacity must be measured before increasing limits.

## Family migration

Prepare a private JSON export following `plan_migration` in `migration.py`: version 1,
`currency_units_verified: true`, explicit `currency` and `unit` (`major` or `minor`),
legacy chat-ID-to-tenant `owners`, the legacy `preferences`, and a `manifest` with
selected `search_url`, `price`, and verified `low_price` for each flight. Do not infer
currency from a dollar sign or seed a historical minimum from the latest history row.

```bash
PYTHONPATH=src .venv/bin/python -m gfpt_next.cli migrate .next/family-export.json
PYTHONPATH=src .venv/bin/python -m gfpt_next.cli migrate .next/family-export.json --apply
```

Preview performs no writes. Apply creates paused local monitors and copies preferences;
repeating the same import is safe. It does not edit old data or present imported prices
as live observations. Resume only the monitors selected for a comparison run.

## Historical production comparison and rollback

This section records the November 4 shadow comparison. Current customer deployment,
shared-bot routing, and rollback instructions are in [OPERATIONS.md](OPERATIONS.md).
The historical image and inputs are recorded in `docs/deployments/2026-11-04-shadow.json`;
do not overwrite the current release inputs with that older manifest.
Terraform uses `gfpt-next-production/terraform.tfstate` in the existing private,
versioned S3 state bucket. It never reads or writes the family stack’s state key.
An account guard rejects the wrong AWS account, and lifecycle protection prevents
accidental table, repository, or worker deletion.

`infra-next/` defines additive resources in the current AWS account using separate
Terraform state and a new document table; its schema cannot replace the old price table.
It contains no Google credentials and no Telegram webhook registration. The old
whole-stack deployment shortcuts remain guarded in this worktree.

```bash
# Use the immutable browser-base URI recorded in the deployment manifest.
docker buildx build --platform linux/arm64 --provenance=false --load \
  --build-arg BROWSER_BASE=IMMUTABLE_BASE_IMAGE_URI \
  -f Dockerfile.next -t gfpt-next:local .
terraform -chdir=infra-next init
terraform -chdir=infra-next plan
```

Before planning an existing deployment from a fresh checkout, restore the nonsecret
`terraform_inputs` from the deployment manifest into the ignored
`infra-next/production.auto.tfvars.json`. Otherwise missing image inputs would
request removal, which lifecycle protection rejects.

For a new installation, the first apply can create storage/ECR only. Build and test the ARM64 image, push it
to the returned repository, then set `image_uri` to its immutable `@sha256:` URI.
The new worker has one reserved invocation, 2 GB memory, and a 180-second timeout.
Its five-minute schedule defaults disabled; the deployed comparison enables it for
one sample monitor. `worker_max_targets` defaults to one; it can be set to an integer
from 1–20 to enable bounded browser reuse. The sample's
requested interval is 900 seconds; five-minute dispatch granularity and retries can
extend the actual gap. This is not a sub-minute or fixed-latency service promise.

With `product_delivery_enabled=false`, `telegram_secret_arn` empty, and
`webhook_delivery_enabled=false` (the defaults),
the worker suppresses delivery and never reads a Telegram secret. Setting
`webhook_delivery_enabled=true` enables verified webhook delivery; combining it
with a Telegram secret enables explicit routing to either channel. Monitor
`health:worker`, CloudWatch counters/logs, and Lambda errors.
Use routed delivery for mixed Telegram/webhook subscriptions. A delivery targeting
a runtime-disabled channel consumes normal retries and may require explicit
redrive after that channel is enabled; it never changes destinations.
`alerts_suppressed` distinguishes shadow delivery from actual sends; `alerts_sent`
must stay zero during comparison.
Before enabling delivery, drain old shadow work and compare identity, freshness,
and resource cost. A Telegram secret must contain `bot_token` and a `recipients`
map from tenant to numeric chat ID; recipients never come from API request bodies.

The later Fareflare release uses product delivery and a shared-bot routing adapter;
family commands still execute in the original service. This is not a completed
migration of family watches or notifications. Use the current operations runbook
to restore a saved webhook route or disable Fareflare's schedule without changing
the family schedule, and validate recovery before claiming migration complete.
