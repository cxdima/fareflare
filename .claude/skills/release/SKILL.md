---
name: release
description: Release Fareflare to production (fareflare.dev on AWS) — build, verify, push, plan, apply, smoke-test, watch and record a commit on main, or roll a release back. Use when the maintainer asks to deploy or release a change.
---

# Release Fareflare to production

[docs/OPERATIONS.md](../../../docs/OPERATIONS.md#release-api-and-worker-images) is the
procedure for any installation. This is the hosted service's run of it, with its scripts
in `scripts/release/`. Work in the main checkout's root, on `main`, with the release
commit pushed. Each release keeps its logs, plan and record in the git-ignored
`.fareflare/release-<short sha>/` (`$R` below).

## Gates

Stop at the first that fails and tell the maintainer.

1. **AWS session.** `command aws sts get-caller-identity`. `ExpiredToken` means the
   maintainer has to refresh their MFA session: ask for it before building anything.
2. **Clean and green.** `git status` shows nothing to commit, and CI passed for the commit:
   `gh run list --commit $(git rev-parse HEAD)` (the full hash; a short one finds nothing).
3. **Go-ahead.** A release changes what people use. Apply only after the maintainer has
   said to deploy this change; approval of one release does not cover the next.

## Steps

```bash
sha=$(git rev-parse --short HEAD); R=.fareflare/release-$sha
scripts/release/build.sh                                  # web build and both images
.venv/bin/python scripts/release/verify_api.py fareflare-api:$sha > $R/api-verify.log
tail -1 $R/api-verify.log                                 # must be FAILURES: none
```

Before pushing, as the change requires:

- **How links are read** (`links.py`, `search_links.py`, `limits.py`, `refusals.py`): the
  read-only plan, `PYTHONPATH=src .venv/bin/python -m fareflare.reidentify --table
  gfpt-next-production`, must say the migration is [done](../../../docs/OPERATIONS.md#when-the-migration-is-done). If it does
  not, this is an identity-changing release: see below.
- **Intake or collection** (`links.py`, `search_links.py`, `limits.py`, `public_browser.py`,
  `public_quotes.py`, Selenium, the browser base, `awslambdaric`): one live quote in the new
  worker image (CONTRIBUTING.md), through the address the importer writes. A refusal from
  Google (`provider_error`, a challenge) is about Google, not the image: run the same
  quote with the deployed image to tell them apart.

```bash
scripts/release/push.sh       # skips images production already runs; tfvars only after verified pushes
PYTHONPATH=src .venv/bin/python -m fareflare.publish_web \
  --bucket "$(terraform -chdir=infra output -raw web_bucket)" \
  --distribution "$(terraform -chdir=infra output -raw cdn_distribution_id)" > $R/publish-web.log
terraform -chdir=infra plan -no-color -out="$PWD/$R/release.tfplan" > $R/plan.log
grep -E "^Plan:|will be|must be|^\s+[-+~] " $R/plan.log
```

Upload the website before apply: a new page must never name a script the site does not
have yet. `publish_web` never deletes and invalidates the changed `/assets/` files.

The plan must show only what this release changes. For a code release that is the two
`image_uri` values (and their computed `last_modified`); for a web-only change, the API
image alone. Anything else: stop and explain it to the maintainer. Never `apply -target`:
it pulls in everything the target references.

```bash
terraform -chdir=infra apply -no-color "$PWD/$R/release.tfplan" > $R/apply.log
date -u +%Y-%m-%dT%H:%M:%SZ > $R/applied-at.txt
.venv/bin/python scripts/release/smoke.py > $R/smoke.log; tail -1 $R/smoke.log     # FAILURES: none
PYTHONPATH=src .venv/bin/python scripts/release/watch.py --since "$(cat $R/applied-at.txt)" \
  > $R/watch.log; tail -1 $R/watch.log                    # FRESH n/n: every flight priced again
.venv/bin/python scripts/release/record.py --change "<what changed>" --verified "<what was checked>"
```

- Read the `FAILURES:` line itself. Counting lines with "FAIL" also counts `FAILURES: none`.
- `watch.py` runs up to 25 minutes, so start it in the background. For a change to check
  timing, use `--prices 3` and compare the gaps with the interval and retry it prints.
- `scripts/release/state.py` prints one line per itinerary (due, interval, failures, lease)
  whenever production's checks need a look.

Report to the maintainer: what went out, the smoke and watch lines, and the rollback.

## Identity-changing release

When the plan above moves or merges flights, the release follows
[A release that changes how links are read](../../../docs/OPERATIONS.md#a-release-that-changes-how-links-are-read) instead of applying
straight away: a table backup, `admin_cli pause-checks`, the deploy below, `reidentify
--apply $sha`, plans until the migration is [done](../../../docs/OPERATIONS.md#when-the-migration-is-done), then `admin_cli
resume-checks`. Show the maintainer the plan (every move, merge and stopped flight) and
get the go-ahead for it as well as for the deploy. The run's [saved file](../../../docs/OPERATIONS.md#the-saved-file)
is in `$R/reidentify/`; `--restore` undoes the run from it.

## Rollback

```bash
cp $R/production.auto.tfvars.before.json infra/production.auto.tfvars.json
terraform -chdir=infra plan -no-color -out="$PWD/$R/rollback.tfplan"   # the image values return
terraform -chdir=infra apply -no-color "$PWD/$R/rollback.tfplan"       # with the go-ahead
.venv/bin/python scripts/release/smoke.py
```

Each image repository keeps its newest ten images, so a rollback can reach ten releases
back. Rolling back images does not undo a data migration: after an identity-changing
release, pause checks and run `reidentify --restore` with the release's file first.
