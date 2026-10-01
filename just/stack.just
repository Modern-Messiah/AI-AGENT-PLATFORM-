# Docker Compose stack: full app, infra-only, lifecycle, logs.

# Start the FULL stack: build images, then run infra + migrations + api + worker + ui.
[group('stack')]
up:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -f .env ]; then
        echo "✗ .env not found. Copy it first:  cp .env.example .env  (and fill the secrets)"
        exit 1
    fi
    docker compose up -d --build
    echo ""
    echo "✓ Stack is up:"
    echo "  UI            http://127.0.0.1:5173"
    echo "  API           http://127.0.0.1:{{ api_port }}"
    echo "  OpenAPI       http://127.0.0.1:{{ api_port }}/openapi.json"
    echo "  Temporal UI   http://127.0.0.1:8233"
    echo "  MinIO console http://127.0.0.1:9001"
    echo "  ClickHouse    http://127.0.0.1:8123"
    echo ""
    echo "  tenant API key:  just key demo local"
    echo "  logs:            just logs   (or just logs api / worker / ui …)"

# Start only infrastructure (postgres, redis, clickhouse, minio, temporal + UI).
[group('stack')]
infra:
    docker compose up -d postgres redis clickhouse minio temporal temporal-ui

# Stop all services, keep data.
[group('stack')]
down:
    docker compose down

# Restart all services, keep data.
[group('stack')]
restart:
    docker compose restart

# Stop services AND DELETE ALL DATA (volumes: Postgres, ClickHouse, MinIO, Redis).
[group('stack')]
reset:
    #!/usr/bin/env bash
    set -euo pipefail
    read -r -p "This deletes ALL local data (Postgres, ClickHouse, MinIO, Redis). Continue? [y/N] " confirm
    case "$confirm" in
        y|Y|yes|YES) docker compose down -v ;;
        *) echo "Aborted." ;;
    esac

# Tail logs from all services, or one: `just logs api`.
[group('stack')]
logs service='':
    docker compose logs -f --tail=100 {{ service }}

# Show service status.
[group('stack')]
ps:
    docker compose ps

# Build (or rebuild) all app images without starting anything.
[group('stack')]
build:
    docker compose build

# Start the optional Caddy TLS termination profile (LAN/HTTPS).
[group('stack')]
tls:
    docker compose --profile tls up -d

# Validate compose configs (same gates as CI).
[group('stack')]
validate:
    docker compose config --quiet
    docker compose --profile tls config --quiet
    docker compose --profile observability config --quiet
