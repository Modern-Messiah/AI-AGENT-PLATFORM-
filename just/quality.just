# Quality gates mirroring CI: tests and linters.

# Run backend tests (pytest).
[group('quality')]
test:
    uv run python -m pytest -q

# Run frontend tests (node:test + vitest).
[group('quality')]
test-ui:
    npm --prefix apps/ui test

# Run live e2e smoke tests against an ALREADY RUNNING local stack.
[group('quality')]
test-e2e base='http://127.0.0.1:8000':
    RUN_E2E_SMOKE=1 E2E_API_BASE_URL={{ base }} uv run python -m pytest -q -m e2e tests/e2e

# Lint backend: ruff check + format check + mypy (blocking gates as in CI).
[group('quality')]
lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy .

# Lint frontend (eslint).
[group('quality')]
lint-ui:
    npm --prefix apps/ui run lint

# Auto-format backend code.
[group('quality')]
format:
    uv run ruff format .
    uv run ruff check --fix .
