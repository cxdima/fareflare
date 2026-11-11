# Changelog

Notable changes to Fareflare. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 2.1.0 — unreleased

### Added

- **Passkeys.** Sign in with a fingerprint, face or device PIN instead of a password,
  from 1Password, iCloud Keychain, Google Password Manager, the browser or a
  security key. The sign-in page offers a saved passkey in the email field's
  autofill list and behind a **Sign in with a passkey** button. Passkeys are added,
  named after their provider, renamed and removed in **Account settings →
  Security**, and password managers find that page through
  `/.well-known/passkey-endpoints`. Every passkey requires user verification, so it
  replaces the password and any second step. Verification uses `webauthn` 3.0.1.
- **Two-step sign-in.** After the password, ask for a 6-digit code from an
  authenticator app. Setup shows a QR code (1Password can scan it from the screen),
  the key to type and a link for an app on the same phone; the code field is
  marked `one-time-code` so 1Password fills it. Ten single-use backup codes come
  with it and can be replaced. A used code cannot sign in twice, and a sign-in stops
  accepting codes after five wrong ones.
- **Password reset by email.** **Forgot password?** sends a link to the account's
  confirmed address through Amazon SES. It works once, for 30 minutes, stops
  working if the password changes first, asks for a code when two-step sign-in is
  on, and signs out every other browser. The reply is the same whether or not an
  account uses the address. New accounts get one email to confirm their address;
  the address can be changed (with the password) in Security.
- **Sign out everywhere.** Revokes every session, API key, connected application and
  Telegram link, then signs the current browser back in.
- Terraform sends account email from the public domain: an SES identity with DKIM,
  a `mail.` MAIL FROM subdomain, and the API's permission to send
  (`email_enabled`, `email_from`). Locally, email is written to
  `.fareflare/outbox/`.
- **System status.** A public page at `/status` says whether price checks, alerts
  and the website are working, in plain words: *Everything is working*, *Some price
  checks are failing*, *Price checks are not running*. It shows each of the last 24
  hours as a bar (and as a table), how many checks recorded a price, and how many
  alerts were sent, and refreshes itself every minute. The workspace header shows
  the same answer in a few words and links to the page. `GET /v1/status` returns
  the report without signing in; it holds counts and states only, never anything
  about an account or a flight. The worker folds each run into hourly totals on
  its `health:worker` record, kept for 48 hours.
- **Start from the link.** The website's front page has a field for a Google
  Flights link. It says at once whether the link is recognized; after signing up or
  signing in, the add-flight dialog opens with that link already filled in. The
  link waits in the browser tab only and is offered once.
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

- **Passwords need 8 characters, not 15.** Sign-up, password changes and resets
  accept 8 to 128 characters, and the `passwordrules` hint that password managers
  read says the same. Existing passwords are unaffected.
- Flight numbers are written with a space everywhere (`UA 414`), matching the
  dashboard.
- The website's main action leads to sign-up; "Sign in" is for returning
  visitors. Invitation links open `/register`; older `/login?invite=` links are
  forwarded there.
- A wrong password when deleting an account is answered with 403 instead of 401.
  Sign-in failures read "Incorrect email, username or password".
- The `/flights` list orders flights on the same route and day by departure time.
- A dashboard flight no longer shows "The last check could not finish" after a
  single failed check. Such a check is retried within a couple of minutes and
  usually succeeds; the note appears from the second failure in a row, or at once
  when checks have stopped. It now says "We will keep trying" instead of naming
  the next scheduled check, which was not when the retry happened.
- **Buttons** share one design: a pill, in ink for the main action. The action
  that starts a flight carries a lime disc with an arrow, which tips upward on
  hover. A button settles when pressed, and a disabled one is plainly grey instead
  of a pale version of the active one.
- The page header and footer line up with the page content at every window width,
  and account settings use one width for the section tabs and the panels.
- Telegram options in **Account settings → Notifications** are grouped as *Include
  in alerts* and *How alerts arrive*, each with its explanation directly under it.
- Each workspace page names itself in the browser tab, for example
  `Alert activity · Fareflare`.
- When every monitor is in use, the flights page says why **Watch a flight** is
  unavailable.
- **Every page is redesigned** around one object, a baggage tag: warm paper, ink,
  a lavender field, and lime for the thing to notice. Headlines are large capitals
  with a light italic line; the typeface is Mona Sans, self-hosted.
  - The front page opens with the headline, the link field and a phone showing an
    example alert. Two pictures move with the scroll: a paper plane unfolds into
    a baggage tag as the three steps go by, and the closing section flies into a
    flock of paper planes. With reduced motion both are still pictures. The alert
    rules can be tried on an example, and the facts sit in a grid of unequal
    tiles.
  - In the workspace each flight is a tag: route code at full size, a sticker for
    its state, and a stub with the latest price and a strip of its recent recorded
    prices. The lowest is marked in lime and times with no recorded price are
    hatched, never filled in. The strip reads the flight's own history
    (`GET /v1/monitors/{id}/history?limit=48`) when the tag comes into view; if
    that fails the tag simply goes without it.
  - Navigation is a rail of pills on wide screens and a bar at the bottom of a
    phone. Lists with nothing in them yet show a paper object and one sentence.
  - Sign-in, sign-up and recovery put the form first, beside a poster that
    follows the form as a short band on a phone. Guides show their contents
    beside the text on wide screens. The status page states the answer in a block
    of its colour, with the last 24 hours as bars.
  - The artwork is generated and documented in
    [docs/BRAND_ASSETS.md](docs/BRAND_ASSETS.md), with each prompt recorded beside
    its file. The four editorial photographs are gone; the link preview image is
    now `/assets/social.jpg`.
