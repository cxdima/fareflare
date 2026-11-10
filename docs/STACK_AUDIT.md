# Frontend stack audit

Audited November 6, 2026, after a browser extension reported both Angular and React.

Fareflare's web application uses Angular 22, Bootstrap 5, Bootstrap Icons and locally hosted Plus Jakarta Sans. The npm lockfile contains no React, React DOM or React reconciler package. The production bundles checked during this audit contained no React runtime signatures.

A fresh Chrome context without extensions loaded the public site, sign-in page and API reference. Its scripts came from Fareflare's own origin; no React globals, mounted React roots, fiber properties or registered React renderers were found. The unauthenticated dashboard request redirected to sign-in; it also downloaded the dashboard bundle. This does not establish what the reporting extension observed in the user's authenticated browser. The screenshot's exact cause remains unverified.

After deployment, the [production settings verification](SETTINGS_VERIFICATION.md)
also checked a clean, authenticated workspace. It found Angular, no React globals
or mounted renderer markers, and no external scripts. The API reference remained
script-free and `/redoc` returned 404.

## Removed dependency path

The standalone Python API still exposed FastAPI's default Swagger UI and ReDoc pages. These documentation applications introduce an additional frontend stack. The hosted portal already replaced those pages with its own static reference.

Both entry points now disable the default documentation applications and use the same script-free HTML reference at `/docs`. `/openapi.json` remains available. `/redoc` and the Swagger OAuth callback are absent. The reference preserves endpoint summaries, authentication instructions and the schema download.

## Verification

- `tests/test_api_reference.py` checks both reference rendering and the standalone routing contract, including HTML escaping and protected API access.
- `web/tests/stack.spec.ts` checks the served public site and mocked authenticated workspace, loaded scripts, Bootstrap styles, React runtime markers and the script-free reference.
- Keep the dependency lockfile committed and run the browser regression after changes to documentation viewers, embedded widgets or frontend dependencies.

Detection labels alone do not identify the responsible script. A [public Wappalyzer rules snapshot](https://github.com/ahrefs/Wappalyzer/blob/master/src/technologies/r.json) includes React DOM, global and script-name signatures; it is not proof of the rules used by a particular installed extension. FastAPI documents disabling its bundled documentation pages with [`docs_url` and `redoc_url`](https://fastapi.tiangolo.com/tutorial/metadata/#docs-urls).
