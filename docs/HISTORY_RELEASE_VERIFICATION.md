# Price history and collection verification

Verified on 2026-11-06 UTC. Implementation: `196584970e779c84f04ddb786707154150216090`.

## Changes

- Price history offers 7-day, 30-day and all-loaded views, dated chart axes,
  latest/low/high comparisons, and CSV exports. Comparisons use only the loaded
  observations in the chosen range. Gaps over twice the requested interval are
  disconnected; no price is inferred between checks.
- Monitor search and status filters work with explicitly loaded pages. Quota
  counts come from the account record. Refresh preserves loaded depth, cancels
  superseded requests and retains the previous snapshot when a later page fails.
- Anonymous collection waits for complete, verified page evidence within a
  cumulative 100-second budget. Wrong identity, currency, or fare eligibility
  fails immediately. Supported flight coverage and scheduling are unchanged.
- Signup has inline validation, password visibility and pending feedback.
  Public pages include original coastal artwork, an accessible FAQ and guide
  contents links. No new production dependencies were added.
- Documented `fareflare-*` table names are accepted alongside existing deployments.

## Automated checks

| Check | Result |
| --- | --- |
| Backend compilation, Pyright and Ruff | Pass |
| Backend suite | 685 passed; 92.34% coverage |
| Angular production build and formatting | Pass |
| Browser-test TypeScript check | Pass; added to CI |
| Playwright suite | 54 passed: 30 browser scenarios and 24 model cases |
| Previously failing pagination timing assertion | Fixed to await its response; five repeat runs passed |
| Production npm dependency audit | No known vulnerabilities reported |
| Gitleaks scan of staged changes | No findings |
| API container source/build comparison | 56 files match; 16 isolated checks passed |
| Worker container source comparison | All 31 Python files match |

The browser suite exercises the actual Python portal and CSP, session lifecycle,
keyboard behavior, desktop/mobile accessibility, request failures, pagination
races, quota display, date boundaries, CSV quoting and formula prefixes. Model
cases cover singleton/flat series, actual elapsed-time spacing, precise gap
boundaries, Unicode formula prefixes and JPY minor units. CSV exports contain
UTC timestamps and integer minor amounts; they do not contain account credentials.

## Read-only collection checks

The packaged worker collected these public quotes on its first attempt, without
accounts, database writes, or notifications:

| Check | Observed total | Runtime |
| --- | --- | --- |
| UA414, DEN to DFW, March 14, 2027, one adult | USD314.00, Economy | 2.082 seconds |
| Nonstop route search for the same date and airports | USD191.00, Economy Bundle, F9 2550 | 3.738 seconds |

Both validated itinerary identity, fare eligibility, party size and currency.
These are dated samples of existing capabilities, not evidence of broader
coverage or sustained collection reliability. Browser startup remains subject to
WebDriver process behavior; the deadline rejects late results rather than forcibly
terminating a process. The worker uses the previously verified Chromium base;
fresh Debian snapshot builds retain the availability limitation documented in
[the earlier verification](WEBSITE_VERIFICATION.md).

## Live release checks

The API and worker were deployed as immutable image digests. The reviewed
Terraform plan changed only the two Lambda images. Billing remains disabled,
registration invite-only, and collection/concurrency limits unchanged.

All **25 production checks** passed: public assets and metadata, desktop/mobile
layouts, eight accessibility scans, invitation signup, password login, HttpOnly
sessions, API-key creation/revocation, hosted MCP discovery of 20 tools and account
deletion. No browser runtime, CSP or asset-loading errors were detected. The
disposable account was deleted, no monitors were created and no notifications
were sent. History data interactions are covered locally by the browser suite;
the live account-flow check uses an empty account.

Image digests:

- API: `sha256:855cc115a2a670eac641095bf936bcfdbc1caf8dd063e3c1a4e2fe639114e62f`
- Worker: `sha256:4a3f26318eef9bb6a78b2e7d8fee9717166a2596b164cc629de47a3378c73e66`

## Visual review

Desktop and 375-pixel mobile layouts were reviewed. Charts retain a semantic data
table, controls have visible labels and focus indicators, and all styling uses
classes. The new editorial artwork is a locally served 117 KB WebP.

- [Landing page](design/landing-desktop.png)
- [Flight dashboard](design/dashboard-desktop.png)
- [History desktop](design/history-desktop.png)
- [History mobile](design/history-mobile.png)
