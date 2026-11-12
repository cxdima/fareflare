# Fareflare operations

This runbook covers self-hosted deployments and release maintenance. Keep actual
account IDs, backend settings, secrets, tested image digests, and rollback records
in private operator storage. Published verification records describe checks that
were performed; they are not a substitute for testing your deployment.

## Configure your installation

Use Python 3.12, Node.js 24, Docker with ARM64 build support, AWS CLI v2, and
Terraform 1.10 or newer. Authenticate to the intended AWS account and provision a
private, encrypted, versioned S3 bucket for Terraform state.

```bash
umask 077
mkdir -p .fareflare
cp infra/backend.hcl.example .fareflare/backend.hcl
cp infra/terraform.tfvars.example infra/production.auto.tfvars
```

Edit the copied files. Set your state bucket, a unique state key, region,
`expected_account_id`, and a resource name such as `fareflare-production`.
The AWS provider rejects a different authenticated account. Never share state
between installations. Backend files and variable files stay out of Git.

```bash
terraform -chdir=infra init -backend-config=../.fareflare/backend.hcl
terraform -chdir=infra plan -out=../.fareflare/fareflare.tfplan
terraform -chdir=infra apply ../.fareflare/fareflare.tfplan
```

Review the saved plan before applying. On the **first** deployment, empty image
URIs create storage and ECR repositories without running application code.
Afterward, always preserve both deployed image URIs in your recorded inputs.
Empty image values on an existing deployment request removal, which lifecycle
protection rejects. Keep scheduling and delivery disabled until validation passes.

## Release API and worker images

Run backend and browser checks, then build both images. The API image packages
`web/dist`, so build the dashboard first. Build `Dockerfile.browser` once as the
Chromium base; reuse a verified immutable base digest for subsequent worker releases.

```bash
make check
npm --prefix web ci
npm --prefix web run format:check
npm --prefix web run test:types
npm --prefix web run build
npm --prefix web test

docker buildx build --platform linux/arm64 --provenance=false --sbom=false --load \
  -f Dockerfile.browser -t fareflare-browser-base .
docker buildx build --platform linux/arm64 --provenance=false --sbom=false --load \
  -f Dockerfile.api -t "$FAREFLARE_API_REPOSITORY:$FAREFLARE_RELEASE" .
docker buildx build --platform linux/arm64 --provenance=false --sbom=false --load \
  --build-arg BROWSER_BASE=fareflare-browser-base \
  -f Dockerfile.worker -t "$FAREFLARE_WORKER_REPOSITORY:$FAREFLARE_RELEASE" .
```

Set `FAREFLARE_API_REPOSITORY`, `FAREFLARE_WORKER_REPOSITORY`, and
`FAREFLARE_RELEASE` to your ECR repository URLs and a new release tag. Authenticate
Docker to that registry, push both images, and retrieve their ECR image digests.
Set `api_image_uri` and `image_uri` to `REPOSITORY@sha256:DIGEST`. Record the source
revision, browser base, new digests, and previous digests privately.

```bash
docker push "$FAREFLARE_API_REPOSITORY:$FAREFLARE_RELEASE"
docker push "$FAREFLARE_WORKER_REPOSITORY:$FAREFLARE_RELEASE"
terraform -chdir=infra plan -out=../.fareflare/fareflare.tfplan
terraform -chdir=infra apply ../.fareflare/fareflare.tfplan
```

Validate health, account registration, tenant isolation, API key revocation, and
OAuth/MCP before announcing the release. `product_delivery_enabled=true` activates the
customer inbox, Telegram, and verified webhook delivery paths. Measure collection
time and resource use before choosing `worker_max_targets`,
`worker_schedule_minutes`, and `schedule_enabled=true`. The default batch is one
target and the default dispatch interval is five minutes. Dispatch frequency is
not a guarantee of price freshness.

## CDN (CloudFront)

With `cdn_enabled=true` and an `edge_secret` of at least 32 random characters in the
tfvars, the domain points at a CloudFront distribution (`infra/cdn.tf`) whose origin is
the API Gateway custom domain, reached with the viewer's `Host` header. Scripts,
styles, fonts and everything under `/assets/` and `/media/` are cached at the edge by
path alone (cookies, headers and query strings never make a new cache entry, so the
cache cannot be bypassed); pages, `/v1`, `/auth`, `/oauth`, `/mcp` and `/telegram` pass
through uncached. Throttled or failed answers are never cached.

