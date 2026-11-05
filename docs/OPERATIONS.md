# Fareflare Operations

This is the operator runbook for the free, invite-only development release. It
describes implemented controls and deployment procedures; it is not evidence that
a particular image, bot cutover, or recovery has been verified in production. Keep
the tested image digests and actual Terraform inputs in a dated deployment record.
The older [shadow verification](PRODUCTION_VERIFICATION.md) documents that earlier
release, not the current customer application.

## Accounts, invitations, and development limits

The dashboard, REST API, and hosted MCP share the same accounts and monitors.
Default limits are three monitors per account, a 900-second minimum requested
interval, and 20 distinct shared collection targets. Dispatcher frequency, browser
failures, and queueing can extend observation gaps. A price low means the lowest
price observed since monitoring began; there is no guarantee of observing every
market change. Cancellation, departure, and account deletion release monitor
capacity; shared targets remain reserved while another subscriber needs them.

Keep `registration_mode="invite"` and `billing_enabled=false`. Billing is disabled
on the server and in Terraform; enabling the flag fails rather than starting
unimplemented payments. Free customer access does not eliminate AWS charges.
Review CloudWatch usage and AWS costs before raising limits.

Create a seven-day, single-use invitation for the deployed table:

```bash
umask 077
mkdir -p .next
PYTHONPATH=src .venv/bin/python -m gfpt_next.product_cli \
  --public-url https://YOUR-API.execute-api.us-east-1.amazonaws.com \
  invite .next/invitation-UNIQUE.json --table gfpt-next-production \
  --aws-account 851725466918 --region us-east-1
```

The command verifies the AWS account and creates the output exclusively with
mode `0600`; it will not replace an existing invitation file. Share its URL only
with the intended person. Local `make product-invite` uses SQLite, so it cannot
onboard a deployed account. Invitation files, API keys, recovery codes, and session
cookies belong outside Git.

Customers download one recovery code during signup. Recovery replaces that code,
changes the password, and invalidates existing sessions, keys, OAuth grants, and
Telegram bindings. No email reset provider or operator password-reset backdoor is
configured. Account deletion requires the password, stops future collection and
delivery for that account, and removes its Telegram association; it does not erase
shared price observations belonging to other subscribers.

OAuth dynamic registration admits public PKCE clients and has a permanent global
cap of **1,000 registered clients**. The count is not automatically reclaimed.
Per-IP registration limits also apply. Plan client cleanup or a revised admission
policy before reaching this cap; increasing it blindly removes a storage bound.

## Release API and worker images

Use only `infra-next/` for Fareflare. Its current backend is
`s3://gfpricetracker-terraform-state/gfpt-next-production/terraform.tfstate`.
The family stack uses a different key. Terraform's `expected_account_id` guard
defaults to `851725466918`; the resource prefix must start with `gfpt-next-`.
For another installation, explicitly override the backend bucket/key/region and
account ID. Never point this module at the family state.

1. Confirm `aws sts get-caller-identity` and restore the **latest** recorded inputs
   into ignored `infra-next/production.auto.tfvars.json`. Preserve both image URIs
   and all delivery/schedule settings. Empty image defaults request resource
   removal on an existing deployment, which lifecycle protection rejects.
2. Run `make next-check`, `npm --prefix web ci`, `npm --prefix web run build`, and
   `npm --prefix web test`. Build the dashboard before packaging the API.
3. Build ARM64 images with fresh immutable ECR tags. Set `BROWSER_BASE` to the
   previously verified immutable browser image URI; the worker extends that image.

```bash
docker buildx build --platform linux/arm64 --provenance=false --load \
  -f Dockerfile.api -t "$FAREFLARE_API_REPOSITORY:$FAREFLARE_RELEASE" .
docker buildx build --platform linux/arm64 --provenance=false --load \
  --build-arg BROWSER_BASE="$FAREFLARE_BROWSER_BASE_DIGEST" \
  -f Dockerfile.next -t "$FAREFLARE_WORKER_REPOSITORY:$FAREFLARE_RELEASE" .
docker push "$FAREFLARE_API_REPOSITORY:$FAREFLARE_RELEASE"
docker push "$FAREFLARE_WORKER_REPOSITORY:$FAREFLARE_RELEASE"
```

Authenticate Docker to the intended ECR registry first. Obtain each pushed
`imageDigest` with ECR `describe-images`. Set `api_image_uri` and `image_uri` to
`REPOSITORY@sha256:DIGEST`, not mutable tags. Record the source revision, browser
base digest, both new digests, and previous digests for rollback.

```bash
terraform -chdir=infra-next init
terraform -chdir=infra-next plan -out=../.next/fareflare.tfplan
terraform -chdir=infra-next apply ../.next/fareflare.tfplan
```

Review the saved plan before applying: changes must belong to the intended
Fareflare resources. For first deployment, start with scheduling disabled. Test
the application health, invitation login, account isolation, API key revocation,
and OAuth/MCP flow before admitting users. Enable `product_delivery_enabled=true`
for dashboard/Telegram and verified webhook delivery. Then choose
`worker_max_targets`, `worker_schedule_minutes`, and `schedule_enabled=true` from
measured collection time and cost. The default worker batch is one target and the
default wake-up interval is five minutes. Terraform does not switch the bot URL.

## Shared Telegram configuration and routing

