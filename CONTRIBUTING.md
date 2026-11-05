# Contributing to Fareflare

Start with the [local setup guide](docs/FAREFLARE.md). Use Python 3.12 and Node.js
24, install the locked dependencies, then run the application against local SQLite.
You do not need AWS credentials or a Google account to work on the UI or most
backend behavior.

## Choose a change

Search existing [issues](https://github.com/cxdima/fareflare/issues) before opening
one. A useful bug report includes the affected screen or endpoint, expected and
actual behavior, and steps to reproduce. Remove account details, tokens, full
invitation URLs, browser cookies, and private travel information from examples.

For changes to collection coverage, authentication, persistence, or the API
contract, explain the proposed behavior in an issue first. Small fixes and
clear documentation corrections can go directly to a pull request.

## Code organization and style

- Keep domain decisions in `src/gfpt_next/` independent of browser and cloud APIs.
  Adapters translate external data into validated contracts; API and MCP share
  application services.
- Use four-space Python indentation, type hints, `snake_case` functions, and
  `PascalCase` classes. Ruff checks import order and correctness.
- Use Angular standalone component classes, OnPush, signals, and typed services.
  Keep templates and SCSS in separate files. Use semantic CSS classes and theme
  tokens; avoid inline styles and direct HTML injection.
- Keep prices in integer minor units with an explicit currency. An observation
  must preserve itinerary, passenger, fare, and collection-time context.
- Follow [DESIGN.md](DESIGN.md) for interface decisions and
  [architecture notes](docs/ARCHITECTURE_REVIEW.md) for boundaries and patterns.

## Validate your work

```bash
make check
npm --prefix web run format:check
npm --prefix web run build
npm --prefix web test
```

`make check` compiles Python, runs Pyright and Ruff, and executes pytest with
an 80% minimum coverage threshold for `gfpt_next`. Add behavioral tests for changed
rules, tenant isolation, retries, money handling, and failure paths. Backend tests
must not read real credentials or contact AWS or Google.

Playwright runs the built portal with a temporary SQLite database. For Chromium:

```bash
cd web
npx playwright install chromium
PLAYWRIGHT_CHROME_CHANNEL=chromium npm test
```

UI changes should include desktop and narrow-screen checks, keyboard navigation,
loading/error/empty states, and screenshots using synthetic data. A new collector
capability requires a redacted fixture and validation of the actual itinerary,
passenger context, currency, and eligible fare.

## Pull requests

Fork the repository and create a focused branch. Use concise commit subjects with
`feat:`, `fix:`, `docs:`, `refactor:`, or `chore:` as appropriate. Explain the problem,
resulting behavior, and validation in the pull request; link relevant issues and
include screenshots for visible changes. Describe configuration or data-migration
requirements explicitly. Do not commit generated builds, local databases, secrets,
Terraform state, or private test artifacts.

By contributing, you agree that your changes are distributed under the repository's
[MIT license](LICENSE). Be respectful, discuss the code rather than the person,
and give reviewers enough context to reproduce your result.