Without it, every file is a Lambda invocation under API Gateway's account-wide throttle:
one landing-page visit made about 190 requests and drew 429 and 503 answers.

CloudFront adds `X-Fareflare-Edge: <edge_secret>` to every request it forwards. Only a
request with that header may name the visitor (`CloudFront-Viewer-Address`) for the
per-address sign-in and sign-up limits; anything else is limited by API Gateway's own
source address.

Fingerprinted files change name with each build. Files under `/assets/` keep their
names and are cached for an hour, so after a release that changes artwork run:

```bash
aws cloudfront create-invalidation --distribution-id "$(terraform -chdir=infra output -raw cdn_distribution_id)" --paths '/assets/*'
```

## Account email (Amazon SES)

Password resets and address confirmation are sent through Amazon SES from the
public domain. Set `email_enabled=true` with `domain_name` and `hosted_zone_id`;
Terraform then creates the SES domain identity, its three DKIM records, a
`mail.<domain>` MAIL FROM subdomain (MX and SPF records), the API's `ses:SendEmail`
permission, and `FAREFLARE_EMAIL=ses` with `FAREFLARE_EMAIL_FROM`. `email_from`
overrides the default `"<product_name> <no-reply@<domain>>"`.

A new SES account starts in the sandbox, where it can send only to verified
addresses. Request production access in the SES console (Account dashboard >
Request production access) before relying on resets. Until then, and whenever SES
rejects a message, the failure is logged and the person sees the same answer as
for any address, so nothing about accounts is revealed. A DMARC record for the
domain is not created; add one if the domain has none.

SES reputation belongs to the whole AWS account, including other domains that send
from it, so the application keeps its own email within budgets: 60 an hour and 300 a
day for each kind (confirmations, resets, security notices), and five address
changes or confirmation resends per account per day. When a budget runs out the
message is skipped and `Account email budget reached` is logged; the
`<name>-email-budget-reached` alarm counts those lines. The `<name>-ses-bounce-rate`
(above 3%) and `<name>-ses-complaint-rate` (above 0.05%) alarms watch the account's
SES reputation; AWS reviews an account at 5% and 0.1%. The gateway also gives every
email-sending and credential-checking route its own slower limit (`sensitive_routes`
in `infra/api.tf`).

### Alarm notifications

Every alarm publishes to the `<name>-alarms` SNS topic. Set `alarm_email` in the
production tfvars to receive them by email; AWS sends one confirmation message that
must be accepted before notifications arrive. Without it, alarms still change state
in CloudWatch but nobody is told. The collection-failure alarm is not routed there:
Google's own error pages make some failures routine.

## Admin access

The admin role can only be granted or removed from the command line, with access to the
database: AWS credentials for the DynamoDB table of a deployed service, or the SQLite
file of a local one. Nothing in the panel can make an admin.

```bash
# First admin. Prints when the temporary password stops working (30 minutes by default).
PYTHONPATH=src .venv/bin/python -m fareflare.admin_cli --table <name> \
  bootstrap admin@<domain> --temporary-password '<temporary>'
PYTHONPATH=src .venv/bin/python -m fareflare.admin_cli --table <name> grant person@example.com
PYTHONPATH=src .venv/bin/python -m fareflare.admin_cli --table <name> revoke person@example.com
PYTHONPATH=src .venv/bin/python -m fareflare.admin_cli --table <name> list
# Locked out: a new temporary password; every browser is signed out.
PYTHONPATH=src .venv/bin/python -m fareflare.admin_cli --table <name> reset-password admin@<domain>
```

Omit `--temporary-password` to have a random one printed. Run `bootstrap` just before
signing in: until the temporary password is replaced, anyone who has it can choose the
account's real password. `bootstrap` refuses an address another account already uses;
`--reclaim` takes it over and removes that account's sessions, API keys, passkeys and
two-step sign-in. Public sign-up refuses addresses at the service's own domain, so an
`admin@<domain>` account can only come from here.

After the first sign-in the admin must choose a password, then turn on two-step sign-in
or add a passkey: the panel opens only in a session that began with one of them, and for
twelve hours from that sign-in. Every admin action is written to an audit log
(`admin_audit` partition, kept 400 days) that the panel can read and not change.

