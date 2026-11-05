# Fareflare development release

Fareflare watches Google Flights itineraries and supported route searches, recording
the lowest eligible price it actually observes. It cannot promise the lowest fare
across the entire market or detect a price that appears and disappears between checks.

The [hosted development release](https://8jq9j5zhif.execute-api.us-east-1.amazonaws.com)
is free and invite-only, with billing disabled and route searches enabled. Current
collection supports:

- **Selected itineraries:** US-English economy, one or two adults, USD/JPY, and
  nonstop one-way or fully selected round trips.
- **Route searches:** exact departure and arrival airports, an exact date, one way,
  nonstop, one adult, USD, US-English, and economy excluding Basic. The collector
  compares eligible offers returned for that search; flexible dates, nearby-airport
  searches, and unrestricted market-wide comparisons are unsupported.

Unsupported inputs fail explicitly. Route observations retain the actual matching
flight and fare; the dashboard's **View flight** opens that observed offer's selected
Google Flights itinerary. Its price and availability can change before booking.

## Run locally

Use Python 3.12 and Node.js 22 or newer. Install the pinned Python dependencies:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-next-dev.lock
make product-build
make product-invite
make product-serve
```

Open the invitation URL in `.next/invitation.json`. The file contains a single-use
credential: keep it private. The dashboard, API, and MCP share
`http://127.0.0.1:8001`; local customer data is stored in `.next/product.sqlite3`.
Keep the recovery code shown at signup. There is no email reset service.

The HTTP server never launches Chrome. With local Chromium and ChromeDriver installed,
run a bounded worker against the same database:

```bash
PYTHONPATH=src .venv/bin/python -m gfpt_next.product_cli worker --limit 5
```

Use `--chrome-binary` and `--chromedriver` for explicit executable paths. Run the
worker periodically; each invocation collects only due monitors. Local delivery
supports the dashboard inbox and verified HTTPS webhooks. `make next-demo` and `make next-webhook-demo` exercise
the durable pipeline using clearly labeled synthetic prices without external calls.

## Product configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `GFPT_NEXT_PRODUCT_NAME` | `Fareflare` | Display name |
| `GFPT_NEXT_PUBLIC_URL` | Required in Lambda | Exact HTTPS application origin |
| `GFPT_NEXT_REGISTRATION_MODE` | `invite` | Single-use invites; `open` is opt-in |
| `GFPT_NEXT_BILLING_ENABLED` | `false` | No charges, checkout, or payment-provider calls |
| `GFPT_NEXT_SEARCH_ENABLED` | `false` | Opt in to the constrained route-search capability |
| `GFPT_NEXT_MONITOR_LIMIT` | `3` | Monitors per account |
| `GFPT_NEXT_MIN_INTERVAL` | `900` | Minimum requested interval in seconds |
| `GFPT_NEXT_GLOBAL_TARGET_LIMIT` | `20` | Shared collection capacity |

Billing deliberately refuses startup when enabled until a payment integration is
implemented. Identical target identities share collection; subscriptions and alert
preferences remain private. Limits constrain work, not guarantee a cloud bill or
polling deadline. Stale observations and collection errors are visible in the UI.

Self-hosted installations keep route searches off by default. To enable them locally,
start the API and worker in separate terminals with the same flag:

```bash
GFPT_NEXT_SEARCH_ENABLED=true make product-serve
# Separate worker terminal:
GFPT_NEXT_SEARCH_ENABLED=true PYTHONPATH=src \
  .venv/bin/python -m gfpt_next.product_cli worker --limit 5
```

`GET /v1/config` exposes `capabilities.route_searches`; the dashboard adapts its
supported-input guidance to that value. Use the [operations runbook](OPERATIONS.md)
for image rollout, validation, monitoring, and rollback.

## API, MCP, and notifications

Create a named API key in **API & MCP**; its secret is shown once. Send it as
`Authorization: Bearer KEY`. `/docs` lists routes and `/openapi.json` is the complete
request/response schema. Creation requests require an `Idempotency-Key` header;
reuse the same value after a network failure. Prices use integer minor units.

The remote MCP URL is the application origin followed by `/mcp`. It supports OAuth
authorization with explicit consent and PKCE, or a bearer API key for clients that
accept custom headers. The local stdio adapter remains available with `make next-mcp`.
OAuth access is scoped to MCP; customer API keys work with both interfaces.

Connect Telegram from the dashboard and start the bot using the generated link.
Without a connection, default alerts remain in the dashboard. An explicitly selected
webhook receives alerts only at that endpoint. Register and verify ownership before
selecting it. See [webhook setup](NEXT.md#customer-webhooks) for signatures, retries,
and receiver verification. Delivery is at least once; deduplicate using the event ID.
Verify a real customer Telegram price alert separately during rollout: dashboard
checks and authenticated webhook forwarding do not establish successful alert delivery.

## Deploy your own instance

`infra-next/` provisions a DynamoDB document store, an ARM64 browser worker, a separate
API Lambda, an HTTP API, a schedule, scoped IAM permissions, and CloudWatch alarms.
Build the original `Dockerfile` as `gfpt-browser-base`, then build `Dockerfile.next`
for collection. Build the dashboard before `Dockerfile.api`. Push both images to your
own ECR repositories and supply immutable digest URIs to Terraform.
Follow the [release procedure](OPERATIONS.md#release-api-and-worker-images) to keep
API and worker images, collection flags, and rollback records consistent.

The checked-in backend settings identify this project's existing state location.
For your own deployment, override `bucket`, `key`, and `region` with
`terraform init -backend-config=...`; set `expected_account_id`, `name`, and `region`
to your account. Start with empty image URIs to provision repositories and obtain
`application_url`, then apply the pinned images. Keep `billing_enabled=false` and
`registration_mode=invite`. Never reuse the original family's state key.

Issue a deployed invite explicitly:

```bash
PYTHONPATH=src .venv/bin/python -m gfpt_next.product_cli \
  --public-url https://YOUR-HTTP-API.execute-api.REGION.amazonaws.com \
  invite .next/invitation.json --table gfpt-next-YOUR-NAME \
  --aws-account YOUR_ACCOUNT_ID --region REGION
```

The account-ID guard must match the authenticated AWS identity. Configure Telegram
separately using Secrets Manager; never put bot tokens, invitation URLs, browser
cookies, state files, or API keys in Git. CloudWatch alarms expose failure counts;
attach an operator notification destination for unattended operation.

## Contribute

Run `make next-check`, `npm --prefix web run build`, and the dashboard browser tests
before submitting a change. Add behavioral tests around tenant isolation, money
units, delivery ordering, and provider evidence. Keep provider adapters, application
use cases, persistence, and delivery separate. A new collection capability needs a
real redacted fixture and explicit identity/party/price validation.

See [Repository Guidelines](../AGENTS.md). Do not use the stable family service as
a test fixture. The [MIT license](../LICENSE) covers project code; dependencies
retain their own licenses.
