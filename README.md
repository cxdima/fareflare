# Fareflare

Open-source flight price monitoring with Telegram alerts, webhooks, an HTTP API, and MCP.

Paste a supported Google Flights link, choose an alert rule, and Fareflare records
prices as it checks. See the latest fare, previous observations, and collection
status in one dashboard. Connect Telegram or a verified webhook to receive alerts
when a price meets your rule.

[Open Fareflare](https://fareflare.dev) ·
[Local setup](docs/FAREFLARE.md) · [Documentation](docs/README.md) ·
[Contribute](CONTRIBUTING.md)

![Fareflare flight dashboard with example data](docs/design/dashboard-desktop.png)

## What it does

- Tracks selected itineraries and supported route searches without a customer
  Google login or a paid flight-data API.
- Explores recorded prices by date range, with scoped comparisons, visible gaps,
  and CSV exports.
- Finds loaded monitors by airport, flight number, date, or status; loads further
  pages when available.
- Supports new-low, target-price, and optional rebound alerts, with pause and mute controls.
- Provides the same monitors through the dashboard, REST API, and remote MCP.
- Delivers alerts through Telegram or signed HTTPS webhooks with durable retries.
- Saves account time zones, regional formats and clock preferences.
- Lets each person choose how alerts read: three built-in Telegram styles or
  their own [message templates](docs/ACCOUNT_PREFERENCES.md#message-styles-and-templates),
  with a preview that sends no notification.
- Shows departure and arrival times beside each price, and keeps alerts silent
  during the [quiet hours](docs/ACCOUNT_PREFERENCES.md#quiet-hours) you choose
  without delaying them.
- Stays quiet about its own problems: a failed price check shows a short plain
  note, and technical details are an explicit opt-in for developers.
- Shares collection for equivalent searches while keeping accounts and alert rules private.

History comparisons use the observations loaded in the selected range, not every
fare ever offered. CSV files include UTC timestamps, currency, and integer minor
units; for example, `19100` USD means $191.00. See the
[dashboard guide](docs/FAREFLARE.md#use-the-dashboard) for scope and export details.
See [account preferences](docs/ACCOUNT_PREFERENCES.md) for local time and message
settings. Regional formatting preserves the original fare currency.
The workspace groups secondary flight actions under **Manage flight** and account
preferences into four focused sections. See the
[design verification](docs/UI_REFINEMENT_VERIFICATION.md) for responsive review and checks.

The [Telegram bot](docs/TELEGRAM.md) supports flight creation, recent prices,
pause/resume controls, alert-rule editing and message settings inside the chat
after an initial account connection. This revision is deployed; see the
[verification record](docs/TELEGRAM_VERIFICATION.md) for completed checks and limits.

[Sign up at fareflare.dev](https://fareflare.dev/register). The hosted service is
**free with open registration** and allows 20 monitors per account while capacity
is being measured.
Billing is disabled. Self-hosting uses your own infrastructure and can incur costs.
Prices are sampled periodically: Fareflare cannot guarantee the cheapest fare on
the market or detect a drop that begins and ends between checks.

## Run locally

Requirements: Python 3.12, Node.js 24, and npm. No AWS account is needed for the
local dashboard, API, MCP, or automated tests.

```bash
git clone https://github.com/cxdima/fareflare.git
cd fareflare
python3.12 -m venv .venv
make install
make build
make invite
make serve
```

Open the signup URL saved in `.fareflare/invitation.json`. The application runs at
`http://127.0.0.1:8001`, and local data stays in `.fareflare/product.sqlite3`.
Save the recovery code shown at signup; account recovery does not use email.
Invitation files contain credentials and must stay private.

Live collection needs Chromium and a matching ChromeDriver. Run one bounded pass
in another terminal:

```bash
PYTHONPATH=src .venv/bin/python -m fareflare.product_cli worker --limit 5
```

The worker checks due monitors and processes alerts. Schedule it separately for
continuous monitoring. See the [setup guide](docs/FAREFLARE.md) for browser paths,
route-search configuration, and AWS deployment.

## Supported flights

| Input              | Current coverage                                                                                |
| ------------------ | ----------------------------------------------------------------------------------------------- |
| Selected itinerary | US-English economy, one or two adults, USD or JPY, nonstop one-way or fully selected round trip |
| Route search       | Exact airports and date, one way, nonstop, one adult, USD, US-English economy excluding Basic   |

Route searches are enabled on the hosted instance and opt-in when self-hosting.
Connections, flexible dates, nearby airports, other passenger types, and additional
cabins or markets require further collector validation. Unsupported inputs are
rejected explicitly. A recorded price can change before booking.

## Stack and structure

The Angular and Bootstrap frontend uses component classes, signals, and external
SCSS. A Python/FastAPI API serves the built website and account workflows. Browser
collection runs separately with Selenium and Chromium. SQLite supports local use;
AWS uses DynamoDB, separate API and worker Lambdas, and EventBridge.
Both API entry points use a shared script-free HTML reference. The
[stack audit](docs/STACK_AUDIT.md) documents the dependency and runtime checks.

| Path             | Purpose                                                                     |
| ---------------- | --------------------------------------------------------------------------- |
| `src/fareflare/` | Domain models, account services, API/MCP, collectors, persistence, delivery |
| `web/`           | Angular website, dashboard, and Playwright tests                            |
| `tests/`         | Backend behavior, security, integration, and collector fixtures             |
| `infra/`         | Terraform for the API, worker, storage, scheduling, and alarms              |
| `examples/`      | Synthetic demos and a signed webhook receiver example                       |
| `docs/`          | Setup, architecture, operations, and verification records                   |

The Python package is `fareflare`; configuration keys use the `FAREFLARE_` prefix.
Run `make help` for the available commands.

## API and MCP

Create an API key in **API & MCP**. Send it in the `Authorization: Bearer` header;
never put it in a URL. The application serves `/docs` and `/openapi.json` for the
HTTP API. The remote MCP endpoint is `/mcp`, with OAuth/PKCE or an API key for
clients that support custom headers. See [integration details](docs/INTEGRATIONS.md).

## Contributing

Bug reports, collector fixtures, accessibility improvements, and documentation
changes are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests, and
pull request guidance, and the [code of conduct](CODE_OF_CONDUCT.md). Report
vulnerabilities through the private channel in [SECURITY.md](SECURITY.md).
Changes are recorded in the [changelog](CHANGELOG.md).

```bash
make check
npm --prefix web run format:check
npm --prefix web run build
npm --prefix web test
```

Fareflare is [MIT licensed](LICENSE). Dependencies and airline trademarks retain
their respective licenses and ownership. Fareflare is not affiliated with Google
or any airline.