The **Controls** tab holds two switches stored in `configuration:admin`: pausing new
sign-ups (existing accounts keep working) and pausing every price check (the worker skips
collection; due flights are checked once it is turned off). Both are recorded in the
activity log.

## Accounts and capacity

The hosted release uses `registration_mode="open"` and `billing_enabled=false`.
`closed` stops new sign-ups while existing accounts keep working.
Enabling billing fails startup until a payment integration exists. Free access
does not eliminate AWS charges. Default limits are 20 monitors per account,
a 900-second minimum requested interval, and 20 distinct shared targets.
Equivalent targets share collection; account preferences remain private.

Accounts sign up with an email address and a password, and can add passkeys and
two-step sign-in. A taken address is reported at sign-up, so anyone can learn
whether an address has an account. A password reset goes only to a confirmed
address, works once for 30 minutes, needs an authenticator code when two-step
sign-in is on, and signs out other browsers. **Sign out everywhere** invalidates
sessions, API keys, OAuth grants and Telegram bindings. Confirming actions count
against the sign-in rate limit; a wrong confirming password is answered with 403,
so the browser does not mistake it for an expired session.
`/.well-known/change-password` redirects password managers to that page. Account deletion requires
the password and stops future work for that account. Shared observations may remain
available to other subscribers.

OAuth dynamic registration admits public PKCE clients, applies per-IP limits, and
has a permanent cap of 1,000 clients. Review retention before raising that cap.

## Telegram configuration

The expanded bot controls are deployed on the hosted service; see the
[verification record](TELEGRAM_VERIFICATION.md) for checked behavior and limits.
When self-hosting, deploy a verified API image supporting callbacks before enabling
them. [The Telegram guide](TELEGRAM.md) documents commands and user workflows.

Create a Telegram bot and store the following JSON in AWS Secrets Manager:

```json
{
  "bot_token": "YOUR_BOT_TOKEN",
  "bot_username": "YOUR_BOT_USERNAME",
  "webhook_secret": "YOUR_RANDOM_WEBHOOK_SECRET"
}
```

Use a strong random webhook secret and set `customer_telegram_secret_arn` in private
Terraform inputs. The API and worker read only that configured secret. Connect an
account from **Account settings** using its one-use link; links expire in ten
minutes and require a private chat whose sender matches the chat owner.
After connecting, users can manage flights and alert rules through the private
chat. `/help` shows guidance; `/stop` disconnects Telegram without cancelling
monitors or removing history. No browser runs in the command handler. Collection
continues through the scheduled worker, using the existing HTTP adapter without
new paid APIs or bot-framework dependencies.

Register the webhook after the API is reachable:

```bash
PYTHONPATH=src .venv/bin/python scripts/route_telegram.py \
  --secret-arn "$FAREFLARE_TELEGRAM_SECRET_ARN" \
  --aws-account YOUR_ACCOUNT_ID --region YOUR_REGION \
  --url https://YOUR-API.execute-api.REGION.amazonaws.com/telegram/webhook \
  --snapshot .fareflare/telegram-before-UNIQUE.json --enable-callbacks
```

The script verifies AWS identity, saves a new private snapshot before changing
routing, preserves pending updates, and reads the route back. It refuses custom
certificate routes that cannot be restored from Telegram's API. It does not print
bot credentials. `--enable-callbacks` adds `callback_query` to a nonempty update
filter, preserving existing update types and `max_connections`. An empty filter
already includes callbacks and stays empty. Use the existing URL to enable
callbacks without moving the route. An already-matching configuration is a
read-only no-op and creates no snapshot.

Configure the public Fareflare name, descriptions, private-chat command menu and
default menu button separately. Preview reads the current settings without
changing them:

```bash
PYTHONPATH=src .venv/bin/python scripts/configure_telegram.py \
  --secret-arn "$FAREFLARE_TELEGRAM_SECRET_ARN" \
  --aws-account YOUR_ACCOUNT_ID --region YOUR_REGION
```

Apply the displayed profile after deploying the matching commands:

```bash
PYTHONPATH=src .venv/bin/python scripts/configure_telegram.py \
  --secret-arn "$FAREFLARE_TELEGRAM_SECRET_ARN" \
  --aws-account YOUR_ACCOUNT_ID --region YOUR_REGION \
  --apply --snapshot .fareflare/telegram-profile-before-UNIQUE.json
```

