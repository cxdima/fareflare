# Contributing to Fareflare

Start with the [local setup guide](docs/FAREFLARE.md). Use Python 3.12 and Node.js
24, install the locked dependencies, then run the application against local SQLite.
You do not need AWS credentials or a Google account to work on the UI or most
backend behavior.

## Choose a change

Search existing [issues](https://github.com/cxdima/fareflare/issues) before opening
one. A useful bug report includes the affected screen or endpoint, expected and
actual behavior, and steps to reproduce. Remove account details, tokens, full
reset links, backup codes, browser cookies, and private travel information from examples.

For changes to collection coverage, authentication, persistence, or the API
contract, explain the proposed behavior in an issue first. Small fixes and
clear documentation corrections can go directly to a pull request.

## Code organization and style

- Keep domain decisions in `src/fareflare/` independent of browser and cloud APIs.
  Adapters translate external data into validated contracts; API and MCP share
  application services.
- Use four-space Python indentation, type hints, `snake_case` functions, and
  `PascalCase` classes. Ruff checks import order, correctness and common security
  mistakes. A `# noqa` names its rule and says why.
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

`make check` runs Ruff (lint and formatting), compiles Python, runs Pyright, and
executes pytest with an 80% minimum coverage threshold for `fareflare`. `make format`
applies Ruff's fixes and formatting. Add behavioral tests for changed
rules, tenant isolation, retries, money handling, and failure paths. Backend tests
must not read real credentials or contact AWS or Google.

Code that reads text nobody on the project wrote (templates, pasted links, scraped
pages) also has generated tests in `tests/test_properties.py`. Cases vary locally
and are fixed in CI; `HYPOTHESIS_PROFILE=thorough make test` searches much harder.
When one fails, keep the reported input as an ordinary example test beside the fix.

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

Add a line to [CHANGELOG.md](CHANGELOG.md) for anything a user or operator would notice.

## Dependencies

Python dependencies are pinned in `requirements.txt` and `requirements-dev.txt` and
installed from hash-locked files. After changing a pin, regenerate both locks with
[uv](https://docs.astral.sh/uv/) and commit them together:

```bash
make lock
```

`make check` fails when a pin and its lock disagree. Dependabot can edit the pins
but not the locks, so a Python update from it needs `make lock` before it is merged.
Updates to `selenium`, `awslambdaric` and the container base images also need a
build and one live collection, because the test suite does not start a real browser
or Lambda runtime. After building the images as in
[operations](docs/OPERATIONS.md#release-api-and-worker-images):

```bash
docker run --rm --platform linux/arm64 -e AWS_LAMBDA_FUNCTION_NAME=local-verify \
  --entrypoint python fareflare-worker -m fareflare.cli quote "$(jq -r .url examples/demo.json)" \
  --chrome-binary /usr/bin/chromium --chromedriver /usr/bin/chromedriver
```

It prints `"ok": true` with a price read from the public page. The variable only
switches on the browser flags the worker uses in Lambda, which a container needs too.

Frontend dependencies use exact versions in `web/package.json` with
`web/package-lock.json`. GitHub Actions and container base images are pinned to
commit or image digests.

## Message wording

Text that people read in Telegram or the dashboard uses plain language: say what
happened and what, if anything, to do next. Failure codes and other technical
detail are shown only to accounts that turned on diagnostics. New details for
message templates are added to the vocabulary in `telegram_templates.py` and
produced in `telegram_messages.py`; templates never evaluate expressions.

By contributing, you agree that your changes are distributed under the repository's
[MIT license](LICENSE) and to follow the [code of conduct](CODE_OF_CONDUCT.md).
Be respectful, discuss the code rather than the person, and give reviewers enough
context to reproduce your result.