Store this JSON shape in the configured Secrets Manager secret:

```json
{
  "bot_token": "REDACTED",
  "bot_username": "gfpricetrackerbot",
  "legacy_chat_ids": [111111111, 222222222],
  "webhook_secret": "EXACT_EXISTING_WEBHOOK_SECRET"
}
```

Set `customer_telegram_secret_arn` and `legacy_bot_function_arn` in the private
Terraform inputs. API IAM permits reading only that secret and invoking only the
specified family Lambda. The worker reads the bot secret without invoking the
family handler. The existing family handler derives its webhook secret from
`sha256("gfpt-webhook:" + bot_token)[:40]`; retain that exact configured value for
forwarding and rollback. `getWebhookInfo` does not disclose the secret.

Fareflare validates the incoming webhook credential. Explicit `ff_` connection
payloads stay in Fareflare, require a private chat matching the sender, expire in
ten minutes, and can be used once. Family commands are forwarded to the unchanged
legacy HTTP handler with its expected secret; no tracker event is constructed.
Family `/mute` preferences continue to govern legacy alerts. Manage Fareflare
preferences and family-account Telegram connections in the dashboard during the
transition. Other connected customers can use `/help` and `/stop`.

After live API checks, switch the single shared bot using a new snapshot filename:

```bash
PYTHONPATH=src .venv/bin/python scripts/route_telegram.py \
  --secret-arn "$FAREFLARE_TELEGRAM_SECRET_ARN" \
  --aws-account 851725466918 --region us-east-1 \
  --url https://YOUR-API.execute-api.us-east-1.amazonaws.com/telegram/webhook \
  --snapshot .next/telegram-before-UNIQUE.json
```

The script verifies AWS identity, restricts the secret to that account/region,
reads the existing route, and durably writes a new `0600` snapshot **before**
changing it. It preserves allowed update types, uses four webhook connections,
keeps pending updates, reuses the configured secret, and checks the resulting
route. It prints no bot credentials. It refuses custom-certificate webhooks
because their certificate cannot be recovered from Telegram's readback.
It does not rename the bot or register bot commands.

Validate a normal family command and a customer connection after switching.
Rollback the routing with the same secret and private snapshot:

```bash
PYTHONPATH=src .venv/bin/python scripts/route_telegram.py \
  --secret-arn "$FAREFLARE_TELEGRAM_SECRET_ARN" \
  --aws-account 851725466918 --region us-east-1 \
  --restore .next/telegram-before-UNIQUE.json
```

Rollback restores the saved URL, update types, and connection limit. It rejects
a different bot, changed secret, public snapshot permissions, or an unrelated
newer route. Repeating an already completed rollback is a read-only operation.
DNS is resolved normally; the observed previous IP address is not pinned.
Preserve the snapshot if a request or readback fails. Restoring the webhook only
changes inbound command routing: outbound worker notifications are separate.
Pause onboarding while customer connection commands are routed to the legacy bot.
See the [Telegram Bot API](https://core.telegram.org/bots/api#setwebhook) for the
underlying webhook fields.

## Health, incidents, and restoration

`GET /health` returns `last_worker_at`; HTTP 200 alone does not establish collection
freshness. Inspect the DynamoDB `health:worker` document, monitor freshness and
`last_error`, and CloudWatch logs at `/aws/lambda/gfpt-next-production` and
`/aws/lambda/gfpt-next-production-api`. Worker `GFPTNext` metrics include collection
failures, skipped targets, browser starts/reuses, delivery counts, and runtime.
Allow for the configured dispatch interval and the 180-second invocation limit.

Terraform defines `gfpt-next-production-errors`,
`gfpt-next-production-api-errors`, and `gfpt-next-production-collection-failures`.
They evaluate five-minute windows; handled provider failures need their separate
collection alarm. These alarms have no notification destination configured. Add
an operator destination before relying on unattended incident reporting. Also
watch throttles, stale heartbeats, and dead-letter deliveries; not every operational
failure becomes a Lambda exception.

To halt Fareflare collection and outbound delivery immediately:

```bash
aws events disable-rule --name gfpt-next-production-schedule --region us-east-1
```

An invocation already running may finish. Set `schedule_enabled=false` in the
recorded inputs and apply a reviewed plan to keep Terraform consistent. This
leaves the family schedule running. Roll back application code by restoring the
previous API/worker digest pair in those inputs and applying another reviewed
plan; do not delete resources or downgrade incompatible data without review.

On a new workstation, restore the repository, locked dependencies, latest
nonsecret deployment manifest, AWS authentication, and isolated backend inputs.
Secrets remain in Secrets Manager; do not recreate production credentials from
test examples. `scripts/restore_env.sh` and `make deploy` target the legacy stack
and are intentionally blocked in this checkout.

DynamoDB has point-in-time recovery, encryption, deletion protection, and TTL.
For data loss, first stop the Fareflare schedule and prevent new account writes;
restore a selected point to a **new** table and validate it before choosing a
cutover. The current module has no automatic restored-table swap: prepare and
review the table/configuration migration so API and worker use the same restored
data. Keep the original table and versioned Terraform state for diagnosis.
Restoring old account state can resurrect credentials previously revoked; review
authentication epochs and customer sessions before reopening access. Validate
freshness, delivery routing, and account isolation before resuming the schedule.