The profile tool verifies AWS and bot identity, exclusively creates a mode-0600
snapshot before mutation, and reads back each change. It updates default-language
metadata and the `all_private_chats` command scope, preserving other languages,
command scopes and per-chat menu overrides. It does not change the avatar,
username or webhook. To restore, replace `--apply --snapshot FILE` with
`--restore FILE`; restore refuses unrelated intervening edits and supports a
partially applied configuration. Keep these snapshots private and use new names.

Check initial connection, command menus, paginated views, link and rule
confirmations, `/cancel`, expired controls, disconnect/reconnect, and an actual
price notification. Confirm time-zone and sound settings with a disposable
account before announcing the change.

Restore the saved route when rolling back:

```bash
PYTHONPATH=src .venv/bin/python scripts/route_telegram.py \
  --secret-arn "$FAREFLARE_TELEGRAM_SECRET_ARN" \
  --aws-account YOUR_ACCOUNT_ID --region YOUR_REGION \
  --restore .fareflare/telegram-before-UNIQUE.json
```

The restore checks the bot identity, secret, snapshot permissions, and current
route. New snapshots also guard update filters and connection limits so rollback
cannot silently replace a newer configuration. Webhook routing controls incoming
commands; outbound worker delivery is separate. See the
[Telegram Bot API](https://core.telegram.org/bots/api#setwebhook) for webhook behavior.

### Callback security and retry behavior

The webhook secret authenticates ingress. Commands require the private-chat
sender to match the chat owner; callbacks additionally require a message authored
by the configured bot. Opaque controls expire after 15 minutes and are bound to
the account, chat, authentication epoch and current connection. Mutations check
current revisions and consume their action transactionally. Forwarded, expired,
replayed or stale confirmation controls cannot authorize a new change.

Update IDs deduplicate requests. Pending command replies can be cached for retry
with a two-day expiry; they may contain account views and button data. DynamoDB
TTL deletion is asynchronous, so expiry is not an immediate physical-deletion
guarantee. Cached account views are rechecked against the current connection
before delivery. Successful replies discard the cached content.

Delivery remains at least once. Telegram can accept a message before an HTTP
response is lost, so a retried send can produce a duplicate menu. The handler
edits the existing menu when possible, honours Telegram retry delays and limits
interactive commands. Account mutations are guarded separately from reply
delivery. Do not interpret a duplicate message as permission to repeat a change.

## Monitoring and incidents

`/status` (and `GET /v1/status`, no sign-in) is the public summary: it reports
price checks as stalled when no worker run has been recorded for 20 minutes, as
having trouble when 40% of the last three hours' checks failed, and as not working
at 90%; fewer than four checks in that window is never called trouble. It is built
from hourly totals (`runs`, `collected`, `failed`, `alerts_sent`) that the worker
folds into `health:worker` under `hours`, kept for 48 hours. If two worker runs
write at once, one hour's totals can miss a run; the page is a summary, not an
audit. The thresholds are constants at the top of `src/fareflare/health.py`.

HTTP 200 from `/health` does not prove that collection is fresh. Inspect
`last_worker_at`, the DynamoDB `health:worker` record, monitor freshness and
`last_error`, and the API/worker CloudWatch logs. `Fareflare` metrics include browser
starts/reuses, collection failures, skipped targets, delivery counts, and runtime.
Monitor Lambda throttles and dead-letter deliveries as well as exceptions.

Each worker log line and the `health:worker` record carry `failure_codes`, a count
per failure code for that run, for example `{"layout_changed": 2}`. An error the
collector did not expect is logged once as its exception type and the code location
that raised it, such as `KeyError at public_quotes.py:98 verified_reading`. Exception
messages are never logged or stored, because a provider error can quote a URL or a
cookie.

A `timeout` is the commonest code. When the page loaded but its price summary
never appeared, the log says what the page held, using fixed labels and a rounded
length instead of its text:

```text
Public browser timeout phase=summary page=selected_flights,booking_options chars=1200
```

`selected_flights` without `lowest_total` means the trip rendered and Google
returned no booking options; `none` with a small length means the page stayed an
empty shell; `lowest_total` without `cheapest_match` means the layout the
collector waits for has changed. A failed check is retried after 30 seconds to a
few minutes, so a run of timeouts delays a price rather than losing it.

Google Flights sometimes answers a valid link with its own error page: "Oops,
something went wrong." above a Reload button. It is not a challenge and does not
depend on the flight; it comes and goes by the hour, and before it was handled it
ended about one check in four as a `timeout`. The page appears within a second
and stays, so the collector does not wait it out. It loads the same validated
link again, at most twice with a one-second pause, and presses nothing on the
page. `page_reloads` in the worker log line and the `health:worker` record counts
those loads for the run. A page that still fails is recorded as `provider_error`,
retried later like any other failed check, and logged as:

```text
Public browser provider error page reloads=2
```

The page comes in spells of a few minutes in which about half of all loads show
it, with clean stretches between. In a local trial of 30 checks that began in
such a spell, 13 met the page, 10 of those recovered by reloading, and the 3
that did not failed in five seconds instead of 28. So `page_reloads` rising with
an occasional `provider_error` is the normal picture.
`provider_error` on most checks means reloading has stopped helping. Compare a
local run of `python -m fareflare.cli quote <link>` before changing anything,
because the cause is on Google's side.

In Lambda, Chromium runs with `--no-sandbox` and `--no-zygote` and keeps its
renderers in their own processes. It used to run with `--single-process`, and the
first Chromium started in an environment crashed two to three seconds after it
started about one time in three: over five days that was 26 of 69 environments,
and none of the 1,014 browsers started later in the same environments.

The crash was a segmentation fault in the browser process as chromedriver sent
its first page commands, and it only happened when Chromium had been slow to
start. Slow file reads are what make it slow. An environment that has been frozen
between invocations reads Chromium's 300 MB of files in about 2.7 seconds, against
0.6 in a new environment and 0.04 once they are cached, so the first launch after
a freeze can take over 2.5 seconds instead of 1.3. In trials on environments
frozen for five minutes, the first launch crashed 44 times in 559 with
`--single-process`, every time after a slow start, and 0 times in 357 without it,
28 slow starts included. A new environment can be slow in the same way: 4 of 19
crashed in one trial.

Do not bring `--single-process` back to save memory. A check peaks near 460 MB of
the worker's 2,048 MB, about 40 MB more than before, and takes the same time.
`--no-zygote` has to stay: with a zygote, all 12 of 12 launches in Lambda failed.

The collector still handles a browser that dies at either moment. Before a
session exists it starts Chromium again and logs the first line below; while the
link is loading it does the same and logs the second, where `launch` counts
browsers started in that environment:

```text
Public browser startup retry attempt=2 reason=browser_start_failed elapsed_ms=2485
Public browser restart attempt=2 reason=session_lost launch=1
```

`browser_restarts` in the worker log line counts the second kind. Neither line
appeared in the trials without `--single-process`, so several a day with
`launch=1` would mean the first launch is crashing again for another reason. A
restart with a high `launch` number means a browser died in an environment that
had already run one, and a `Public browser failure` line straight after a restart
means the replacement died as well; neither has been seen, and both point to
something else.

Terraform provisions Lambda and collection-failure alarms. Attach an operator
notification destination before relying on unattended alerts. Handled provider
failures require their collection metric; they do not always become Lambda errors.

To halt new scheduled work:

```bash
aws events disable-rule --name "$FAREFLARE_SCHEDULE_NAME" --region "$FAREFLARE_REGION"
```

A running invocation may finish. Also record `schedule_enabled=false` in Terraform
inputs and apply a reviewed plan. Roll back application code by restoring the prior
API/worker digest pair. Retain current data unless a reviewed migration requires a
change; an older image may not understand a newer data format.

## Data recovery

DynamoDB uses encryption, deletion protection, point-in-time recovery, and TTL.
For data loss, stop scheduling and prevent account writes, restore to a **new**
table, and validate it before cutover. The module does not automate a restored-table
swap: review the configuration so API and worker use the same recovered data.
Keep the original table and versioned state for diagnosis.

Restoring account data can resurrect revoked credentials. Review authentication
epochs and sessions before reopening access, then validate tenant isolation,
collection freshness, and delivery. Rehearse restoration for your own installation;
a successful image rollback does not prove database recovery.

## API request concurrency

The API Lambda reserves eight concurrent executions so a browser can load its
assets in parallel. API Gateway still limits requests to 10 per second with a
burst of 20; authentication routes use stricter limits. The worker remains at one
concurrent execution. Watch Lambda `Throttles` alongside API Gateway 5xx metrics: a
rejected asset request can leave an otherwise successful page missing an image.
