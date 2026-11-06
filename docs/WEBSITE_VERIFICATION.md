# Fareflare interface verification

For the subsequent history, collection and onboarding release, see
[the current verification report](HISTORY_RELEASE_VERIFICATION.md).

This release removes personal origin content and retired tracker behavior from the
product and repository. The public site, authentication, dashboard, API/MCP setup,
and bot connection messages use the same product terminology.

## Changes reviewed

- Plus Jakarta Sans, a shared button theme, consistent alignment, and responsive
  navigation. Component templates use classes and external SCSS.
- Airline identification with local assets and readable fallbacks, clearer price
  and check states, and a compact flight summary.
- MCP/API connection selection, complete endpoints, copy feedback, and explicit
  credential handling.
- Landing page and guides with product-focused copy, crawlable initial HTML,
  canonical metadata, structured data, sitemap, RSS, and private-page noindex.
- Telegram uses one connection/help/disconnect behavior for every account.
  The product no longer invokes another tracker or exposes retired commands.
- Repository documentation, contributor instructions, issue templates, MIT license,
  private security reporting, and neutral self-hosting configuration.

## Verification

Backend compilation, Pyright, Ruff, and **635 tests** pass with **92.32% coverage**.
The removed application and migration-only tests are no longer part of this suite.
Angular compiles with strict TypeScript and template checking. Browser validation
uses the actual Python portal, including its CSP and session behavior.

The repository history was scanned with Gitleaks 8.30.1. Three matches were
verified examples: two placeholder API-key headers and one deterministic webhook
fixture. No live credential findings were identified. This is a scan result,
not a guarantee that every possible secret format is detectable.

Final results:

| Check | Result |
| --- | --- |
| Angular build and formatting | Passed; strict TypeScript/templates |
| Browser suite | 15 passed against the Python portal |
| API container | 55 files matched source/build hashes; 15 isolated checks passed |
| Worker container | 31 source files matched; runtime imports and headless browser passed |
| Live collection | A supported selected itinerary returned a verified quote |
| Production browser | 25 checks passed, including 8 accessibility scans |
| Browser failures | No runtime/CSP errors or failed asset requests in the final run |
| Secret scan | No live credentials found; two current-tree example/fixture matches reviewed |
| Dependency audit | No reported production npm vulnerabilities |

The live browser run completed at 2026-11-05T22:11:38.115Z. It created a disposable
account, checked its recovery/session behavior, exercised an API key and MCP's
20 tools, revoked the key, and deleted the account. It created no monitors or
outgoing alerts. Raw reports and credentials remain in ignored `.next/`.

## Deployment

The API and worker were deployed through a reviewed Terraform plan. The API no
longer has permission to invoke another tracker. Bot metadata now names Fareflare
and advertises only `/start`, `/help`, and `/stop`.

A first live check exposed one rejected image request at the API's four-request
concurrency limit. CloudWatch confirmed a Lambda throttle. The limit was raised
to eight; the complete live run then passed without failed assets. Request-rate
limits and the worker's single-execution limit remain in place.

The worker build reused five verified OS/browser layers from an existing image
because Debian snapshot package downloads were unavailable. All application and
Python dependency layers were excluded; current locked dependencies and source
were installed afterward. Both layer hashes and the resulting browser were
verified. The public Dockerfile remains independent of private images; a fresh
browser-base build requires the Debian snapshot service to be available.

Release image digests:

- API: `sha256:15151b7a6ff839728b0e863d81c4fab07a59f12c37d6ee4b41d47115a2a381a1`
- Worker: `sha256:322c69656605e265c678a0f0ed68e0b7ee4a908439dadd2198f28a5ef447beb3`

AWS readback confirmed successful updates. The pre-existing scheduled deployment
was not changed. No database migration was required. Billing remains disabled
and hosted registration remains invite-only.

## Review screenshots

- [Landing page](design/landing-desktop.png)
- [Flight dashboard](design/dashboard-desktop.png)
- [Mobile dashboard](design/dashboard-mobile.png)
- [API and MCP setup](design/developer-desktop.png)

See [design decisions](../DESIGN.md), [research](DESIGN_RESEARCH.md), and
[asset provenance](BRAND_ASSETS.md). The service currently uses an AWS origin;
changing domains requires updating its configured public URL and OAuth clients.
