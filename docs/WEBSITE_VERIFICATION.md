# Fareflare interface verification

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

Build, browser, container, and production readback results for the completed
rollout are recorded below before publication. Raw reports and any disposable
credentials stay in ignored `.next/`; screenshots use test accounts/data.

## Review screenshots

- [Landing page](design/landing-desktop.png)
- [Flight dashboard](design/dashboard-desktop.png)
- [Mobile dashboard](design/dashboard-mobile.png)

See [design decisions](../DESIGN.md), [research](DESIGN_RESEARCH.md), and
[asset provenance](BRAND_ASSETS.md). The service currently uses an AWS origin;
changing domains requires updating its configured public URL and OAuth clients.
