.PHONY: help test lint deploy run-local logs
.PHONY: next-install next-init next-serve next-demo next-mcp next-check
.PHONY: next-quote next-collect
.PHONY: next-webhook-demo

PYTHON ?= .venv/bin/python

help:
	@echo "make test       Run unit tests (no browser, no AWS)"
	@echo "make lint       Ruff lint over src/ and tests/"
	@echo "make deploy     Build, push, and deploy to AWS Lambda"
	@echo "make run-local  Full pipeline against live Chrome (visible window)"
	@echo "make logs       Tail the Lambda's CloudWatch logs"

test:
	@$(PYTHON) -m pytest

lint:
	@$(PYTHON) -m ruff check src tests

deploy:
	@bash scripts/deploy.sh

run-local:
	@$(PYTHON) scripts/run_local.py

logs:
	@aws logs tail /aws/lambda/$${PROJECT_NAME:-gfpricetracker} --follow --region $${AWS_REGION:-us-east-1}

next-install:
	@$(PYTHON) -m pip install --require-hashes -r requirements-next-dev.lock

next-init:
	@PYTHONPATH=src $(PYTHON) -m gfpt_next.cli init

next-serve:
	@PYTHONPATH=src $(PYTHON) -m gfpt_next.cli serve

next-demo:
	@PYTHONPATH=src $(PYTHON) -m gfpt_next.cli demo

next-webhook-demo:
	@PYTHONPATH=src $(PYTHON) examples/webhook_demo.py

next-mcp:
	@PYTHONPATH=src $(PYTHON) -m gfpt_next.cli mcp

next-quote:
	@PYTHONPATH=src $(PYTHON) -m gfpt_next.cli quote

next-collect:
	@PYTHONPATH=src $(PYTHON) -m gfpt_next.cli collect-once

next-check:
	@$(PYTHON) -m compileall -q src/gfpt_next
	@$(PYTHON) -m pyright
	@$(PYTHON) -m ruff check src tests tests_next
	@$(PYTHON) -m pytest --cov=gfpt_next --cov-report=term-missing

.PHONY: next-worker
next-worker:
	@PYTHONPATH=src $(PYTHON) -m gfpt_next.cli worker

.PHONY: product-build product-serve product-invite
product-build:
	@npm --prefix web ci
	@npm --prefix web run build

product-serve:
	@PYTHONPATH=src $(PYTHON) -m gfpt_next.product_cli serve

product-invite:
	@PYTHONPATH=src $(PYTHON) -m gfpt_next.product_cli invite .next/invitation.json
