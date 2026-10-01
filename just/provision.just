# Provisioning: migrations, MinIO bucket, tenant API keys.

# Run Alembic migrations against the local database. Uses the postgres
# superuser like the compose `migrate` service: the runtime role (aap_app)
# has no grants on alembic_version.
[group('provision')]
migrate:
    #!/usr/bin/env bash
    set -euo pipefail
    DATABASE_URL="postgresql+asyncpg://postgres:${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}@localhost:5432/${POSTGRES_DB:-app}" \
      uv run alembic upgrade head

# Pre-create the MinIO app bucket (the app also creates it lazily on first use).
[group('provision')]
seed:
    bash scripts/seed.sh

# Create a tenant API key via the running API. Usage: just key demo local
[group('provision')]
key tenant='demo' name='local':
    #!/usr/bin/env bash
    set -euo pipefail
    curl -fsS -X POST "http://127.0.0.1:{{ api_port }}/auth/keys" \
      -H 'Content-Type: application/json' \
      -H "X-Admin-Secret: ${ADMIN_SECRET:?Set ADMIN_SECRET in .env}" \
      -d '{"tenant_id":"{{ tenant }}","name":"{{ name }}"}'
