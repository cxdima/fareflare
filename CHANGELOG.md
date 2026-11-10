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
- **Quiet hours.** `quiet_hours`, for example `22:00-07:00`, names a daily window in
  the account's time zone during which Telegram alerts and notices arrive without a
  sound. They are still delivered at once: nothing is held back or dropped. Set it
  in **Account settings → Notifications** or from the bot's `/settings`.
- Alerts record what they are compared with. `previous.price_minor` and
  `previous.low_minor` appear in `GET /v1/alerts` and in webhook events.
- `GET /v1/preferences/telegram-templates` lists templates, placeholders, presets
  and limits. `POST /v1/preferences/telegram-preview` accepts
  `?message=tracking_started|new_low|below_price|rebound|flight_list`.
- **Sign in with an email address.** The sign-in name can be an email address
  or a username, and one field labeled "Email or username" asks for it on every
  page. Sign-in, sign-up and recovery each have an address (`/login`,
  `/register`, `/recover`) and their fields are marked up for password managers,
  so the login saved at sign-up is the one offered at sign-in. An address is only
  a name: it is never verified and Fareflare still sends no email.
- **Change your password, replace your recovery code.** Both are in
  **Account settings → Security** and confirm the current password
  (`POST /auth/password`, `POST /auth/recovery-code`). Changing a password signs
  out other browsers and leaves API keys, connected applications and Telegram
  alone. `/.well-known/change-password` points password managers to the page.
- **A guided first visit.** The recovery code is a step of signing up, shown once
  before the workspace opens. A new account is asked which flight it is watching
  and shown where a link comes from; the add-flight dialog recognizes a Google
  Flights link as it is pasted, and the first price appears without a refresh.
- **Telegram where it is needed.** Someone watching a flight with nowhere to be
  told is offered Telegram on the flights page. The page notices the connection
  by itself; the "Check connection" button is gone.
- **Price context on each flight.** `low_minor` on monitors is the lowest total a
  monitor has recorded. Cards show "Lowest since Nov 3" or the low the price is
  compared with, and "Checked 7 minutes ago" with the exact time on hover.
- Settings sections have addresses (`/app#settings?section=security`), and
  someone sent to sign in from a workspace page returns to it afterwards.
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
- A price check that times out waiting for the price summary logs what the page
  held instead (`page=selected_flights,booking_options chars=1200`), as fixed
  labels and a rounded length, never the page text.
- Stricter linting: Ruff's security, bare-exception, simplification, timezone,
  logging and async rule sets now run in `make check`.
- Property-based tests (Hypothesis) for the template engine, the link importer
  and the flight-time parser. They found both defects listed under *Fixed*.

### Changed

- Flight numbers are written with a space everywhere (`UA 414`), matching the
  dashboard.
- The website's main action leads to sign-up; "Sign in" is for returning
  visitors. Invitation links open `/register`; older `/login?invite=` links are
  forwarded there.
- A wrong password when deleting an account is answered with 403 instead of 401.
  Sign-in failures read "Incorrect email, username or password".
- The `/flights` list orders flights on the same route and day by departure time.
- Saved preferences are read tolerantly: a field this release does not recognize
  falls back to its default instead of making the record unreadable. Updates are
  still validated strictly.
- The stdio MCP adapter needs only `FAREFLARE_API_KEY`; a local development
  configuration file is no longer required.
- Python sources are formatted with Ruff, and `make check` enforces it.
- Updated boto3 to 1.43, Ruff to 0.17.4, Angular to 22.2.5, Playwright to 1.65,
  TypeScript to 6.0.3 and Selenium to 4.52, and refreshed both container base
  images. The Selenium and base-image updates were checked with a real price read
  inside the rebuilt worker image.
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
- Mistyping the password while deleting an account signed the browser out,
  because the refusal looked like an expired session.
- An email address typed at sign-up was refused, although it is what most
  password managers offer as the name to save.

### Removed

- The remaining references to the original single-account tracker, including the
  `make next-*` and `make product-*` aliases.

### Upgrade notes

- No data migration is needed. New preference fields take their defaults.
  Existing usernames keep working unchanged.
- An account whose sign-in name is an email address cannot sign in to an earlier
  image, which accepts usernames only. Rolling back locks those accounts out
  until the release is restored; nothing is lost.
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
