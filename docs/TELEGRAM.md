# Use Fareflare in Telegram

Manage flight monitors from a private chat with Fareflare. The
[verification record](TELEGRAM_VERIFICATION.md) documents release checks and their
limits; see [operations](OPERATIONS.md#telegram-configuration) for self-hosted setup.

## Connect once

Sign in to Fareflare, open **Account settings → Connections**, and choose **Connect Telegram**.
Open the one-use link in a private chat with the bot and press **Start**. Connection
links expire after ten minutes. You can then add flights, review recorded prices,
change alert rules, and pause or stop tracking inside Telegram.

The website remains available for account recovery, connection management, time
zone and regional settings, API keys, and webhooks. A Google account is not needed.

## Commands

| Command | Action |
| --- | --- |
| `/start` | Open your flight dashboard. |
| `/flights` | List flights, open their details, and review recorded prices. |
| `/add` | Get instructions for adding a Google Flights link. |
| `/settings` | Change message detail, notification sound, and muting. |
| `/help` | Show the command guide. |
| `/cancel` | Discard a pending addition, amount entry, or confirmation. |
| `/stop` | Disconnect Telegram from your account. Monitors keep running. |

Commands also appear in Telegram's menu when the operator has configured the bot
profile. Use the buttons beneath a message for flight-specific actions. Controls
expire after 15 minutes; send `/flights` or `/settings` for fresh ones.

## Add and manage flights

1. Select your itinerary on Google Flights and copy the full browser address.
   Open shortened share links first. [Supported route-search links](../README.md#supported-flights)
   also work when enabled by the installation.
2. Paste the link directly into the chat, or send `/add YOUR_GOOGLE_FLIGHTS_URL`.
3. Review the route, dates, passengers, cabin, currency, and requested check
   interval. Choose **Start watching** to confirm, or **Cancel** to discard it.

The bot validates the link before creating a monitor. Prices arrive after a
scheduled collection pass; opening a menu or pressing a button does not start a
browser search. Account quotas and supported-flight restrictions still apply.

From `/flights`, choose a flight to see its latest observed price and check time.
The list follows your message style. In the classic style, flights on the same
route and day share a heading and a flight at its lowest recorded price is marked
`🔥 at the low`. **Recent prices** shows five readings per page; **Earlier prices**
loads more. The low shown there applies only to the readings on that page.

- **Pause watching** suspends tracking; **Resume watching** starts it again.
- **Retry collection** appears when collection is blocked and schedules another attempt.
- **Stop watching…** asks for confirmation. It stops that monitor and keeps recorded
  history. A stopped monitor cannot resume; add its link again to watch it anew.
- **View on Google Flights** opens the flight's validated booking/search link.

`/cancel` changes no existing monitor. `/stop` disconnects the bot; it does **not**
stop any flight monitor. Reconnect through Account settings when needed.

## Choose alert rules

Open a flight and choose **Alert rules**:

- **New observed lows:** notify on the first recorded price and subsequent lows
  observed by this monitor. This does not establish the lowest fare on the market.
- **Set minimum drop:** for new-low alerts, require the cumulative decrease from
  the last queued price alert to reach this amount. Enter `0` to remove that minimum.
- **Set target price:** notify when a recorded price first reaches or crosses
  below your threshold. Repeated readings below the target do not repeatedly alert.
- **Enable rebound alerts:** also notify when a price rises from its observed low.
  Another rebound alert requires a new observed low first.

For target prices and minimum drops, send the amount and review **Save alert rule**
before confirming. Amounts use the flight's currency, never a conversion. Enter
digits without currency signs or thousands separators: `250.50` for `en-US` and
`en-GB`, or `250,50` for `de-DE`, `fr-FR`, `es-ES`, and `uk-UA`. USD permits up to
two decimal places; JPY requires whole yen, such as `25000`. Targets must be positive.
Rule changes apply to future observations.

## Messages and delivery

`/settings` offers silent Telegram notifications, global muting and **Message
style**: Detailed, Compact or Classic with emoji, each shown with an example before
you choose it. Your own wording is written in
[Account settings](ACCOUNT_PREFERENCES.md#message-styles-and-templates) and then
appears in this menu as **Custom**. **Mute alerts also mutes webhook delivery**; checks and history
continue. **Send silently** changes Telegram notification sound only. More display
and route-muting options live in [Account settings](ACCOUNT_PREFERENCES.md).

Alerts show the price first, followed by itinerary details and the observation
time in your saved time zone. Without a saved zone, Telegram uses UTC. Validated
flight and dashboard links appear as buttons, without long URLs or internal IDs
in the message body. Website previews use sample data and noninteractive button
labels; they do not send messages.

If a price check cannot finish, the flight shows a short note and Fareflare tries
again; the bot does not send error messages unless you turned on
[technical details](ACCOUNT_PREFERENCES.md#technical-details-are-opt-in).

Prices are sampled and may change before booking. Delivery is at least once: an
ambiguous Telegram response can cause a repeated message or menu. Duplicate
commands and confirmation clicks are guarded against repeated account changes.
