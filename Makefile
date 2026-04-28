.PHONY: help up down logs ps restart seed migrate api worker test lint format clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

up: ## Start all infra services
	docker compose up -d
	@echo "→ Postgres:    localhost:5432"
	@echo "→ Redis:       localhost:6379"
	@echo "→ ClickHouse:  localhost:8123"
	@echo "→ MinIO:       localhost:9002 (console: http://localhost:9001)"
	@echo "→ Temporal:    localhost:7233 (UI: http://localhost:8233)"
	@echo "→ Langfuse:    http://localhost:3000"
	@echo "→ Bifrost:     http://localhost:8088"

down: ## Stop all services
	docker compose down

down-volumes: ## Stop services AND drop all data (destructive)
	docker compose down -v

logs: ## Tail logs from all services
	docker compose logs -f --tail=100

ps: ## Show service status
	docker compose ps

restart: down up ## Restart all services

seed: ## Create MinIO buckets and any seed data
	bash scripts/seed.sh

migrate: ## Run alembic migrations against app database
	uv run alembic upgrade head

api: ## Run FastAPI dev server
	uv run uvicorn apps.api.main:app --reload --port 8000

worker: ## Run Temporal worker
	uv run python -m apps.worker.main

test: ## Run tests
	uv run pytest

lint: ## Lint code
	uv run ruff check .
	uv run mypy .

format: ## Format code
	uv run ruff format .
	uv run ruff check --fix .

backup: ## Dump Postgres → MinIO (requires running services)
	uv run python scripts/backup.py

clean: ## Remove caches
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
