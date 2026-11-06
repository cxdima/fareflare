.PHONY: help install build serve invite test lint check demo webhook-demo
.PHONY: next-install next-init next-serve next-demo next-mcp next-check
.PHONY: next-quote next-collect next-webhook-demo next-worker
.PHONY: product-build product-serve product-invite

PYTHON ?= .venv/bin/python

help:
	@echo "make install       Install locked Python development dependencies"
	@echo "make build         Install frontend dependencies and build the website"
	@echo "make serve         Serve the website, API, and MCP at http://127.0.0.1:8001"
	@echo "make invite        Write a local invitation to .next/invitation.json"
	@echo "make test          Run isolated Python tests without live services"
	@echo "make lint          Check Python source and test style with Ruff"
	@echo "make check         Compile, type-check, lint, and test with coverage"
	@echo "make demo          Replay synthetic prices without network access"
	@echo "make webhook-demo  Exercise signed webhook delivery locally"

install:
	@$(PYTHON) -m pip install --require-hashes -r requirements-next-dev.lock

build:
	@npm --prefix web ci
	@npm --prefix web run build

serve:
	@PYTHONPATH=src $(PYTHON) -m fareflare.product_cli serve

invite:
	@PYTHONPATH=src $(PYTHON) -m fareflare.product_cli invite .next/invitation.json

test:
	@$(PYTHON) -m pytest

lint:
	@$(PYTHON) -m ruff check src tests_next

check:
	@$(PYTHON) -m compileall -q src/fareflare
	@$(PYTHON) -m pyright
	@$(PYTHON) -m ruff check src tests_next
	@$(PYTHON) -m pytest --cov=fareflare --cov-report=term-missing

demo:
	@PYTHONPATH=src $(PYTHON) -m fareflare.cli demo

webhook-demo:
	@PYTHONPATH=src $(PYTHON) examples/webhook_demo.py

next-install: install
next-check: check
next-demo: demo
next-webhook-demo: webhook-demo
product-build: build
product-serve: serve
product-invite: invite

next-init:
	@PYTHONPATH=src $(PYTHON) -m fareflare.cli init

next-serve:
	@PYTHONPATH=src $(PYTHON) -m fareflare.cli serve

next-mcp:
	@PYTHONPATH=src $(PYTHON) -m fareflare.cli mcp

next-quote:
	@PYTHONPATH=src $(PYTHON) -m fareflare.cli quote

next-collect:
	@PYTHONPATH=src $(PYTHON) -m fareflare.cli collect-once

next-worker:
	@PYTHONPATH=src $(PYTHON) -m fareflare.cli worker
