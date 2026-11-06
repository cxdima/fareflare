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
mkdir -p .next
cp infra-next/backend.hcl.example .next/backend.hcl
cp infra-next/terraform.tfvars.example infra-next/production.auto.tfvars
```

Edit the copied files. Set your state bucket, a unique state key, region,
`expected_account_id`, and a resource name such as `fareflare-production`.
The AWS provider rejects a different authenticated account. Never share state
between installations. Backend files and variable files stay out of Git.

```bash
terraform -chdir=infra-next init -backend-config=../.next/backend.hcl
terraform -chdir=infra-next plan -out=../.next/fareflare.tfplan
terraform -chdir=infra-next apply ../.next/fareflare.tfplan
```

Review the saved plan before applying. On the **first** deployment, empty image
URIs create storage and ECR repositories without running application code.
Afterward, always preserve both deployed image URIs in your recorded inputs.
Empty image values on an existing deployment request removal, which lifecycle
protection rejects. Keep scheduling and delivery disabled until validation passes.

## Release API and worker images

Run backend and browser checks, then build both images. The API image packages
`web/dist`, so build the dashboard first. Build `Dockerfile` once as the Chromium
base; reuse a verified immutable base digest for subsequent worker releases.

```bash
make check
npm --prefix web ci
npm --prefix web run format:check
npm --prefix web run test:types
npm --prefix web run build
npm --prefix web test

docker buildx build --platform linux/arm64 --provenance=false --sbom=false --load \
  -f Dockerfile -t fareflare-browser-base .
docker buildx build --platform linux/arm64 --provenance=false --sbom=false --load \
  -f Dockerfile.api -t "$FAREFLARE_API_REPOSITORY:$FAREFLARE_RELEASE" .
docker buildx build --platform linux/arm64 --provenance=false --sbom=false --load \
  --build-arg BROWSER_BASE=fareflare-browser-base \
  -f Dockerfile.next -t "$FAREFLARE_WORKER_REPOSITORY:$FAREFLARE_RELEASE" .
```

Set `FAREFLARE_API_REPOSITORY`, `FAREFLARE_WORKER_REPOSITORY`, and
`FAREFLARE_RELEASE` to your ECR repository URLs and a new release tag. Authenticate
Docker to that registry, push both images, and retrieve their ECR image digests.
Set `api_image_uri` and `image_uri` to `REPOSITORY@sha256:DIGEST`. Record the source
revision, browser base, new digests, and previous digests privately.

```bash
docker push "$FAREFLARE_API_REPOSITORY:$FAREFLARE_RELEASE"
docker push "$FAREFLARE_WORKER_REPOSITORY:$FAREFLARE_RELEASE"
terraform -chdir=infra-next plan -out=../.next/fareflare.tfplan
terraform -chdir=infra-next apply ../.next/fareflare.tfplan
```

Validate health, account registration, tenant isolation, API key revocation, and
OAuth/MCP before inviting users. `product_delivery_enabled=true` activates the
customer inbox, Telegram, and verified webhook delivery paths. Measure collection
time and resource use before choosing `worker_max_targets`,
`worker_schedule_minutes`, and `schedule_enabled=true`. The default batch is one
target and the default dispatch interval is five minutes. Dispatch frequency is
not a guarantee of price freshness.

## Accounts, invitations, and capacity

Keep `registration_mode="invite"` and `billing_enabled=false` during development.
Enabling billing fails startup until a payment integration exists. Free access
does not eliminate AWS charges. Default limits are three monitors per account,
a 900-second minimum requested interval, and 20 distinct shared targets.
Equivalent targets share collection; account preferences remain private.

Issue a deployed invitation with an explicit account guard:

```bash
PYTHONPATH=src .venv/bin/python -m gfpt_next.product_cli \
  --public-url https://YOUR-API.execute-api.REGION.amazonaws.com \
  invite .next/invitation-UNIQUE.json --table fareflare-production \
  --aws-account YOUR_ACCOUNT_ID --region YOUR_REGION
```

Invitations expire after seven days and can be used once. The command creates the
output with private permissions and refuses to overwrite a file. Share the signup
URL only with its intended recipient. `make invite` uses local SQLite and
cannot invite someone to a deployed instance.

Recovery codes replace email resets. Recovery changes the password and invalidates
sessions, API keys, OAuth grants, and Telegram bindings. Account deletion requires
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
  --snapshot .next/telegram-before-UNIQUE.json --enable-callbacks
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
  --apply --snapshot .next/telegram-profile-before-UNIQUE.json
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
account before inviting users.

Restore the saved route when rolling back:

```bash
PYTHONPATH=src .venv/bin/python scripts/route_telegram.py \
  --secret-arn "$FAREFLARE_TELEGRAM_SECRET_ARN" \
  --aws-account YOUR_ACCOUNT_ID --region YOUR_REGION \
  --restore .next/telegram-before-UNIQUE.json
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

HTTP 200 from `/health` does not prove that collection is fresh. Inspect
`last_worker_at`, the DynamoDB `health:worker` record, monitor freshness and
`last_error`, and the API/worker CloudWatch logs. `GFPTNext` metrics include browser
starts/reuses, collection failures, skipped targets, delivery counts, and runtime.
Monitor Lambda throttles and dead-letter deliveries as well as exceptions.

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
