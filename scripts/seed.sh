#!/usr/bin/env bash
set -euo pipefail

# Pre-create the MinIO app bucket via mc. The app also creates the bucket
# lazily on first use (packages/storage/object_store.py), so failure here
# is non-fatal (|| true) — e.g. MinIO is not running yet.
echo "→ Creating MinIO bucket: ${MINIO_BUCKET:-app-files}"
docker run --rm --network host \
  -e MC_HOST_local="http://${MINIO_ROOT_USER:-minioadmin}:${MINIO_ROOT_PASSWORD:-minioadmin}@localhost:9002" \
  minio/mc:latest mb -p "local/${MINIO_BUCKET:-app-files}" || true

echo "→ Done"
