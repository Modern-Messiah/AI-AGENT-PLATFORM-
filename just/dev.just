# Local development: host-run api/worker/ui against compose infrastructure.

# Install Python deps (uv sync) and frontend deps (npm ci).
[group('dev')]
install:
    uv sync
    npm --prefix apps/ui ci

# Ready infra for local dev: start infra services and run migrations.
[group('dev')]
dev-infra: infra migrate

# Run the FastAPI dev server with autoreload on :8000.
[group('dev')]
dev-api:
    uv run uvicorn apps.api.main:app --reload --port {{ api_port }}

# Run the Temporal worker on the host.
[group('dev')]
dev-worker:
    uv run python -m apps.worker.main

# Run the Vite dev server for the UI.
[group('dev')]
dev-ui:
    npm --prefix apps/ui run dev
