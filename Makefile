UV ?= uv
COMPOSE = docker compose --env-file .env -p oria-local -f deploy/compose.yaml
DEV_COMPOSE = $(COMPOSE) -f deploy/compose.dev.yaml --profile dev --profile astrology

.DEFAULT_GOAL := help

.PHONY: dev down

.PHONY: worker help bootstrap env api run format lint typecheck test-unit test-integration test-e2e test verify clean infra-up infra-down infra-reset migrate migrate-down mcp mcp-local mcp-test test-contract webhook-set webhook-delete webhook-reset logs metrics

help: ## Show available development commands
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Install locked runtime and development dependencies
	$(UV) sync --frozen --all-groups

env: ## Create .env from .env.example when absent
	@test -e .env || cp .env.example .env

api: ## Run the local HTTP gateway on http://127.0.0.1:8001
	$(UV) run python -m oria_engine

worker: ## Run Redis workers and durable event recovery
	$(UV) run python -m oria_engine.queue

dev: env ## Build, migrate and start the complete local application stack
	$(DEV_COMPOSE) up --build -d --wait --wait-timeout 120

down: env ## Stop the complete local stack, preserving PostgreSQL data
	$(DEV_COMPOSE) -f deploy/compose.polling.yaml down --remove-orphans

logs: env ## Follow local infrastructure, gateway, worker and migration logs
	$(DEV_COMPOSE) logs --follow --tail 100

metrics: ## Print a private aggregate queue/consent/onboarding/deletion snapshot
	@$(UV) run python -m oria_engine.operations

run: ## Run the development Telegram bot using long polling
	$(UV) run python -m oria_engine.telegram

webhook-set: ## Register the configured HTTPS webhook, preserving pending updates
	$(UV) run python -m oria_engine.telegram.webhook_admin set

webhook-delete: ## Remove the webhook, preserving pending updates
	$(UV) run python -m oria_engine.telegram.webhook_admin delete

webhook-reset: ## Reapply the configured webhook URL/secret/update types
	$(UV) run python -m oria_engine.telegram.webhook_admin reset

mcp: env ## Build and run the astrology MCP container on its private network
	$(COMPOSE) --profile astrology up --build -d --wait astrology-mcp

mcp-local: env ## Start MCP with loopback access for host-run Telegram polling
	$(COMPOSE) -f deploy/compose.polling.yaml --profile astrology up --build -d --wait astrology-mcp

mcp-test: ## Build and smoke-test an isolated astrology MCP container
	$(UV) run pytest tests/contract/test_astrology_container.py

test-contract: ## Verify astrology and SecondContext contracts, MCP transport and container
	$(UV) run pytest tests/contract

infra-up: env ## Start local PostgreSQL and Redis and wait for health checks
	$(COMPOSE) up -d --wait --wait-timeout 90

infra-down: env ## Stop local infrastructure, preserving PostgreSQL data
	$(DEV_COMPOSE) -f deploy/compose.polling.yaml down --remove-orphans

infra-reset: env ## Delete local PostgreSQL data and stop infrastructure (dev/test only)
	$(UV) run python -m oria_engine.db.local
	$(DEV_COMPOSE) -f deploy/compose.polling.yaml down --remove-orphans --volumes

migrate: ## Apply all pending database migrations
	$(UV) run alembic upgrade head

migrate-down: ## Roll back one database revision (dev/test only)
	$(UV) run python -m oria_engine.db.local
	$(UV) run alembic downgrade -1

format: ## Format Python source and tests
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

lint: ## Check formatting and lint rules
	$(UV) run ruff format --check .
	$(UV) run ruff check .

typecheck: ## Run strict static type checking
	$(UV) run mypy

test-unit: ## Run the fast unit-test suite
	$(UV) run pytest tests/unit

test-integration: ## Test migrations and transactions using isolated Docker services
	$(UV) run pytest tests/integration

test-e2e: ## Replay Telegram conversations using isolated services and local HTTP fakes
	$(UV) run pytest tests/e2e

test: test-unit test-integration test-contract test-e2e ## Run all automated test lanes

verify: lint typecheck test ## Run the required CI verification gate

clean: ## Remove generated caches, coverage, and build artifacts
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +
	rm -rf .coverage .coverage.* coverage.xml htmlcov build dist
