# Fareflare dashboard

React and TypeScript customer interface, built with Vite and served by the Python portal on the same origin. Branding and development limits come from `GET /v1/config`. Billing is disabled; this interface contains no checkout or payment controls.

## Run and build

Use Node 24 and the repository’s Python development environment.

```sh
npm --prefix web ci
npm --prefix web run build
make product-serve
```

Open `http://127.0.0.1:8001`. Run `make product-invite` to create a local invitation; the invitation is written to a private file, never the frontend bundle. For hot reload, run `npm --prefix web run dev` alongside the portal. Vite proxies `/v1` and `/auth` to port 8001; cookie authentication requires matching origins, so use the built portal for account flows.

## Verify

```sh
npm --prefix web run build
npm --prefix web run format:check
npm --prefix web test
```

Playwright uses installed Google Chrome by default. Set `PLAYWRIGHT_CHROME_CHANNEL=chromium` after `npx --prefix web playwright install chromium` to use bundled Chromium. Tests launch Vite and an isolated SQLite-backed portal on ports 4173 and 8007. The portal fixture creates a temporary invitation, does not read `.env`, and never starts a collector or contacts AWS/Google. Browser tests cover real cookie signup/recovery/deletion, API-key revocation, monitor lifecycle, webhook verification, CSRF, idempotency, and WCAG checks with axe. Screenshots and reports stay in ignored directories.

## Structure and security

- `src/App.tsx`: authenticated shell, navigation, refresh, OAuth consent.
- `src/Monitors.tsx`, `Alerts.tsx`, `Integrations.tsx`, `Settings.tsx`: customer workflows.
- `src/api.ts`: same-origin requests, CSRF, errors, presentation helpers.
- `src/ui.tsx`, `styles.css`: semantic components and responsive styling.

Use two-space indentation, typed component props, and function components. Run `npm --prefix web run format` for the shared Prettier style. Keep changes within the relevant workflow module and use the shared request helper for cookie/CSRF handling.

Session cookies remain HttpOnly; CSRF tokens and one-time secrets remain in memory. Do not store credentials in local/session storage or URL parameters. Keep scripts, styles, and assets local to preserve the production Content Security Policy. React escapes customer content; never introduce raw HTML rendering. Native dialogs trap focus, support Escape, and return focus to their trigger. Match API schemas and use stable idempotency keys when retrying create requests.
