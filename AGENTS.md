# Repository Guidelines

Guidance for coding agents and new contributors. [CONTRIBUTING.md](CONTRIBUTING.md)
covers the contribution process; this file is the short technical map.

## Project structure

| Path | Contents |
| --- | --- |
| `src/fareflare/` | Python application: domain rules, services, API/MCP, collectors, persistence, delivery |
| `tests/` | Pytest suite with SQLite and Moto DynamoDB; fixtures in `tests/fixtures/` |
| `web/` | Angular dashboard and public site, with Playwright tests in `web/tests/` |
| `infra/` | Terraform for the API and worker Lambdas, DynamoDB, scheduling and alarms |
| `scripts/` | Operator tools for Telegram webhook routing and bot profile |
| `examples/` | Synthetic demos and a signed-webhook receiver |
| `docs/` | Setup, architecture, operations and verification records |

Key modules: `service.py` (monitoring use cases), `store.py` (SQLite/DynamoDB
documents), `public_browser.py` and `public_quotes.py` (collection and quote
validation), `outbox.py` (ordered delivery), `telegram_bot.py` (chat controls),
`message_templates.py` and `telegram_templates.py` (message styles), `portal.py`
(the account application). See [docs/ARCHITECTURE_REVIEW.md](docs/ARCHITECTURE_REVIEW.md).

## Build, test and development commands

```bash
python3.12 -m venv .venv
make install          # locked Python dependencies
make build            # install and build the dashboard
make serve            # website, API and MCP at http://127.0.0.1:8001
make check            # Ruff lint + format check, compile, Pyright, pytest with coverage
make format           # apply Ruff fixes and formatting
npm --prefix web run format:check && npm --prefix web run test:types
npm --prefix web test # Playwright against the built dashboard and a temporary database
```

Run one module with `.venv/bin/python -m pytest tests/test_service.py`. No AWS
account, Google account or network access is needed for any of these.

## Coding style and naming

- Python 3.12, four-space indentation, type hints, `snake_case` functions and
  `PascalCase` classes. Ruff formats and lints at 100 columns; Pyright must stay clean.
- Angular standalone components with OnPush, signals and typed services. Templates
  and SCSS live in separate files. Prettier formats the frontend.
- Money is an integer in minor units with an explicit currency. Never use floats.
- Keep provider parsing, persistence and transports out of pure policy code.
  Dependencies are wired at CLI or Lambda startup.

## Testing guidelines

Name files `test_*.py` and functions `test_*`, describing behavior. Reuse the
`store`, `service`, `clock` and `flight_url` fixtures; most tests run against both
stores. Tests have a 60-second timeout and must not read real credentials or
contact AWS, Google or Telegram. Coverage must stay at or above 80%. Cover tenant
isolation, retries, money handling and failure paths for any changed rule.

## Commits and pull requests

Use `feat:`, `fix:`, `docs:`, `refactor:` or `chore:` subjects. A pull request
explains the problem, the resulting behavior and how it was validated, and notes
any configuration or data-format change. Add an entry to [CHANGELOG.md](CHANGELOG.md).

## Security and privacy

- Never commit credentials, invitations, cookies, Terraform state or variable
  files. Local operator state belongs in the ignored `.fareflare/` directory.
- Never log or persist provider exception text; use the finite failure codes in
  `contracts.py`. Messages shown to people use plain language, and technical codes
  appear only for accounts that enabled diagnostics.
- Account-authored message templates are data, not code. Extend the placeholder
  vocabulary in `telegram_templates.py`; do not introduce an expression-evaluating
  template engine.
- Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
