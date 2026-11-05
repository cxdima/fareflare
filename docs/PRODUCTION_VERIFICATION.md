# Production comparison verification

Verified November 4, 2026. The new `gfpt-next-production` worker is deployed in
`us-east-1`, in the same AWS account as the family tracker. Its five-minute
EventBridge schedule is enabled. It monitors the original UA414 sample with a
900-second requested interval; the three additional verification monitors are paused.
All new-system notifications are suppressed. The existing family tracker continues
running its original image and 15-minute schedule.

The exact image digests, source checksum, Terraform inputs, observation timestamps,
and Lambda report are in [the deployment manifest](deployments/2026-11-04-shadow.json).

## What was verified

| Case | Observed total | Result |
| --- | --- | --- |
| DEN–DFW UA414, March 14, one adult | USD 309 | Active comparison monitor |
| Same selected flight, two adults | USD 617 | Verified; monitor now paused |
| Same selected flight, one adult, JPY | JPY 48,883 | Verified; monitor now paused |
| UA414 outbound / UA2049 return March 21 | USD 577 | Verified; monitor now paused |

The first automatic scheduled invocation collected and processed one observation
successfully. Its unchanged price generated no new alert. Across the verification
cases, four initial alerts were durably marked `suppressed`, with **zero delivery
attempts** and **zero messages sent**.

That scheduled invocation took 7,128.65 ms, billed 7,129 ms at 2,048 MB, and used a
reported peak of 559 MB. This is one measured sample, not a latency guarantee.
Its compute usage was approximately 14.258 GB-seconds. Other runs included startup
costs and retries; idle invocations, DynamoDB, ECR, logs, storage, and the account's
existing free-tier usage must also be considered before predicting monthly cost.
The old tracker batches saved flights, so these single-target measurements do not
establish which collector is cheaper at a larger watch count.

## Changes discovered through production testing

The existing deployed image supplied the pinned Chromium 146 ARM64 base, avoiding
the stalled Debian snapshot download. The new image builds separately on that
immutable base; the family function was not updated.

Initial probes exposed browser failures and a page timeout. The new adapter now
uses the stable runtime's Lambda process settings and logs only a safe failure
phase/category. Readiness depends on the selected booking fare; unrelated loading
text elsewhere on the page cannot hold up a valid quote. Failed checks retain the
last validated price and never advance alert baselines. These successful probes
are not a long-running reliability test.

Real DynamoDB index propagation delayed discovery of freshly committed events.
The worker now passes durable event IDs to event processing and delivery IDs to
the outbox. Strong reads allow those stages to run in the same invocation. Index
queries remain the recovery path after a restart. Tests cover missing new index
rows and stale completed rows, without sacrificing ownership or FIFO delivery.
Pending events have no expiry; processed events retain their seven-day TTL.

## Infrastructure and verification

- New resources use the `gfpt-next-production` prefix and separate Terraform state
  at `s3://gfpricetracker-terraform-state/gfpt-next-production/terraform.tfstate`.
- The worker role can access its own document table/index and log streams. It has
  no permission to read family account state or Telegram secrets.
- The worker has one reserved invocation, 2 GB memory, and a 180-second timeout.
- Terraform rejects another AWS account and prevents accidental deletion of the
  worker, repository, and table. The table also has AWS deletion protection.
- `make next-check` passed: **563 tests, 92.23% coverage**, syntax, types, and lint.
- ARM64 container and actual Lambda checks passed. Terraform validation passed;
  the final plan reported no changes.
- The family image digest, function modification timestamp, and enabled schedule
  match their pre-deployment values. Existing `AGENTS.md` is unchanged.

## Reproduce and operate

Authenticate to the recorded account and ECR registry. Use `browser_base_image`
from the deployment manifest as `BROWSER_BASE` when building `Dockerfile.next`;
pass `--platform linux/arm64 --provenance=false`. Push under a new immutable tag,
then use the ECR digest URI in the next Terraform plan.

Before planning from a fresh checkout, restore the nonsecret recorded inputs:

```bash
python3 - <<'PY'
import json
from pathlib import Path
record = json.loads(Path('docs/deployments/2026-11-04-shadow.json').read_text())
path = Path('infra-next/production.auto.tfvars.json')
with path.open('x') as output:
    json.dump(record['terraform_inputs'], output, indent=2)
PY
terraform -chdir=infra-next init
terraform -chdir=infra-next plan
```

Inspect `health:worker`, CloudWatch `GFPTNext` counters, and the new log group.
`alerts_sent` must remain zero during comparison. Collection failures have a
separate alarm because handled provider failures do not count as Lambda crashes.
Alarms currently report in CloudWatch; no Telegram or SNS destination is attached.

To stop this comparison immediately:

```bash
aws events disable-rule --name gfpt-next-production-schedule --region us-east-1
```

Then set `schedule_enabled` to `false` in the ignored production inputs and apply
a reviewed Terraform plan so configuration matches the stopped state. This does
not affect the family schedule. The new worker's Telegram secret ARN is empty;
keep it empty until notification and command-routing transition work is complete.

## Remaining transition work

Observe sustained freshness and failure rates, finish family command/removal/health
notification parity, review the family export and low-watermarks, and validate the
full cutover/rollback procedure before switching the family bot. Connections,
additional passenger types/cabins/markets, explicit baggage/refund filters, hosted
API/MCP access, and commercial capacity/billing remain separate release work.
The five-minute dispatcher can extend a target's requested interval; this release
does not promise sub-minute detection or a fixed polling SLA.
