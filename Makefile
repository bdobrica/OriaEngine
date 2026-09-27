UV ?= uv
COMPOSE = docker compose --env-file .env -p oria-local -f deploy/compose.yaml

.DEFAULT_GOAL := help

.PHONY: help bootstrap env api format lint typecheck test-unit test-integration verify clean infra-up infra-down infra-reset migrate migrate-down

help: ## Show available development commands
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Install locked runtime and development dependencies
	$(UV) sync --frozen --all-groups

env: ## Create .env from .env.example when absent
	@test -e .env || cp .env.example .env

api: ## Run the local HTTP gateway on http://127.0.0.1:8001
	$(UV) run python -m oria_engine

infra-up: env ## Start local PostgreSQL and Redis and wait for health checks
	$(COMPOSE) up -d --wait --wait-timeout 90

infra-down: env ## Stop local infrastructure, preserving PostgreSQL data
	$(COMPOSE) down

infra-reset: env ## Delete local PostgreSQL data and stop infrastructure (dev/test only)
	$(UV) run python -m oria_engine.db.local
	$(COMPOSE) down --volumes

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

verify: lint typecheck test-unit test-integration ## Run the required CI verification gate

clean: ## Remove generated caches, coverage, and build artifacts
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +
	rm -rf .coverage .coverage.* coverage.xml htmlcov build dist
