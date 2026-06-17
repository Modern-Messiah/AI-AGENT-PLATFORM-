# Backup and Restore Runbook

This runbook describes how to back up and restore a private/self-hosted AI Agent
Platform deployment.

It is intentionally conservative. A backup that was never restored is only a guess,
so treat the restore drill as part of the backup process.

## Scope

The minimum recoverable system needs:

| Component | Required for restore? | What it contains |
|---|---:|---|
| `.env` and secrets | Yes | Provider keys, DB passwords, MinIO password, Langfuse encryption key, admin secret |
| Postgres | Yes | App data, API keys, documents metadata, chunks, vectors, sessions, notebooks, Temporal DBs, Langfuse DB |
| MinIO | Yes | Original uploaded files, generated previews/assets, Langfuse object data |
| Git commit / source tree | Yes | The code and migrations that match the data |
| ClickHouse | Optional but useful | Usage analytics and Langfuse event data |
| Redis | Optional | Semantic cache and transient local state; can usually be rebuilt |

The existing `make backup` target runs `scripts/backup.py`. That script only dumps the
application Postgres database to MinIO. It does not back up MinIO itself, `.env`,
Temporal databases, Langfuse database, ClickHouse, or Redis. Use the full procedure
below for real disaster recovery.

## Backup Storage Rules

Do not store backups only inside the same Docker host. If the machine or Docker volume
is lost, local-only backups are lost too.

Recommended pattern:

1. Create a timestamped backup directory locally.
2. Put Postgres dump, MinIO mirror, `.env`, and metadata in that directory.
3. Copy the directory to an external disk, NAS, encrypted cloud storage, or another
   machine.
4. Encrypt or access-control the backup. It contains API keys and user documents.

Example backup directory:

```bash
BACKUP_ROOT="$HOME/aap-backups"
BACKUP_ID="$(date -u +%Y%m%d_%H%M%S)"
BACKUP_DIR="$BACKUP_ROOT/$BACKUP_ID"
mkdir -p "$BACKUP_DIR"/{postgres,minio,secrets,metadata}
```

Load `.env` into the shell for the commands below:

```bash
set -a
. ./.env
set +a
```

## Pre-Backup Checks

Run these from the project root:

```bash
docker compose ps
docker compose config --quiet
curl -fsS http://127.0.0.1:8000/health
```

Expected result:

- Compose config exits with code `0`.
- API health returns `{"status":"ok"}`.
- `postgres` and `minio` are running and healthy/up.

If ingestion is actively running, either wait for it to finish or accept that the
backup may contain a document in `pending` or `processing` state.

## Back Up Secrets and Deployment Metadata

Copy the exact `.env` used by the deployment:

```bash
cp .env "$BACKUP_DIR/secrets/.env"
chmod 600 "$BACKUP_DIR/secrets/.env"
```

Record the current Git commit and resolved Compose config:

```bash
git rev-parse HEAD > "$BACKUP_DIR/metadata/git-commit.txt"
docker compose config > "$BACKUP_DIR/metadata/docker-compose.resolved.yml"
```

The resolved Compose file may contain secrets. Store it with the same care as `.env`.

At minimum, protect these values:

- `POSTGRES_PASSWORD`
- `APP_DB_PASSWORD`
- `CLICKHOUSE_PASSWORD`
- `MINIO_ROOT_PASSWORD`
- `LANGFUSE_NEXTAUTH_SECRET`
- `LANGFUSE_SALT`
- `LANGFUSE_ENCRYPTION_KEY`
- `MOONSHOT_API_KEY`
- `DEEPSEEK_API_KEY`
- `ADMIN_SECRET`

## Back Up Postgres

For full self-host restore, prefer `pg_dumpall`, because this Compose stack stores more
than the application DB in Postgres: app DB, Temporal DBs, Temporal visibility DB, and
Langfuse DB.

```bash
docker compose exec -T postgres pg_dumpall \
  -U "${POSTGRES_USER:-postgres}" \
  --clean \
  --if-exists \
  | gzip -6 > "$BACKUP_DIR/postgres/postgres-all.sql.gz"
```

