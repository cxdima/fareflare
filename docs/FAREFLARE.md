# Fareflare setup

Fareflare watches Google Flights itineraries and supported route searches, recording
the lowest eligible price it actually observes. It cannot promise the lowest fare
across the entire market or detect a price that appears and disappears between checks.

The [hosted service](https://fareflare.dev)
is free with open registration, with billing disabled and route searches enabled. Current
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

Use Python 3.12 and Node.js 24 (CI) or a supported Angular 22 Node release.
The frontend uses Angular, Bootstrap, and external SCSS. Install the pinned Python dependencies:

```bash
python3.12 -m venv .venv
make install
make build
make invite
make serve
```

Open the invitation URL in `.fareflare/invitation.json`. The file contains a single-use
credential: keep it private. The dashboard, API, and MCP share
`http://127.0.0.1:8001`; the flight dashboard is at `/app`, and local customer data
is stored in `.fareflare/product.sqlite3`. Public guides and landing pages are also
served by Python, with crawlable initial HTML and matching structured data.
Keep the recovery code shown at signup. There is no email reset service.

The HTTP server never launches Chrome. With local Chromium and ChromeDriver installed,
run a bounded worker against the same database:

```bash
PYTHONPATH=src .venv/bin/python -m fareflare.product_cli worker --limit 5
```

Use `--chrome-binary` and `--chromedriver` for explicit executable paths. Run the
worker periodically; each invocation collects only due monitors. Local delivery
supports the dashboard inbox and verified HTTPS webhooks. `make demo` and `make webhook-demo` exercise
the durable pipeline using clearly labeled synthetic prices without external calls.

## Use the dashboard

Open **Filter flights**. **Find a flight** searches the loaded monitors by airport, flight number, or date.
Combine it with the **Status** filter to find watching, paused, stopped/departed,
or attention-needed monitors. If more pages exist, use **Load more monitors**;
search, filters, and the loaded counts do not include pages you have not loaded.

Each flight leads with its route, fare and most recent check. Open **Manage flight**
for the collection schedule, delivery destination, alert editing and pause/stop
controls. When adding a flight, **Collection and delivery** contains the optional
check interval and destination. **API & MCP** separates connection instructions;
the HTTP API view opens the API-key form, which can also be expanded in the MCP view.

Open **Price history** on a monitor to compare **All loaded**, **Past 7 days**, or
**Past 30 days**. Latest, lowest, highest, and change figures use only loaded
observations inside that range. **Load earlier observations** extends the data
available for those comparisons. The chart positions observations by time and
breaks its line across gaps longer than twice the monitor's requested interval.
The table retains each recorded total and, for route searches, the matching flight
when recorded. The chart does not fill missing checks with estimated prices.

**Export CSV** downloads the rows currently in view, most recent first. Columns
include an ISO 8601 UTC timestamp, integer `amount_minor`, `currency`, price basis,
fare name, matching flights, and source. USD uses cents (`19100` means $191.00);
JPY uses whole yen (`19100` means ¥19,100). Spreadsheet formula-like text is
prefixed with an apostrophe for safe import. CSV export is a browser download,
not a new server endpoint or a complete-history export.

**Account settings → Display** saves your time zone, regional date/number format and clock
preference. With no saved zone, the website uses device time and Telegram uses
UTC. Save a named zone to keep both consistent. Flight departure dates stay in
the airport's calendar; fare amounts retain their original currency.

Under **Notifications**, choose a Telegram message style (detailed, compact, classic with
emoji, or your own wording), optional flight/fare/timestamp details, silent delivery
and quiet hours. **Preview message** displays sample content without
saving changes or sending a notification. Global and route muting stop outgoing
alerts while collection continues. See [account preferences](ACCOUNT_PREFERENCES.md)
for defaults, partial API/MCP updates and formatting limits.

Collection waits for verified fare evidence within a shared 100-second budget,
leaving time inside the 120-second lease for cleanup and persistence. A transient
page update can be retried within that budget; an unsupported or mismatched fare
is not accepted. A timeout leaves the previous observation visible with its age
and collection status.

## Product configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `FAREFLARE_PRODUCT_NAME` | `Fareflare` | Display name |
| `FAREFLARE_PUBLIC_URL` | Required in Lambda | Exact HTTPS application origin |
| `FAREFLARE_REGISTRATION_MODE` | `invite` | Single-use invites; `open` is opt-in |
| `FAREFLARE_BILLING_ENABLED` | `false` | No charges, checkout, or payment-provider calls |
| `FAREFLARE_SEARCH_ENABLED` | `false` | Opt in to the constrained route-search capability |
| `FAREFLARE_MONITOR_LIMIT` | `3` | Monitors per account |
| `FAREFLARE_MIN_INTERVAL` | `900` | Minimum requested interval in seconds |
| `FAREFLARE_GLOBAL_TARGET_LIMIT` | `20` | Shared collection capacity |

Billing deliberately refuses startup when enabled until a payment integration is
implemented. Identical target identities share collection; subscriptions and alert
preferences remain private. Limits constrain work, not guarantee a cloud bill or
polling deadline. Stale observations and collection errors are visible in the UI.

Self-hosted installations keep route searches off by default. To enable them locally,
start the API and worker in separate terminals with the same flag:

```bash
FAREFLARE_SEARCH_ENABLED=true make serve
# Separate worker terminal:
FAREFLARE_SEARCH_ENABLED=true PYTHONPATH=src \
  .venv/bin/python -m fareflare.product_cli worker --limit 5
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
accept custom headers. The local stdio adapter is available with `make mcp` when configured with an API URL and key.
OAuth access is scoped to MCP; customer API keys work with both interfaces.

Connect Telegram from the dashboard and start the bot using the generated link.
Without a connection, default alerts remain in the dashboard. An explicitly selected
webhook receives alerts only at that endpoint. Register and verify ownership before
selecting it. See [webhook setup](INTEGRATIONS.md#customer-webhooks) for signatures, retries,
and receiver verification. Delivery is at least once; deduplicate using the event ID.
Use `/help` in Telegram for connection status and `/stop` to disconnect.
Verify a real Telegram price alert separately during rollout; a working connection
flow alone does not establish successful alert delivery.

## Deploy your own instance

`infra/` provisions a DynamoDB document store, an ARM64 browser worker, a separate
API Lambda, an HTTP API, a schedule, scoped IAM permissions, and CloudWatch alarms.
Build `Dockerfile.browser` as `fareflare-browser-base`, then build `Dockerfile.worker`
for collection. Build the dashboard before `Dockerfile.api`. Push both images to your
own ECR repositories and supply immutable digest URIs to Terraform.
Follow the [release procedure](OPERATIONS.md#release-api-and-worker-images) to keep
API and worker images, collection flags, and rollback records consistent.

Supply your own private S3 state backend with `terraform init -backend-config=...`;
set `expected_account_id`, `name`, and `region` to your installation. Start with
empty image URIs to provision repositories and obtain `application_url`, then apply
the pinned images. Keep `billing_enabled=false` and `registration_mode=invite`.
The [operations runbook](OPERATIONS.md#configure-your-installation) contains the
configuration templates and release sequence.

Issue a deployed invite explicitly:

```bash
PYTHONPATH=src .venv/bin/python -m fareflare.product_cli \
  --public-url https://YOUR-HTTP-API.execute-api.REGION.amazonaws.com \
  invite .fareflare/invitation.json --table fareflare-YOUR-NAME \
  --aws-account YOUR_ACCOUNT_ID --region REGION
```

The account-ID guard must match the authenticated AWS identity. Configure Telegram
separately using Secrets Manager; never put bot tokens, invitation URLs, browser
cookies, state files, or API keys in Git. CloudWatch alarms expose failure counts;
attach an operator notification destination for unattended operation.

## Contribute

Run `make check`, `npm --prefix web run build`, and the dashboard browser tests
before submitting a change. Add behavioral tests around tenant isolation, money
units, delivery ordering, and provider evidence. Keep provider adapters, application
use cases, persistence, and delivery separate. A new collection capability needs a
real redacted fixture and explicit identity/party/price validation.

Read [CONTRIBUTING.md](../CONTRIBUTING.md) for test setup and pull request guidance.
The [MIT license](../LICENSE) covers project code; dependencies retain their own
licenses. Use synthetic accounts and data for tests.
