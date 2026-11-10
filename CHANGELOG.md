# Changelog

Notable changes to Fareflare. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 2.1.0 — unreleased

### Added

- **Message styles.** Telegram alerts and the flight list can use a built-in
  style or your own wording. *Classic with emoji* shows what changed at a glance,
  for example `📉 New low!  $246  (was $254, −$8 · −3%)`, and marks a flight that
  is at its lowest recorded price with 🔥 in `/flights`.
- **Custom templates.** Each alert, plus the flight list heading and row, accepts
  a template of `{placeholders}`, `[optional groups]` and `**bold**`,
  `__italic__` or `` `monospace` `` emphasis. Templates are plain data: there are
  no expressions and nothing is evaluated. See
  [account preferences](docs/ACCOUNT_PREFERENCES.md#message-styles-and-templates).
- A message editor in **Account settings → Notifications** with insertable
  placeholders and a preview for every message, and a **Message style** menu in
  the Telegram bot.
- **Flight times.** Departure and arrival times are read with each price and shown
  in alerts, the `/flights` list, the bot's flight detail and dashboard cards, in
  the account's 12- or 24-hour style: `Mar 10  ·  16:42 → 17:58`. An arrival on a
  later day is marked `+1`. Templates gain `{times}`, `{depart_time}`,
  `{arrive_time}`, `{duration}` and their `return_` forms; `telegram_show_times`
  turns them off for the built-in styles. `observation.schedule` carries the same
  facts in the API and in webhook events. Times never decide whether a price is
  accepted: anything ambiguous is left out rather than guessed.
- Alerts record what they are compared with. `previous.price_minor` and
  `previous.low_minor` appear in `GET /v1/alerts` and in webhook events.
- `GET /v1/preferences/telegram-templates` lists templates, placeholders, presets
  and limits. `POST /v1/preferences/telegram-preview` accepts
  `?message=tracking_started|new_low|below_price|rebound|flight_list`.
- **Opt-in diagnostics.** The `diagnostics` preference shows failure codes on
  flights and sends a Telegram notice when price checks keep failing, stop, or
  recover. It is off by default; without it, people see only a short plain note.
- `collection_failures` on monitors: consecutive failed checks.
- `telegram_show_buttons` to send alerts without link buttons.
- `make worker`, `make mcp`, `make format` and `make lock`; CodeQL and Dependabot
  configuration; a code of conduct, `CODEOWNERS` and `.editorconfig`.
- `make check` fails when a pinned requirement and its hash-locked file disagree,
  so a dependency bump cannot look tested while installing the old version.
- The worker's log line and `health:worker` record carry `failure_codes`, a count
  per failure code for the run. An error the collector did not expect is logged as
  its exception type and the code location that raised it, never its message.
- Stricter linting: Ruff's security, bare-exception, simplification, timezone,
  logging and async rule sets now run in `make check`.
- Property-based tests (Hypothesis) for the template engine, the link importer
  and the flight-time parser. They found both defects listed under *Fixed*.

### Changed

- Flight numbers are written with a space everywhere (`UA 414`), matching the
  dashboard.
- The `/flights` list orders flights on the same route and day by departure time.
- Saved preferences are read tolerantly: a field this release does not recognize
  falls back to its default instead of making the record unreadable. Updates are
  still validated strictly.
- The stdio MCP adapter needs only `FAREFLARE_API_KEY`; a local development
  configuration file is no longer required.
- Python sources are formatted with Ruff, and `make check` enforces it.
- Updated boto3 to 1.43, Ruff to 0.17.4, Angular to 22.2.5 and Playwright to 1.65.
- One version number is published by the Python package, the API and the dashboard.
- Paths that carried an earlier codename were renamed. Update local scripts:

  | Before | Now |
  | --- | --- |
  | `tests_next/` | `tests/` |
  | `infra-next/` | `infra/` |
  | `requirements-next*.txt`, `.lock` | `requirements*.txt`, `.lock` |
  | `Dockerfile` (browser base) | `Dockerfile.browser` |
  | `Dockerfile.next` | `Dockerfile.worker` |
  | `docs/NEXT.md` | `docs/INTEGRATIONS.md` |
  | `examples/next-demo.json` | `examples/demo.json` |
  | `.next/` (local state) | `.fareflare/` |
  | `make next-check`, `next-demo`, `next-mcp` | `make check`, `demo`, `mcp` |

  To keep existing local data and operator records, rename the directory once:
  `mv .next .fareflare`. Both names stay in `.gitignore`.

### Fixed

- A Google Flights link whose itinerary token held bytes that are not valid text
  caused a server error. It is now refused with the usual "could not be decoded"
  message.
- A template containing a lone carriage return is stored with a normal line break
  instead of being rejected as containing a control character.

### Removed

- The remaining references to the original single-account tracker, including the
  `make next-*` and `make product-*` aliases.

### Upgrade notes

- No data migration is needed. New preference fields take their defaults.
- Rolling back to an earlier image after an account has saved a new message style
  makes that account's preferences unreadable to the older code. Reset
  `telegram_style` to `detailed` or `compact` for affected accounts first.
- A queued alert created before this release has no comparison data; it is
  delivered without the "was" figures and its webhook body is unchanged.

## 2.0.0

The first Fareflare release: accounts, a dashboard, an HTTP API, hosted MCP,
Telegram controls, signed webhooks, and shared collection of public Google
Flights prices without a customer Google login. See
[development status](docs/DEVELOPMENT_STATUS.md) for the history of that work.