Also create an application-only dump for fast inspection or partial recovery:

```bash
docker compose exec -T postgres pg_dump \
  -U "${POSTGRES_USER:-postgres}" \
  --clean \
  --if-exists \
  app \
  | gzip -6 > "$BACKUP_DIR/postgres/app.sql.gz"
```

Validate dump files:

```bash
gzip -t "$BACKUP_DIR/postgres/postgres-all.sql.gz"
gzip -t "$BACKUP_DIR/postgres/app.sql.gz"
ls -lh "$BACKUP_DIR/postgres"
```

## Back Up MinIO

MinIO stores the original uploaded files and generated assets. The database is not
enough without this data: document rows and chunks may remain, but original files,
reindexing, and protected previews will be broken.

Use the official MinIO client container and connect through the running MinIO
container network namespace:

```bash
docker run --rm \
  --network container:aap-minio \
  -e MINIO_ROOT_USER="$MINIO_ROOT_USER" \
  -e MINIO_ROOT_PASSWORD="$MINIO_ROOT_PASSWORD" \
  -v "$BACKUP_DIR/minio:/backup" \
  minio/mc sh -c '
    set -eu
    mc alias set local http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
    mc mirror --overwrite local/app-files /backup/app-files
    mc mirror --overwrite local/langfuse /backup/langfuse || true
  '
```

Validate the mirror:

```bash
find "$BACKUP_DIR/minio" -type f | wc -l
du -sh "$BACKUP_DIR/minio"
```

For an empty development system, the file count may be small. For a real system with
documents, a zero-file `app-files` mirror is suspicious and should be investigated.

## Optional: Back Up ClickHouse

ClickHouse stores usage analytics and some Langfuse data. Losing it should not destroy
documents or chat history, but it does remove historical usage/trace analytics.

For small local deployments, a SQL dump is usually enough:

```bash
docker compose exec -T clickhouse clickhouse-client \
  --user "${CLICKHOUSE_USER:-default}" \
  --password "$CLICKHOUSE_PASSWORD" \
  --query "SHOW DATABASES" \
  > "$BACKUP_DIR/metadata/clickhouse-databases.txt"
```

If ClickHouse analytics become important, add a dedicated ClickHouse backup process
before relying on this for production recovery.

## Optional: Redis

Redis currently holds semantic cache and transient state. It is normally safe to lose:
the system will recompute cache entries. Do not block disaster recovery on Redis unless
you intentionally add durable data there later.

If you still want a copy of the Redis AOF volume, back up the Docker volume or use a
filesystem snapshot while Redis is stopped.

## Package and Move the Backup

Create a checksum manifest:

```bash
find "$BACKUP_DIR" -type f -print0 \
  | sort -z \
  | xargs -0 shasum -a 256 \
  > "$BACKUP_DIR/metadata/SHA256SUMS"
```

Archive the directory:

```bash
tar -C "$BACKUP_ROOT" -czf "$BACKUP_ROOT/aap-$BACKUP_ID.tar.gz" "$BACKUP_ID"
```

Move `aap-$BACKUP_ID.tar.gz` to external storage.

## Restore Overview

Restore into a clean environment whenever possible. Restoring over existing volumes can
mix old and restored state.

The safe order is:

1. Check out the same Git commit.
2. Restore `.env`.
3. Start only Postgres and MinIO.
4. Restore Postgres.
5. Restore MinIO buckets.
6. Start the full stack.
7. Run verification checks.

## Restore: Prepare Clean Environment

Clone or open the project:

```bash
cd /path/to/ai-agent-platform
```

Restore `.env`:

```bash
cp "$BACKUP_DIR/secrets/.env" .env
chmod 600 .env
set -a
. ./.env
set +a
```

Check out the recorded commit if available:

```bash
git checkout "$(cat "$BACKUP_DIR/metadata/git-commit.txt")"
```

For a disposable restore drill, start from empty volumes:

```bash
docker compose down -v
```

