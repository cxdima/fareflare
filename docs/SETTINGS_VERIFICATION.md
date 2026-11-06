# Personal settings and interface verification

Verified locally on November 6, 2026. Implementation:
`8b4b1c73b75f38d006464877a3719168e3d1b334`.

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
| Playwright | 69 passed: 37 browser scenarios and 32 model cases |
| Production npm dependency audit | No known vulnerabilities reported |
| Staged secret scan | No findings |
| API container | 39 isolated checks; 58 matching source/build files |
| Worker container | 21 isolated checks; 34 matching source/lock files |

Tests cover real local account persistence, failed reads/saves, disabled controls
during saves, partial update races, tenant isolation, CSRF/origin enforcement,
preview escaping and stale responses. Time cases include both DST transitions,
the repeated Chicago hour, fractional-hour offsets and date-line boundaries.

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

## Deployment status

This revision is packaged and tested but **not yet deployed**. The AWS session
expired before deployment; the available long-term profile lacks Lambda access.
The live site remains on the [previous release](HISTORY_RELEASE_VERIFICATION.md).
After refreshing the normal AWS session, deploy the verified API and worker
images and run the disposable-account checks before recording a hosted release.

The regional and message settings are formatting controls, not interface
translations. Scheduled quiet hours and automatic currency conversion are not
implemented. Further settings proposals are in
[account preferences](ACCOUNT_PREFERENCES.md#possible-next-additions).
