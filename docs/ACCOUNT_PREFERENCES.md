# Account preferences

Open **Account settings** to configure display formats, Telegram messages and muting. Settings belong to the signed-in account and apply on subsequent visits and devices. They do not change collection intervals or other accounts' monitors.

## Available settings

| Field | Default | Behavior |
| --- | --- | --- |
| `time_zone` | `null` | An IANA name such as `America/Chicago`; adjusts for daylight saving. |
| `locale` | `en-US` | Date/number formatting: `en-US`, `en-GB`, `de-DE`, `fr-FR`, `es-ES`, `uk-UA`. |
| `hour_cycle` | `auto` | Regional default, `h12` (12 hour), or `h23` (00–23). |
| `telegram_style` | `detailed` | Detailed itinerary or `compact`, price-first message. |
| `telegram_show_flight_numbers` | `true` | Include flight numbers. |
| `telegram_show_observed_time` | `true` | Include when the fare was checked, with its time zone. |
| `telegram_show_fare` | `true` | Include the fare name when available. |
| `telegram_silent` | `false` | Send Telegram alerts without notification sound; webhooks are unaffected. |
| `muted` | `false` | Stop outgoing notifications, including webhooks, while collection/history continue. |
| `muted_routes` | `[]` | Mute up to 100 airport pairs, such as `DEN-DFW`. |

With no saved time zone, the website uses the device's zone and Telegram uses UTC. **Use device time zone** selects the current device's named zone; **Save display settings** persists it for Telegram and other devices. API clients can restore the fallback with `time_zone: null`. Raw fixed offsets and host-specific names such as `localtime` are rejected.

Observation timestamps are instants; departure dates remain the airport's calendar date. CSV timestamps stay ISO 8601 UTC. Regional formatting preserves the quoted currency and amount: it does not convert USD to EUR or change collection currency. Interface and Telegram prose remain English.

Price and route remain in Telegram alerts. Validated flight/dashboard links appear as native buttons, without raw booking URLs or internal IDs in the visible body. **Preview message** renders sample data using the selected message options and saved display settings, with noninteractive example button labels. It neither saves preferences nor sends a Telegram message. Structured webhook payloads remain unchanged. These changes are deployed; the [Telegram verification record](TELEGRAM_VERIFICATION.md) distinguishes completed checks from unverified human receipt.

After connecting once through the website, the [Telegram bot](TELEGRAM.md) offers compact/detailed messages, sound and global muting through `/settings`. Time zone, regional format, individual detail fields and route muting remain in Account settings.

## API and MCP contract

`GET /v1/preferences` returns the complete preferences object. `PUT /v1/preferences` merges only supplied fields; omitted fields keep their saved values. Both require authentication. For example:

```json
{"time_zone":"America/Chicago","hour_cycle":"h23","telegram_silent":true}
```

`POST /v1/preferences/telegram-preview` accepts the same partial preference fields and returns `text`, `buttons` (label/URL pairs), `silent` and the effective `time_zone`. The website displays button labels without opening the sample links. Browser mutations require the session's CSRF token. API keys use bearer authentication.

MCP exposes `get_preferences` and `set_preferences`. Pass the partial object through `settings`; the existing `muted` and `muted_routes` arguments remain supported.

## Implementation boundaries

`PreferencesFacade` owns dashboard-scoped state, deduplicates reads and cancels requests at teardown. `RegionalFormat` caches reactive browser `Intl` formatters; pure factories live in `regional-formatting.ts`. The Python `Preferences` model validates API, MCP and delivery input. `MonitoringService` merges changes with optimistic concurrency. `telegram_messages` renders escaped HTML and a plain counterpart from the same preferences; `telegram_text` retains the plain-text interface.

Presentation changes preserve queued alerts and use current preferences at delivery. Muting changes advance the notification revision so stale queued alerts cannot reappear after unmuting. Deployments need IANA tzdata in both API and delivery images.

Tests cover partial updates, tenant isolation, validation, delivery and preview behavior, DST transitions, fractional-hour zones, airport dates, currency preservation and UI persistence. Native behavior follows [JavaScript Intl](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/DateTimeFormat) and Python's [ZoneInfo](https://docs.python.org/3/library/zoneinfo.html).

## Possible next additions

- **Quiet hours:** decide whether to defer or discard alerts, then define queue expiry, deduplication, travel time-zone changes and DST boundaries. Silent delivery is already available; scheduled quiet hours are not implemented.
- **Language packs:** separate prose from regional formatting and review translations before enabling them. Locale selection currently changes formatting only.
- **New-monitor defaults:** let accounts preselect alert thresholds and delivery channels while preserving monitor quotas and minimum collection intervals. Existing monitors should change only through an explicit action.
