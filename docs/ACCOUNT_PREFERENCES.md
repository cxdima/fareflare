# Account preferences

Open **Account settings** to configure display formats, Telegram messages and muting. Settings belong to the signed-in account and apply on subsequent visits and devices. They do not change collection intervals or other accounts' monitors.

Choose a section to focus on one task:

- **Display:** time zone, regional format and clock style; this section opens by default.
- **Notifications:** Telegram message detail, a sample preview, silent delivery and muting.
- **Connections:** connect or disconnect Telegram and manage approved MCP applications.
- **Security:** account recovery guidance and password-confirmed deletion.

Section buttons work with the keyboard and indicate the current section. Switching sections keeps unsaved display, message and muting drafts while Account settings stays open. Use the relevant **Save** button to persist each group. Leaving Account settings or reloading discards unsaved drafts; saving one group does not save the others.

## Available settings

| Field | Default | Behavior |
| --- | --- | --- |
| `time_zone` | `null` | An IANA name such as `America/Chicago`; adjusts for daylight saving. |
| `locale` | `en-US` | Date/number formatting: `en-US`, `en-GB`, `de-DE`, `fr-FR`, `es-ES`, `uk-UA`. |
| `hour_cycle` | `auto` | Regional default, `h12` (12 hour), or `h23` (00–23). |
| `telegram_style` | `detailed` | `detailed`, `compact`, `classic` (emoji, shows what changed) or `custom`. |
| `telegram_templates` | `{}` | Your own wording, used by the `custom` style. See [below](#message-styles-and-templates). |
| `telegram_show_flight_numbers` | `true` | Include flight numbers. |
| `telegram_show_observed_time` | `true` | Include when the fare was checked, with its time zone. |
| `telegram_show_fare` | `true` | Include the fare name when available. |
| `telegram_show_buttons` | `true` | Show link buttons beneath Telegram alerts. |
| `telegram_silent` | `false` | Send Telegram alerts without notification sound; webhooks are unaffected. |
| `muted` | `false` | Stop outgoing notifications, including webhooks, while collection/history continue. |
| `muted_routes` | `[]` | Mute up to 100 airport pairs, such as `DEN-DFW`. |
| `diagnostics` | `false` | Show failure codes and send notices about failing price checks. See [below](#technical-details-are-opt-in). |

With no saved time zone, the website uses the device's zone and Telegram uses UTC. **Use device time zone** selects the current device's named zone; **Save display settings** persists it for Telegram and other devices. API clients can restore the fallback with `time_zone: null`. Raw fixed offsets and host-specific names such as `localtime` are rejected.

Observation timestamps are instants; departure dates remain the airport's calendar date. CSV timestamps stay ISO 8601 UTC. Regional formatting preserves the quoted currency and amount: it does not convert USD to EUR or change collection currency. Interface and Telegram prose remain English.

Price and route remain in Telegram alerts. Validated flight/dashboard links appear as native buttons, without raw booking URLs or internal IDs in the visible body. **Preview message** renders sample data using the selected message options and saved display settings, with noninteractive example button labels. It neither saves preferences nor sends a Telegram message. Structured webhook payloads remain unchanged. These changes are deployed; the [Telegram verification record](TELEGRAM_VERIFICATION.md) distinguishes completed checks from unverified human receipt.

After connecting once through the website, the [Telegram bot](TELEGRAM.md) offers the built-in message styles, sound and global muting through `/settings`. Time zone, regional format, individual detail fields and route muting remain in Account settings.

## Message styles and templates

**Account settings → Notifications → Message style** chooses how Telegram alerts and the `/flights` list are worded. The three flight-number, time and fare checkboxes tune the built-in styles.

| Style | Example of a new low |
| --- | --- |
| Detailed | `USD 246.00` / `New observed low` / route, date and flights / total and fare / time checked |
| Compact | The same facts with total and fare on one line |
| Classic with emoji | `📉 New low!  $246  (was $254, −$8 · −3%)` / `🛫 DFW → DEN` / `United  ·  UA 1753` / `Mar 10` / link / time |
| Custom | Whatever your templates say |

In the classic list, a flight at its lowest recorded price is marked `🔥 at the low`; otherwise the row shows `(low $231)`. "Low" always means the lowest price this monitor has recorded since it began tracking, not a market-wide low.

### Writing your own

Choose **Custom — write your own**. The editor starts from the style you had selected, offers every available detail as a button, and previews each message with sample data before you save. There are six templates: `tracking_started`, `new_low`, `below_price`, `rebound`, `flight_group` (an optional list heading) and `flight_row`. A message without its own template uses the detailed wording.

| You write | It means |
| --- | --- |
| `{price_short}` | A detail from the list below. An unknown name is rejected when you save. |
| `[ · Fare: {fare}]` | Optional: shown only when every detail inside has a value. |
| `**bold**`, `__italic__`, `` `monospace` `` | Emphasis. It must close on the same line. |
| `\[` or `\{` | The character itself, not template syntax. |

A line with nothing left to show is removed, and repeated blank lines collapse. For example:

```text
{emoji} **{headline}**  **{price_short}**[  __({change_summary})__]
🛫 **{route}**
[{airline}][  ·  `{flights}`]
{date_short}[ – {return_date_short}]
{link}
```

Templates are text, not programs. There are no conditions, loops, calculations or formatting options, so a template cannot read anything beyond the listed details. Each template may hold up to 800 characters, 20 lines and 40 placeholders. If a template would produce an empty message for a particular alert, the detailed wording is sent instead, so an alert is never lost.

**Alert details:** `emoji`, `headline`, `reason`, `price`, `price_short`, `previous_price`, `previous_price_short`, `previous_low`, `previous_low_short`, `change`, `change_percent`, `change_summary`, `route`, `origin`, `destination`, `date`, `date_short`, `return_date`, `return_date_short`, `dates`, `flights`, `airline`, `itinerary`, `passengers`, `total`, `fare`, `details`, `observed`, `observed_short`, `link`.

**List row details:** the trip and flight details above, plus `status`, `status_note` (only when a flight needs attention), `price`, `price_short`, `low`, `low_short`, `low_note`, `low_status` and `checked`. A list heading may use the trip details. Consecutive flights with the same heading share it.

`price` writes the currency code (`USD 246.00`); `price_short` uses its symbol and drops empty cents (`$246`). A new low and a rebound are compared with the previous low; a reached target is compared with the previous price. Using `{link}` in a template replaces the **View flight** button. `GET /v1/preferences/telegram-templates` returns the authoritative list with descriptions, the built-in templates and the limits.

## Technical details are opt-in

When a price check cannot finish, Fareflare keeps trying and shows a short, plain note on the flight. It never sends an error message on its own. Turning on **Technical details** (`diagnostics`) is for developers and integrators:

- flights in the dashboard and the Telegram bot also show the failure code and the number of consecutive failed checks;
- Telegram sends one notice when checks have failed five times in a row or have stopped, and one when a price is recorded again.

Muting, pausing a flight or turning the setting off drops pending notices rather than holding them. The setting can be turned off from the bot's `/settings`. The API always reports `last_error` and `collection_failures` on a monitor, whatever this preference says.

## API and MCP contract

`GET /v1/preferences` returns the complete preferences object. `PUT /v1/preferences` merges only supplied fields; omitted fields keep their saved values. Both require authentication. For example:

```json
{"time_zone":"America/Chicago","hour_cycle":"h23","telegram_silent":true}
```

`POST /v1/preferences/telegram-preview` accepts the same partial preference fields and returns `text`, `buttons` (label/URL pairs), `silent` and the effective `time_zone`. Add `?message=` with `tracking_started`, `new_low` (the default), `below_price`, `rebound` or `flight_list` to choose what is rendered. `telegram_templates` is replaced as a whole when supplied, so send every template you want to keep. The website displays button labels without opening the sample links. Browser mutations require the session's CSRF token. API keys use bearer authentication.

MCP exposes `get_preferences` and `set_preferences`. Pass the partial object through `settings`; the existing `muted` and `muted_routes` arguments remain supported.

## Implementation boundaries

`PreferencesFacade` owns dashboard-scoped state, deduplicates reads and cancels requests at teardown. `RegionalFormat` caches reactive browser `Intl` formatters; pure factories live in `regional-formatting.ts`. The Python `Preferences` model validates API, MCP and delivery input. `MonitoringService` merges changes with optimistic concurrency. `telegram_messages` renders escaped HTML and a plain counterpart from the same preferences; `telegram_text` retains the plain-text interface.

Presentation changes preserve queued alerts and use current preferences at delivery. Muting changes advance the notification revision so stale queued alerts cannot reappear after unmuting. Deployments need IANA tzdata in both API and delivery images.

Tests cover partial updates, tenant isolation, validation, delivery and preview behavior, DST transitions, fractional-hour zones, airport dates, currency preservation and UI persistence. Native behavior follows [JavaScript Intl](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/DateTimeFormat) and Python's [ZoneInfo](https://docs.python.org/3/library/zoneinfo.html).

## Possible next additions

- **Quiet hours:** decide whether to defer or discard alerts, then define queue expiry, deduplication, travel time-zone changes and DST boundaries. Silent delivery is already available; scheduled quiet hours are not implemented.
- **Language packs:** separate prose from regional formatting and review translations before enabling them. Locale selection currently changes formatting only.
- **New-monitor defaults:** let accounts preselect alert thresholds and delivery channels while preserving monitor quotas and minimum collection intervals. Existing monitors should change only through an explicit action.
