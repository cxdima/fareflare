# Angular website release verification

Verified and deployed November 5, 2026. The public site is
<https://8jq9j5zhif.execute-api.us-east-1.amazonaws.com>; the account dashboard is
`/app`. This update replaces the React/Vite frontend with Angular 22.2.4 and
Bootstrap 5.3.8 while keeping the existing Python application and collector.

## Delivered

- Editorial landing page, generated wing-shaped F logo and window-seat image,
  consistent Bootstrap Icons, locally served fonts, and responsive dashboard.
- Class-based standalone components with OnPush, signals/Signal Forms, external
  HTML/SCSS, API/session/workspace facades, and a Strategy implementation for
  selected-itinerary versus route-search presentation. No style attributes or
  style bindings in application templates.
- Nine public pages, including three substantial guides, project story, developer
  information, and factual preview privacy/terms pages. Native links preserve
  document metadata across public/private navigation.
- Shared server/client article content; unique titles/descriptions, canonicals,
  Open Graph, Organization/WebSite/SoftwareApplication/BlogPosting/BreadcrumbList
  JSON-LD, sitemap, robots, RSS, and genuine HTTP 404s. No fabricated ratings.
- Private account and credential-bearing URLs are `noindex`. Angular styles and
  structured data receive a fresh CSP nonce; `unsafe-inline` and inline style
  attributes remain disallowed. Public assets use an explicit safe allowlist.

The [design system](../DESIGN.md), [research](DESIGN_RESEARCH.md), and
[asset prompts/provenance](BRAND_ASSETS.md) record the decisions.

## Validation

| Check | Result |
| --- | --- |
| Backend compile/Pyright/Ruff/pytest | **978 passed**, **92.05% coverage** |
| Angular production build | Strict TypeScript/templates passed; no build warnings |
| Formatting and dependency audit | Prettier passed; zero reported production dependency vulnerabilities |
| Browser suite | **13 passed** against the real Python portal and CSP |
| Live production browser | **23 checks passed**; **6 axe scans**, zero observed violations |
| Browser runtime/security | Zero observed runtime/CSP errors; no inline style attributes; no mobile page overflow |
| Public HTTP checks | All nine pages, canonical/JSON-LD, sitemap/RSS, private noindex, 404, docs, and authenticated API boundary passed |
| Container packaging | All **49 packaged source/build files** matched the tested local versions |

Browser coverage includes the real signup/recovery/deletion cookie flow, distinct
one-time-secret fields, CSRF, API-key revocation, monitor actions and idempotent
retries, policies/history, webhook controls, OAuth consent/grant controls, native
dialog focus, mobile layouts, public interactions, and guides without JavaScript.

The production run at **10:02:56–10:03:13 UTC** created a disposable account through
the legacy invitation URL, displayed its recovery code, exercised an API key and
MCP's 20 tools, signed out/in, and deleted the account through the UI. Its revoked
session returned 401. It created no monitors or outgoing notifications. Private
credentials and raw reports remain in ignored `.next/`.

## Deployment and rollback

The reviewed Terraform plan updated **only** `gfpt-next-production-api` to:

`sha256:8b2355b1798970c3ec05309e3e53429d5ce313c27a4a9c7401155bc7909ca6f7`

Its previous image was
`sha256:3b348d32bb8e0cfb42ddcb0d4495c44191797be30e7f427bfb7f3b97c03916e1`.
Both belong to ECR repository `gfpt-next-production-api` in AWS account
`851725466918`, region `us-east-1`. Follow [operations](OPERATIONS.md) to restore a
pinned image through the isolated Fareflare Terraform state. No database migration
was required. A rollback was prepared, not executed.

AWS readback confirmed the Fareflare worker image, original family image,
family Lambda last-modified timestamp, and enabled 15-minute family schedule were
unchanged. Invite-only access, disabled billing, and capacity limits remain active.
This release adds no Node server or external font/CDN dependency.

## Review screenshots

These local screenshots use labeled test data, not a real customer account:

- [Landing page](design/landing-desktop.png)
- [Desktop dashboard](design/dashboard-desktop.png)
- [Mobile dashboard](design/dashboard-mobile.png)

The website currently uses the temporary AWS origin. A future custom domain must
update the configured public URL and OAuth clients. Search Console verification
and sitemap submission were not performed; structured data does not guarantee
indexing, rankings, or rich results. Collection and notification limitations from
the [initial release](RELEASE_VERIFICATION.md) still apply.
