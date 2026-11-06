# Telegram bot verification

Verified locally and in production on November 6, 2026. Implementation:
`790566ddf6dc74837cec338493a65679c757e529`.
Production rollout, bot configuration readback and browser verification passed.

## Changes

- Private-chat controls add a supported Google Flights link after confirmation,
  list flights and recorded prices with pagination, pause/resume tracking,
  schedule a collection retry, and stop a monitor after confirmation.
- Alert rules support observed lows, target prices, minimum drops and rebounds.
  Amount entry uses the saved regional format and the flight's currency, with
  explicit confirmation before saving. `/cancel` discards a pending action;
  `/stop` disconnects Telegram without stopping monitors.
- Settings control compact/detailed messages, silent Telegram delivery and global
  muting. Alerts place the price first and use escaped formatting and validated
  link buttons. Website previews show sample text and noninteractive button labels.
- Controls expire after 15 minutes and bind to the account, private chat and
  connection. Account mutations are guarded separately from cached reply retries.
  Existing account services and the HTTP adapter are reused; commands do not run
  browser collection and no paid API or bot-framework dependency was added.
- Operator tools preview/apply profile metadata and enable webhook callbacks,
  with private snapshots, identity guards, readback and guarded restoration.

## Automated checks

| Check | Result |
| --- | --- |
| `make check`, including Pyright and Ruff | Pass |
| Backend tests | 943 passed; 92.83% coverage |
| Angular production build, formatting and test TypeScript | Pass |
| Frontend suite | 72 passed |
| Gitleaks scan of 34 changed/new files | No findings |
| API container | 39 isolated checks; 61 source/build files match exact hashes |
| Worker container | 21 isolated checks; 37 source/lock files match exact hashes |
| Native workflow in packaged API | 18 checks; real ASGI/account/service layers, mocked Telegram |

The native controller has 56 tests covering SQLite and Moto DynamoDB behavior,
including confirmation replay, replaced or cancelled drafts, pagination,
localized amount validation, tenant isolation, expired controls and concurrent
connection changes. Ingress tests exercise cached replies, Telegram retry delays,
failed edits, malformed errors, command limits, rebind/recovery boundaries and
races between delivery and account changes. Presentation checks cover escaping,
validated destinations, local time, original currency and silent delivery.

Profile and routing tests verify preview-only defaults, exclusive private
snapshots, preservation of unrelated configuration, readback failures, partial
application recovery and refusal to overwrite intervening changes.

Both built images ran the **60 combined isolated checks** with networking disabled,
read-only application files and disposable temporary storage. Exact hash checks
tie the packaged source/build files to the implementation revision above. An
additional 18 checks exercised authenticated webhook connection, link preview and
confirmation, target-price entry, pause/resume, stored price history, formatted
alert delivery, confirmed stopping and disconnection through the packaged API.
Foreign callbacks and replayed additions were rejected without extra mutations.

Telegram requests in automated checks use mocked transports. These checks verify
application behavior and request payloads; they do not establish actual Telegram
client rendering or receipt by a person. No live Telegram test messages were sent.

## Live release checks

The reviewed Terraform plan changed only the API and worker image references.
Both Lambda functions report Active with Successful updates. Environment values
and reserved concurrency match their pre-deployment snapshots. Billing remains
disabled, access invite-only, and collection limits unchanged. The original
tracker's image, configuration and modification time were preserved.

Bot descriptions and the private-chat command menu were applied and read back.
The webhook retains its URL, message/edited-message filters and maximum of four
connections, with `callback_query` added. No pending updates were discarded;
readback showed zero queued updates and no webhook error. Private rollback
snapshots were saved before configuration writes.

All **33 production browser/account checks** passed, including nine accessibility
scans, invitation signup, login, API-key creation/revocation, 20-tool MCP discovery,
settings persistence and account deletion. The preview showed both flight and
Fareflare button labels without turning sample controls into active links.
Previewing unsaved compact/silent settings did not persist them; saving and
reloading retained them. No browser runtime, CSP, asset-loading or server errors
were recorded. The disposable account was deleted. These checks created no
monitors, connected no Telegram account and sent no external notifications.

Final immutable image digests:

- API: `sha256:7123f61e057a9112be31fea9f14ef571b8f2803ecbf86729a6e5f70c60ac0018`
- Worker: `sha256:ca8a1d7fd00163b33aae048a8db7a91b3a2f7b80626f9f64c52945ee0d7a564b`

## Limits

Actual receipt of a collected price alert and native-button behavior in Telegram
remain unverified. Delivery is at least once; an ambiguous send response can
produce a duplicate menu even though account changes are guarded against replay.
Cached reply records use a two-day expiry; DynamoDB TTL deletion is asynchronous.

The bot does not expand supported flight coverage, promise a price-check deadline
or establish the cheapest fare on the market. Saved regional settings format
existing values; they do not translate prose or convert currencies. See the
[Telegram guide](TELEGRAM.md) and [operations runbook](OPERATIONS.md#telegram-configuration)
for behavior and deployment procedures.
