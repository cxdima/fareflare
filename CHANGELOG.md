# Changelog

Notable changes to Fareflare. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- **Release and link tooling for maintainers.** The production release runs from
  versioned scripts in `scripts/release/`: build, image check, push (skipping images
  production already runs, writing the deployment's image values only after every push
  is verified), smoke test, a watch for fresh prices, a record of each release, and a
  check that every stored flight still imports to the same target.
  `scripts/decode_link.py` shows every field of a Google Flights link and what Fareflare
  makes of it. Claude Code gets `release` and `link-report` skills, two reviewer agents
  and a hook that formats each Python file it edits.
- **Every refused link says why.** The bot, the dashboard, the API, MCP and the
  command line answer a refused link with one plain sentence that names what is
  supported and what to change, such as a connection, the cabin, the number of
  passengers, the currency or location, a search instead of a chosen flight, an old
  or damaged link, or a flight that has already left. The API also returns the
  `reason`; accounts with diagnostics on also get the exact check, in the API and in
  Telegram.
- **Refused links in the admin panel**, by reason and check, for the last 30 days.
  Only the counts are kept, never the link.
- **Pause and resume price checks from the command line**
  (`python -m fareflare.admin_cli pause-checks`/`resume-checks`), recorded in the
  admin audit log with who did it and why, like the panel's switch.

### Changed

- **A flight has one identity however its link was found.** These no longer split one
  flight into two or follow it into the address it is checked at: where the link
  was made (the Flights site, a share, Search or Deals), the places you searched for
  once flights are chosen, the page language, how Google was showing the page, the
  browser and click tracking. Parameters Fareflare does not know still count, so two
  links are never merged on a guess. Route searches follow the same rules.
- **Alert links open Google Flights in US English**, the language every check reads.
- **Route searches that include Basic fares are refused**, with the setting to
  choose: Economy (exclude Basic). Route-search prices are only read for fares without
  Basic, so such links used to be accepted and then fail every check.
- **One table of what can be watched** (`src/fareflare/limits.py`) writes the checks,
  the refusal sentences, the guide and the dashboard's description, so they cannot
  disagree.

### Fixed

- **Flights found by searching a city can be watched.** A selected flight whose
  Google Flights search named a city ("Denver to Dallas"), a wider area or several
  airports was refused as an unsupported link, because only a search for the flight's
  exact airports was accepted. Google writes a searched place in more than one way
  (the same city appears as either kind); none of them changes the price. The
  selected flights decide the trip; a search made of airports alone must still
  include the flight's airport.
- **Links shared from Safari are accepted.** Safari writes the country in lower case
  (`gl=us`), which was refused. Route searches read it the same way.
- **More real links are accepted**, from 98 that people shared in public: links on
  Google's country sites that state a location, a currency written in lower case,
  links that leave out the default passengers and cabin, the old Flights address, and
  route searches with any result order. A connection that changes airports within a
  city is now refused as a connection, as connections still are, instead of as a
  broken link. Links in Google Flights' format from before 2020 get their own
  sentence.

### Operators