This command deletes local Docker volumes. Use it only in a test restore directory or
when you intentionally want to replace the current deployment.

## Restore Postgres

Start Postgres:

```bash
docker compose up -d postgres
```

Wait until it is healthy:

```bash
docker compose ps postgres
```

Restore the full dump. The recommended dump uses `--clean --if-exists`, so it can
replace the databases created by `infra/postgres/init.sql` during first container
startup:

```bash
gunzip -c "$BACKUP_DIR/postgres/postgres-all.sql.gz" \
  | docker compose exec -T postgres psql \
      -U "${POSTGRES_USER:-postgres}" \
      -d postgres
```

If you only need the application database and already have roles/databases created,
restore `app.sql.gz` instead. Full disaster recovery should use `postgres-all.sql.gz`.

If you are restoring an older dump that was created without `--clean --if-exists`, use
a clean Postgres volume or manually drop the existing `app`, `temporal`,
`temporal_visibility`, and `langfuse` databases before replaying it.

## Restore MinIO

Start MinIO:

```bash
docker compose up -d minio
```

Restore buckets:

```bash
docker run --rm \
  --network container:aap-minio \
  -e MINIO_ROOT_USER="$MINIO_ROOT_USER" \
  -e MINIO_ROOT_PASSWORD="$MINIO_ROOT_PASSWORD" \
  -v "$BACKUP_DIR/minio:/backup" \
  minio/mc sh -c '
    set -eu
    mc alias set local http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
    mc mb --ignore-existing local/app-files
    mc mirror --overwrite /backup/app-files local/app-files
    if [ -d /backup/langfuse ]; then
      mc mb --ignore-existing local/langfuse
      mc mirror --overwrite /backup/langfuse local/langfuse
    fi
  '
```

## Start the Full Stack

```bash
docker compose up -d --build
```

The `migrate` service should be idempotent. If the restored database already contains
the current schema, Alembic should report no pending destructive work.

## Restore Verification

Run:

```bash
docker compose ps
curl -fsS http://127.0.0.1:8000/health
```

Check database counts:

```bash
docker compose exec -T postgres psql \
  -U "${POSTGRES_USER:-postgres}" \
  -d app \
  -c "select count(*) as documents from documents;" \
  -c "select count(*) as chunks from chunks;" \
  -c "select count(*) as sessions from chat_sessions;" \
  -c "select count(*) as notebooks from notebooks;"
```

Check MinIO restored objects:

```bash
docker run --rm \
  --network container:aap-minio \
  -e MINIO_ROOT_USER="$MINIO_ROOT_USER" \
  -e MINIO_ROOT_PASSWORD="$MINIO_ROOT_PASSWORD" \
  minio/mc sh -c '
    mc alias set local http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
    mc ls --recursive local/app-files | head -50
  '
```

Then verify from the UI:

1. Open `http://127.0.0.1:5173`.
2. Use an existing tenant API key from the restored database, or create a new one with
   `POST /auth/keys`.
3. Confirm documents are listed.
4. Open a restored document detail page.
5. Ask a question about a restored document.
6. Confirm the answer cites the restored source.
7. Reindex one non-critical document to confirm original MinIO objects are present.

## Restore Drill Schedule

For a private deployment, run this drill at least monthly or before any major upgrade:

1. Create a fresh backup.
2. Restore it in a separate directory or disposable machine.
3. Run the verification checks above.
4. Record the backup ID, source commit, restore duration, and any manual fixes needed.

If a restore drill fails, treat that as a production bug. A backup procedure is not
complete until restore works.

## Known Gaps

- `scripts/backup.py` backs up only the `app` Postgres database into MinIO. It is useful
  as a quick app DB snapshot, but it is not a full disaster recovery backup.
- There is no automated restore script yet. This is deliberate: restore commands can
  delete volumes, so they should become automated only after at least one manual drill
  proves the exact procedure.
- ClickHouse and Redis are not part of the minimum restore path. Add dedicated backups
  if analytics or Redis state becomes business-critical.
