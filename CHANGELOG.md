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
- `make worker`, `make mcp` and `make format`; CodeQL and Dependabot
  configuration; a code of conduct, `CODEOWNERS` and `.editorconfig`.

### Changed

- Flight numbers are written with a space everywhere (`UA 414`), matching the
  dashboard.
- Saved preferences are read tolerantly: a field this release does not recognize
  falls back to its default instead of making the record unreadable. Updates are
  still validated strictly.
- The stdio MCP adapter needs only `FAREFLARE_API_KEY`; a local development
  configuration file is no longer required.
- Python sources are formatted with Ruff, and `make check` enforces it.
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