- **Stored flights move to their new identity once, during the release.** Take a
  table backup, pause price checks, deploy, run
  `python -m fareflare.reidentify --apply <file>` (it saves what it replaces to that
  file first, and `--restore <file>` undoes it), repeat the plan until every flight
  is unchanged, then resume price checks. Until the move, every check of a moved
  flight fails as a changed itinerary. Steps are in
  [operations](docs/OPERATIONS.md#a-release-that-changes-how-links-are-read).

## 2.1.0 — 2026-11-23

### Added

- **Admin panel.** For the operator: every account (searchable, with its flights,
  sign-in methods and connections), every checked itinerary with who watches it,
  sign-ups over 30 days, price checks hour by hour, how accounts are protected, and the
  account-email budgets. Actions for support and abuse: sign out everywhere, turn off
  two-step sign-in, issue a temporary password, suspend or reactivate, delete, and
  pause, resume or stop any flight; switches to pause sign-ups or every price check.
  Every action is recorded with who did it and why. The panel opens only for an admin
  with a second factor, in a session that began with it in the last twelve hours, and
  never through an API key. It loads as its own bundle, so other people never download it.
- **Admin access from the command line** (`python -m fareflare.admin_cli`): bootstrap
  an admin with a temporary password that must be replaced at first sign-in, grant or
  revoke the role, list admins, and recover a locked-out admin. Nothing in the panel can
  make an admin. Public sign-up refuses addresses at the service's own domain.
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
- **Message styles.** Telegram alerts and the flight list use *Compact* (the
  default), *Detailed* or your own wording. A compact alert is three short lines:
  `🔥 New low · $191 (was $199)`, `DEN → DFW · Mar 14 · UA 414`,
  `3:50 PM → 6:54 PM`. Detailed adds the size of the change, the airline, flight
  length, fare and the time of the check. Every style writes prices with their
  symbol (`$246`, not `USD 246.00`), and each alert opens with its own mark: ✈️ now
  tracking, 🔥 new low, 🎯 target reached, 📈 price rose.
- **A compact flight list.** `/flights` shows `Your flights (17)`: one line per
  flight under a shared route-and-day heading, in departure order, with 🔥 beside
  a flight at its lowest recorded price and `(low $231)` beside the others. Only
  flights being watched or paused are listed. A long list comes in pages, and one
  **Manage a flight** button opens a picker instead of a button for every flight.
- An alert that arrives ten minutes or more after its price was checked says when
  the check was made, whatever the style.
- **Custom templates.** Each alert, plus the flight list heading and row, accepts
  a template of `{placeholders}`, `[optional groups]` and `**bold**`,
  `__italic__` or `` `monospace` `` emphasis. Templates are plain data: there are
  no expressions and nothing is evaluated. See
  [account preferences](docs/ACCOUNT_PREFERENCES.md#message-styles-and-templates).
- A message editor in **Account settings → Notifications**: the style is a
  three-way switch, the preview follows every change without a button to press and
  explains a template mistake as it is typed, and details to insert are grouped
  (Price, Alert, Trip, Flight, Times, More) with an example of each. Each style
  offers only the switches it uses. The Telegram bot has a **Message style** menu.
- **Flight list order** (`telegram_list_order`): flights on the same route and day
  start with the earliest departure (the default) or with the lowest price. Choose it
  in **Account settings → Notifications**, or with **Sort by price** / **Sort by
  departure** under the bot's `/flights` list.
- **Sample situations in the preview.** Besides the message, choose what the sample
  is: a one-way trip, a round trip for two, a flight whose times are not known yet, or
  an alert that arrives late. The sample trip always leaves sixteen weeks ahead and its
  button opens the flights it names. `POST /v1/preferences/telegram-preview` takes
  `?sample=` and returns `hints`.
- **Remarks on your own wording.** The preview notes when a message does not show the
  price or which flight it is about. A remark is a note: the wording can still be saved.
- In the message editor, **Reset this message to** Compact or Detailed replaces only
  the message being edited; the others keep their wording.
- The bot's **Message style** menu also switches the details the style includes and
  the buttons under alerts, and its example follows each change.
- New template details: `{weekday}`, `{return_weekday}`, `{days_until}` (`in 12
  days`, `tomorrow`, `today`), `{stops}`, `{return_stops}` and `{cabin}`.
- In a template, a separator such as `·` left beside a detail with no value is
  dropped. New details: `{dates_short}`, `{times_short}`, `{return_times_short}`,
  `{party_note}` and `{late_note}`.
- **Flight times.** Departure and arrival times are read with each price and shown
  in alerts, the `/flights` list, the bot's flight detail and dashboard cards, in
  the account's 12- or 24-hour style: `3:50 PM → 6:54 PM` or `15:50 → 18:54`. An
  arrival on a later day is marked `+1`. Templates gain `{times}`, `{depart_time}`,
  `{arrive_time}`, `{duration}` and their `return_` forms; `telegram_show_times`
  leaves them out of built-in alerts. `observation.schedule` carries the same
  facts in the API and in webhook events. Times never decide whether a price is
  accepted: anything ambiguous is left out rather than guessed.
- **Quiet hours.** `quiet_hours`, for example `22:00-07:00`, names a daily window in
  the account's time zone during which Telegram alerts and notices arrive without a
  sound. They are still delivered at once: nothing is held back or dropped. Set it
  in **Account settings → Notifications** or from the bot's `/settings`.
- Alerts record what they are compared with. `previous.price_minor` and
  `previous.low_minor` appear in `GET /v1/alerts` and in webhook events.
- `GET /v1/preferences/telegram-templates` lists the styles with the switches each
  one uses, templates, placeholders with examples and groups, presets and limits.
  `POST /v1/preferences/telegram-preview` accepts
  `?message=tracking_started|new_low|below_price|rebound|flight_list` and returns
  the message as `text` and as `lines` of styled runs.
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

- **Checks every 10 minutes.** A flight added without an interval is checked every
  10 minutes (was 15), and 10 minutes is the shortest interval offered unless
  `FAREFLARE_MIN_INTERVAL` says otherwise (its default is now 600; the Terraform no
  longer sets it). `interval_seconds` is optional in `POST /v1/monitors` and the MCP
  `create_monitor` tool: left out, the flight gets ten minutes, or the installation's
  shortest interval when that is longer. The fixed default of 900 used to be refused
  by an installation whose minimum was higher.
- **One fixed wait after a failed check.** Every failed check is tried again 15
  minutes later, however many have failed in a row. The wait no longer doubles and
  has no random part: before, a refusal by Google waited from 15 minutes up to two
  hours and any other failure from 30 seconds up to an hour. A check whose worker
  stopped before it finished is also run again after 15 minutes (was two).
- A flight waiting for its retry reports `collection_status: "retrying"` (was
  `"backoff"`).
- **Google's robot check no longer stops a flight.** A `challenge`, and Google's
  consent and sign-in pages (`consent_required`, `login_required`), used to stop a
  flight after one occurrence until someone chose **Retry collection**, though
  nobody could clear them and they pass within minutes. They are now retried like
  any failed check, 15 minutes later. The run
  that meets one checks nothing else. Diagnostic notices come after five failed
  checks in a row, as for other failures. Only `unsupported_itinerary` still stops
  a flight. Each refusal is logged with fixed labels for what Google showed, the
  collector step and how soon (`Public browser refused code=challenge
  signal=sorry_page phase=summary elapsed_ms=1840`), never the address or page.
- **Google's error page waits like its robot check.** "Oops, something went wrong"
  turned out to be a refusal too: the booking page loads, but its request for the
  booking options comes back with an internal error instead of fares, while a normal
  browser gets the fares at the same moment. It shows on about 38% of page loads,
  most in the evening. A check that still meets it after two reloads
  (`provider_error`) now waits 15 minutes, like a robot check, instead
  of trying again within seconds, and the run that met it checks nothing else.
- **Faster first visits.**
  - **Website files come from S3 through CloudFront**, not the application. A cache
    miss (common on a quiet site: every edge location misses once per file) used to
    be a Lambda invocation that might start cold, a second or more for a font or
    script; now it is an S3 read. Upload them with `python -m fareflare.publish_web`
    before applying a release (docs/OPERATIONS.md).
  - **Fewer and shorter cold starts.** One API instance is kept ready by a ping every
    five minutes. The application is built while Lambda starts the instance instead
    of on its first request, so instances AWS starts ahead of demand are ready, and
    the function has twice the memory (and so twice the CPU) to start faster.
  - **A lighter landing page.** The app ships the 60 icons it uses instead of all of
    Bootstrap Icons: the icon font went from 135 KB to 5.5 KB and the render-blocking
    stylesheet from 48 KB to 29 KB compressed (`web/scripts/subset-icons.py`; a test
    fails when an icon is used without regenerating). The scroll animation's frames
    load at low priority, after the page has finished loading.
- **`www.fareflare.dev` redirects to fareflare.dev** (it did not resolve before).
- **Discovery.** A `favicon.ico`, an Apple touch icon, a web app manifest,
  `/llms.txt` (what the site is and where to read more, for AI assistants) and
  `/.well-known/security.txt` (reports go to GitHub's private security advisories).
- **Each account can watch 100 flights, up from 20.** The shared limit on distinct
  itineraries the service checks rose from 20 to 100 with it (otherwise no account
  could get past 20), and is now a Terraform variable, `global_target_limit`, instead
  of a fixed value.
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
- Updated the Lambda runtime client (awslambdaric) from 2.0.12 to 4.2.3, boto3 to
  1.43.127, FastAPI to 0.162.2 and Hypothesis to 6.170.15. The runtime client starts
  both functions, so both rebuilt images were invoked through the Lambda emulator:
  the API's full check, and the worker's start, a successful invocation and a
  refused event.
- **Image repositories keep their newest 10 images** (`images_kept`) and delete
  older ones; they used to keep every release for ever. Ten releases remain to roll
  back to.
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

- **A flight is checked at its interval, not a minute later.** Every check ran one
  worker run after its time: a 15-minute flight was checked every 16 minutes on the
  hosted one-minute schedule, and a retry came a minute late too. The next check was
  counted from the moment a price was recorded, a few seconds into a run, so it
  always just missed the run it was meant for and waited for the following one.
  Times are now counted from the start of the run, and a scheduled run takes every
  flight due within half the time until the next run. A 10-minute flight is checked
  by every tenth run, and a failed check is tried again by the fifteenth run after
  it, whatever a check takes and however the runs' start times wander. The schedule
  tells the worker how often it runs (`period_seconds` in its event); the local
  `worker` commands take `--period` for the same purpose.
- **The website answered "Too Many Requests" and left out artwork.** Every file was a
  Lambda invocation behind API Gateway's account-wide throttle; one visit to the
  landing page made about 190 requests, and dozens came back 429 or 503 (the phone in
  the hero among them). The site now sits behind CloudFront: files are cached at the
  edge and only pages and the API reach Lambda. Per-address limits use the visitor's
  address that CloudFront vouches for with a secret header. The hero image loads first,
  artwork below the fold loads as it nears the screen, and a scroll-sequence frame that
  fails is asked for once more. The global sign-up and sign-in limits at the gateway,
  which let one sign-up through every five seconds for everyone, are looser.
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
- The bot's `/flights` listed flights in no particular order and went on listing
  ones that had been stopped or had departed. It now lists the flights being
  watched or paused, by departure.
- The bot read one page of an account's flights from storage and ignored the rest,
  so an account with a long history of stopped flights could find current ones
  missing from `/flights`. It now reads every page.
- A flight list too long for one Telegram message was reworded in another style
  to make it fit, and could still fail. It is now sent in pages.
- The bot recognized "limit reached" by the wording of an error message. It now
  tells an account's quota and the service's capacity apart by their type.
- `POST /v1/preferences/telegram-preview` put a heading of its own ("Example
  alert") inside `text`. `text` is now exactly the message that would be sent.
- Amounts were formatted from two separate currency lists, one for digits and one
  for symbols. There is one list now, so a currency cannot be in one and not the
  other.

### Security

From a full review of how someone could hurt an account holder or the operator:

- **Common and breached passwords are refused.** A new password is checked against
  the most common passwords, runs and repeats (`12345678`, `aaaaaaaa`), the
  account's own email address and the product's name, and Have I Been Pwned's
  breach corpus. Only the first five characters of the password's SHA-1 are sent,
  with padded answers; if the lookup is unreachable the password is allowed.
  `FAREFLARE_PASSWORD_BREACH_CHECK=off` skips the lookup.
- **Guessing is capped, not only slowed.** 30 wrong passwords an hour per sign-in
  name, and 10 wrong codes an hour and 20 a day per account. Before, someone who
  had a password could start a fresh sign-in every few tries and keep guessing
  six-digit codes indefinitely.
- **Fareflare can no longer be used to mail strangers.** Changing the account's
  address sends a confirmation, and nothing limited how many addresses one account
  could cycle through; the only ceiling was the gateway's request rate. Account
  email now has service-wide budgets per kind (60 an hour, 300 a day), each
  account can trigger five address changes or resends a day, and every
  email-sending route has its own gateway limit. This protects the SES
  account's sending reputation, which other domains in the same AWS account share.
- **Adding a passkey asks for the password.** A passkey signs in without the
  password or a code, so a browser left signed in was enough to plant one that
  survived a password change.
- **Security notices.** A confirmed address is told when the password changes,
  a passkey is added, two-step sign-in is turned off, or (at the old address) the
  email address changes.
- **Alarms can reach someone.** Alarms publish to an SNS topic, with an optional
  `alarm_email` subscription. New alarms cover the SES bounce and complaint rates
  and the email budget running out. The gateway's per-route limits named a route
  that no longer existed (`/auth/recover`); they now cover sign-up, sign-in, the
  second step, passkey sign-in, resets and address changes.
- **`X-Content-Type-Options: nosniff` on every response**, not only the API's:
  pages, static files and error pages too. HSTS now includes subdomains.

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
- A flight stopped by `challenge`, `consent_required` or `login_required` before
  this release stays stopped until **Retry collection** is chosen for it once.
- Flights added before this release keep the interval they were created with (15
  minutes unless another was chosen). To check one every 10 minutes, set
  `interval_seconds` to 600 on its `monitor:` record; the itinerary follows at its
  next check.
- Clients that compared `collection_status` with `"backoff"` must compare it with
  `"retrying"`.
- Apply Terraform with this release: it adds `period_seconds` to the schedule's
  event. A worker that is not told its period still checks every flight one run
  late. A `worker` command run from cron needs `--period` with the seconds between
  runs.

## 2.0.0

The first Fareflare release: accounts, a dashboard, an HTTP API, hosted MCP,
Telegram controls, signed webhooks, and shared collection of public Google
Flights prices without a customer Google login. See
[development status](docs/DEVELOPMENT_STATUS.md) for the history of that work.
