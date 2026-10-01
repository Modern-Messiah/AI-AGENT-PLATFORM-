# Operational helpers: backup, database shells, container access, cleanup.

# Dump Postgres → MinIO (requires running services). See docs/runbooks/backup-restore.md.
[group('ops')]
backup:
    uv run python scripts/backup.py

# Interactive psql into the app database.
[group('ops')]
psql:
    docker compose exec postgres psql -U {{ env_var_or_default('POSTGRES_USER', 'postgres') }} -d {{ env_var_or_default('POSTGRES_DB', 'app') }}

# Interactive ClickHouse client.
[group('ops')]
ch:
    docker compose exec clickhouse clickhouse-client

# Shell into a running container: just sh api (default sh; use e.g. `just sh worker bash`).
[group('ops')]
sh service='api' cmd='sh':
    docker compose exec {{ service }} {{ cmd }}

# Remove caches (__pycache__, pytest, ruff, mypy).
[group('ops')]
clean:
    #!/usr/bin/env bash
    set -euo pipefail
    find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache -o -name .mypy_cache \) -prune -exec rm -rf {} +
    echo "✓ Caches removed"
