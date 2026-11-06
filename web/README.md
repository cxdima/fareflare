# Fareflare website and dashboard

Angular 22 standalone components, Bootstrap 5.3, and external SCSS. The Python
portal serves the public website, account interface, REST API, and MCP on one
origin. Public content is readable without JavaScript. No Node server runs in AWS.

## Run locally

Use Node 24 and the repository's Python environment:

```sh
npm --prefix web ci
npm --prefix web run build
make invite
make serve
```

Open `http://127.0.0.1:8001`; the dashboard is `/app`. The local signup URL is in
`.next/invitation.json`. Keep it private. `npm --prefix web run dev` starts Angular's
development server and proxies API requests. Use the built Python portal for
complete session, CSP, and SEO behavior; its configured public origin must match
the browser origin for account mutations.

## Code organization

- `src/app/core/`: typed API transport, session facade, shared contracts, formatters,
  and the public content client.
- `src/app/dashboard/`: feature components, workspace facade, dialogs, and selected
  itinerary/route-search presentation strategies.
- `src/app/auth/`: login, invitation signup, and recovery using Angular signal forms.
- `src/app/public/`: landing page and editorial content views.
- `src/styles.scss`: design tokens, Bootstrap theme, local fonts, and shared classes.
- `../src/gfpt_next/site_content.py`: public content, metadata, structured data,
  sitemap, and crawlable HTML source.

Use component classes with OnPush, signals, and dependency injection. Keep HTML and
SCSS separate. Use semantic classes; do not introduce style attributes or style
bindings. Follow [DESIGN.md](../DESIGN.md) for visual rules and the Strategy pattern.
Do not use raw HTML rendering or bypass Angular sanitization for user content.

## Verification

```sh
npm --prefix web run format:check
npm --prefix web run test:types
npm --prefix web run build
npm --prefix web test
```

Playwright runs the built application against an ephemeral Python/SQLite portal
on port 8007. It never starts a collector or contacts AWS/Google. Tests cover the
real signup/recovery/deletion session flow, mocked feature cases under the real
CSP, keyboard dialogs, mobile layout, axe checks, public HTML/SEO, and strict style
rules. Browser tests use installed Chrome by default; CI sets
`PLAYWRIGHT_CHROME_CHANNEL=chromium` after `npx playwright install --with-deps chromium`
inside `web/`. Reports and temporary credentials remain ignored.

Session cookies stay HttpOnly. CSRF tokens, invitations, API keys, and recovery
codes stay in memory. No browser storage holds credentials. A fresh response nonce
allows Angular component style elements while the CSP continues to reject inline
style attributes and arbitrary scripts. Fonts, icons, images, and scripts are
served locally. Native dialogs trap focus and restore it on close.