- The workspace header no longer repeats the page title, and it has the only
  **Refresh** button: on **Alert activity** it reloads the alerts as well, so the
  separate *Refresh alerts* button is gone.
- Lists with nothing in them yet (alerts, webhook receivers, API keys, a search
  with no matches) share one look, and a field with a button beside it lines up:
  the MCP server address is a single line joined to its **Copy URL** button.
- The front page's closing line reads "Accounts are free".
- **New accounts sign up with an email address.** It is the sign-in name and where a
  reset link goes. Accounts made earlier keep their username and can add an address.
- **The workspace uses the whole screen.** The top bar, page and footer share one
  centred column, so wide screens and zoomed-out windows no longer leave an empty
  band on the right; on very wide pages flights sit two to a row, and account
  settings put their sections in a menu beside the page. Pages lay themselves out
  by the space they get rather than the window size, which keeps them right at any
  zoom from 67% to 400%.
- **Telegram message settings** are switches in two groups, with the message preview
  beside them as a chat with the Fareflare bot, and quiet hours opening in place.
- **Motion.** Disclosures open to their height and close again, dialogs slide away
  when dismissed, workspace pages and settings sections rise into place, and switches
  and checkboxes move when changed. Text never fades, and everything is still under
  reduced motion.
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

- **Artwork and fonts went out without their type.** The Lambda image's Python has
  no entry for WebP, WOFF or WOFF2, so the illustrations, scroll sequences and fonts
  were served as `application/octet-stream`. The portal now sends `image/webp`,
  `image/avif`, `font/woff2` and `font/woff` itself.
- **Pages opened part-way down.** Choosing a page in the navigation moved focus to
  it, and the browser scrolled each page to a different place: account settings
  opened with the header half off screen. Every page now opens at its top, and
  focus still moves to the page for keyboard and screen-reader users.
- A select taller than its text, such as *Show an example of* in the message
  preview, showed its value against the top edge in browsers that support
  customizable selects.
- A Google Flights link whose itinerary token held bytes that are not valid text
  caused a server error. It is now refused with the usual "could not be decoded"
  message.
- A template containing a lone carriage return is stored with a normal line break
  instead of being rejected as containing a control character.
- Mistyping the password while deleting an account signed the browser out,
  because the refusal looked like an expired session.
- An email address typed at sign-up was refused, although it is what most
  password managers offer as the name to save.
- **Price checks lost to Google's own error page.** Google Flights sometimes
  answers a valid link with "Oops, something went wrong." The collector waited 25
  seconds and recorded a `timeout`; in production about one check in four ended
  that way. It now recognises the page within a second and loads the same link
  again, at most twice, without pressing anything on the page. A page that keeps
  failing is recorded as the new `provider_error` code and retried later. The
  worker reports `page_reloads` for each run.
- **Price checks lost to a browser that crashed as it started.** The first
  Chromium started in a Lambda environment crashed two to three seconds after it
  started about one time in three (26 of 69 environments over five days); a
  browser started after it never did (0 of 1,014). Chromium ran with
  `--single-process`, and in that mode the browser process hits a segmentation
  fault when it starts slowly, as it does when its files are slow to read after
  the environment has been frozen. Renderers now run in their own processes, with
  `--no-zygote` in place of `--single-process`. In environments frozen for five
  minutes the first launch crashed 44 times in 559 before the change and 0 times
  in 357 after it. A check takes the same time and about 40 MB more memory.
- A browser that dies while the link is loading, a moment after a start that
  looked successful, ended the check as `browser_failed`. The collector now
  starts a new browser once in that case, with its own empty profile, as it
  already did for a failed start. The worker reports `browser_restarts`.

### Removed

- **Invitations.** Sign-up is open to anyone; `FAREFLARE_REGISTRATION_MODE` is now
  `open` (the default) or `closed`. `make invite` and the `invite` command are gone.
  Old invitation links still open sign-up.
- **Recovery codes.** A forgotten password is reset by email instead, and
  `/auth/recover` and `/auth/recovery-code` are gone. `/recover` opens the
  forgot-password page.
- The remaining references to the original single-account tracker, including the
  `make next-*` and `make product-*` aliases.

### Upgrade notes

- Run `make install` (or rebuild the images): the API now depends on `webauthn`
  3.0.1, with `cbor2`, `pyasn1`, `pyasn1-modules` and `pyOpenSSL`.
- To send account email, set `email_enabled=true` and apply Terraform, then request
  SES production access; until then SES sends only to verified addresses.
- Accounts that signed up with a username have no address on file: until they add
  and confirm one in **Account settings → Security**, they cannot reset a forgotten
  password. Their stored recovery codes no longer do anything.
- Passkeys work only on a domain name: open local servers at `localhost`.
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
