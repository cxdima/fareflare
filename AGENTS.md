# Repository Guidelines

## Project Structure & Module Organization

`src/gfpt/` contains the Python application: `handler.py` routes Lambda events, `config.py` loads settings, and `models.py` defines shared dataclasses. Keep browser capture and price processing in `tracking/`, S3 and DynamoDB persistence in `storage/`, and Telegram commands and notifications in `bot/`.

`tests/` mirrors application modules, with shared fixtures in `conftest.py`. `infra/` holds Terraform; `scripts/` holds deployment, local integration, and environment restoration tools. The root `Dockerfile` packages Chromium and the application for ARM64 Lambda.

## Build, Test, and Development Commands

Set up Python 3.11+ and dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

- `make test`: run isolated unit tests without AWS or a browser.
- `make lint`: run Ruff checks on `src/` and `tests/`.
- `.venv/bin/python -m pytest tests/test_handler.py`: run a focused test module.
- `make run-local`: run the staged integration harness with visible Chrome; requires configured credentials and live services.
- `docker buildx build --platform linux/arm64 --load -t gfpt:local .`: build the container locally.
- `make deploy`: build and push the image, apply AWS infrastructure, register the Telegram webhook, and invoke a live smoke test.
- `make logs`: tail Lambda CloudWatch logs.

## Coding Style & Naming Conventions

Use four-space indentation, `snake_case` for modules and functions, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Follow existing type hints and frozen dataclasses for shared models. Keep environment parsing centralized in `config.py`.

Ruff targets Python 3.11 with a configured 100-character line length; E501 is disabled. Follow its import-order, correctness, and modernization checks.

## Testing Guidelines

Use pytest, `test_*.py` files, and descriptive `test_*` functions. Reuse fake stores, `monkeypatch`, and mocks from `tests/conftest.py`; unit tests must not load real `.env` credentials or contact external services. Tests have a 60-second timeout. No numeric coverage threshold is configured. Cover changed behavior and failure paths, especially event routing, price parsing, and flight reconciliation.

## Commit & Pull Request Guidelines

Follow recent commit prefixes: `feat:`, `fix:`, and `chore:`. Write concise, specific summaries. PRs should explain the problem, resulting behavior, validation performed, and configuration or infrastructure changes; link related issues. Run `make test` and `make lint` before submitting code changes.

## Security & Configuration

Create local configuration from `.env.example`. Never commit credentials, session cookies, or Terraform state; state contains Lambda secrets. Preserve webhook authentication and the separation between Telegram requests and tracker execution.
