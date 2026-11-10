# Personal settings and interface verification

Verified locally and in production on November 6, 2026. Settings implementation:
`8b4b1c73b75f38d006464877a3719168e3d1b334`; loading-state corrections:
`c8282186ef86510c7ef19fb8e3f1907021f908c5`.

## Changes

- Account settings persist an IANA time zone, one of six regional formats and a
  12/24-hour clock preference. Observations use that zone; flight departure dates
  keep their airport calendar day. Currency is formatted without conversion.
- Telegram supports compact or detailed messages, optional flight numbers,
  observed time and fare names, and silent delivery. The preview renders sample
  data without sending messages or saving drafts.
- Partial updates preserve unrelated preferences. Presentation changes preserve
  queued notifications; muting changes retain the existing delivery fence.
- The Angular/Bootstrap layout uses softer sage surfaces, underlined navigation,
  themed buttons with plane flight actions and a grouped profile/sign-out area.
  Styles remain in classes and SCSS.
- Both API entry points share a script-free reference. The separate
  [stack audit](STACK_AUDIT.md) records the React investigation and its limits.

## Automated checks

| Check | Result |
| --- | --- |
| Python compilation, Pyright, Ruff | Pass |
| Backend tests | 761 passed; 92.58% coverage |
| Angular production build, formatting, test TypeScript | Pass |
| Playwright | 72 passed: 40 browser scenarios and 32 model cases |
| Production npm dependency audit | No known vulnerabilities reported |
| Staged secret scan | No findings |
| API container | 39 isolated checks; 58 matching source/build files |
| Worker container | 21 isolated checks; 34 matching source/lock files |

Tests cover real local account persistence, failed reads/saves, disabled controls
during saves, partial update races, tenant isolation, CSRF/origin enforcement,
preview escaping and stale responses. Time cases include both DST transitions,
the repeated Chicago hour, fractional-hour offsets and date-line boundaries.
Three loading regressions use gated responses and virtual time to check the
refresh button's accessible name, hash navigation before requests settle and
teardown without late workspace reads or polling.

Both containers ran without networking, AWS credentials or writable application
files. Their IANA data supports Chicago and Kolkata. Telegram checks use a mock
transport; no real notifications were sent. The worker retains its previously
verified browser base and collection behavior. No dependency or infrastructure
configuration changes are required.

## Visual review

Desktop and 375-pixel mobile views passed accessibility scans and visual review.
The profile link's accessible name now includes its visible username; the
original custom label failed the label-in-name check. The settings test measures
class-only styling before axe's temporary control measurements and reloads
between viewport audits.

- [Desktop dashboard](design/settings-dashboard-desktop.png)
- [Mobile dashboard](design/settings-dashboard-mobile.png)
- [Desktop settings](design/preferences-desktop.png)
- [Mobile settings](design/preferences-mobile.png)

## Live release checks

The API and worker were deployed as immutable image digests. The reviewed first
plan changed only those two Lambda images; the loading correction changed only
the API image. Both functions are Active with Successful updates. Environment
variables and reserved concurrency match the pre-deployment snapshot. Billing
remains disabled and registration invite-only. The original tracker image,
configuration and modification time are unchanged.

The first live run caught a label-in-name failure while the refresh button was
busy and a hash navigation timeout during initial loading. Both were corrected
and covered by the deterministic regressions above. The final run passed all
**32 production checks**, including nine accessibility scans, invitation signup,
password login, API-key creation/revocation, 20-tool MCP discovery, settings
persistence, script-free documentation and account deletion.

The live preferences check saved Chicago time, German regional formatting and a
24-hour clock, then previewed compact, silent Telegram options. Previewing did
not persist the draft; saving and reloading retained the chosen values without
changing muting. A clean authenticated browser found Angular and no React globals,
mounted renderer markers or external scripts. This does not identify the cause
of the original extension report.

No runtime, CSP, asset-loading or server errors were recorded in the final run.
Both disposable test accounts were deleted. Tests created no monitors, connected
no Telegram account and sent no external notifications. Telegram delivery itself
was checked with a mock transport in the packaged worker.

Final image digests:

- API: `sha256:83a369f3b6e856b58eed92e43b90f78e536defba412707665c6ec07e9e4c4e03`
- Worker: `sha256:510a052b50f4dd1ec85b9c1ec8a67e7004d8812b8e9d4ae4b178d86c84f589bd`

The regional and message settings are formatting controls, not interface
translations. Automatic currency conversion is not implemented. Quiet hours were
added after this verification and silence messages rather than delaying them; see
[account preferences](ACCOUNT_PREFERENCES.md#quiet-hours). Further settings proposals are in
[account preferences](ACCOUNT_PREFERENCES.md#possible-next-additions).
