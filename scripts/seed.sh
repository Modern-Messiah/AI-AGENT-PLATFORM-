#!/usr/bin/env bash
set -euo pipefail

# Wait for MinIO and create the app bucket via mc.
echo "→ Creating MinIO bucket: ${MINIO_BUCKET:-app-files}"
docker run --rm --network host \
  -e MC_HOST_local="http://${MINIO_ROOT_USER:-minioadmin}:${MINIO_ROOT_PASSWORD:-minioadmin}@localhost:9002" \
  minio/mc:latest mb -p "local/${MINIO_BUCKET:-app-files}" || true

docker run --rm --network host \
  -e MC_HOST_local="http://${MINIO_ROOT_USER:-minioadmin}:${MINIO_ROOT_PASSWORD:-minioadmin}@localhost:9002" \
  minio/mc:latest mb -p "local/langfuse" || true

echo "→ Done"
