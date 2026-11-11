.PHONY: help install lock build serve worker mcp test lint format check demo webhook-demo

PYTHON ?= .venv/bin/python
PYTHON_SOURCES = src tests scripts examples web/tests/serve_portal.py

help:
	@echo "make install       Install locked Python development dependencies"
	@echo "make lock          Regenerate the hash-locked requirement files (needs uv)"
	@echo "make build         Install frontend dependencies and build the website"
	@echo "make serve         Serve the website, API, and MCP at http://localhost:8001"
	@echo "make worker        Collect due monitors once and deliver queued alerts"
	@echo "make mcp           Run the stdio MCP adapter (needs FAREFLARE_API_KEY)"
	@echo "make test          Run isolated Python tests without live services"
	@echo "make lint          Check Python style and formatting with Ruff"
	@echo "make format        Format Python sources with Ruff"
	@echo "make check         Compile, type-check, lint, and test with coverage"
	@echo "make demo          Replay synthetic prices without network access"
	@echo "make webhook-demo  Exercise signed webhook delivery locally"

install:
	@$(PYTHON) -m pip install --require-hashes -r requirements-dev.lock

lock:
	@uv pip compile requirements.txt --python $(PYTHON) --generate-hashes --quiet \
		--output-file requirements.lock
	@uv pip compile requirements-dev.txt --python $(PYTHON) --generate-hashes --quiet \
		--output-file requirements-dev.lock

build:
	@npm --prefix web ci
	@npm --prefix web run build

serve:
	@PYTHONPATH=src $(PYTHON) -m fareflare.product_cli serve

worker:
	@PYTHONPATH=src $(PYTHON) -m fareflare.product_cli worker --limit 5

mcp:
	@PYTHONPATH=src $(PYTHON) -m fareflare.cli mcp

test:
	@$(PYTHON) -m pytest

lint:
	@$(PYTHON) scripts/check_locks.py
	@$(PYTHON) -m ruff check $(PYTHON_SOURCES)
	@$(PYTHON) -m ruff format --check $(PYTHON_SOURCES)

format:
	@$(PYTHON) -m ruff check --fix $(PYTHON_SOURCES)
	@$(PYTHON) -m ruff format $(PYTHON_SOURCES)

check: lint
	@$(PYTHON) -m compileall -q src/fareflare
	@$(PYTHON) -m pyright
	@$(PYTHON) -m pytest --cov=fareflare --cov-report=term-missing

demo:
	@PYTHONPATH=src $(PYTHON) -m fareflare.cli demo

webhook-demo:
	@PYTHONPATH=src $(PYTHON) examples/webhook_demo.py
