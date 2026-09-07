UV ?= uv

.DEFAULT_GOAL := help

.PHONY: help bootstrap env format lint typecheck test-unit verify clean

help: ## Show available development commands
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Install locked runtime and development dependencies
	$(UV) sync --frozen --all-groups

env: ## Create .env from .env.example when absent
	@test -e .env || cp .env.example .env

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

verify: lint typecheck test-unit ## Run the required CI verification gate

clean: ## Remove generated caches, coverage, and build artifacts
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +
	rm -rf .coverage .coverage.* coverage.xml htmlcov build dist
