# Reindex after an embedding model change

Runbook for switching `EMBEDDING_MODEL` (e.g. from the old English-only
`BAAI/bge-small-en-v1.5` to the default multilingual
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, or upgrading to
`intfloat/multilingual-e5-large`).

## Why

All chunk vectors live in one pgvector column. Vectors from different models
are incomparable **even when the dimensions match**, so after changing
`EMBEDDING_MODEL` every document must be re-embedded. Mixing old and new
vectors silently degrades retrieval for both.

## Case A: same dimension (384 → 384, e.g. bge-small → MiniLM multilingual)

No schema change; just clear the stale vectors and reindex.

1. Back up PostgreSQL app data: `make backup`.

2. Set the env in `.env` (both `api` and `worker` see these via compose):

   ```env
   EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
   EMBEDDING_DIM=384
   ```

3. Restart and clear stale chunks:

   ```bash
   docker compose up -d --build api worker
   docker compose exec postgres psql -U "$POSTGRES_USER" -d app -c "DELETE FROM chunks"
   ```

   Documents keep status `done`, but retrieval answers "no relevant
   information" until step 4 finishes.

4. Reindex every document — per document in the UI (Documents → reindex) or
   all at once:

   ```bash
   uv run python scripts/reindex_all.py --api-base http://localhost:8000 --api-key <key>
   ```

   The script runs one ingestion workflow at a time (OCR/Vision are
   CPU-heavy) and waits for `done` before the next document.

5. Verify with a Russian question that previously failed to retrieve, or run:

   ```bash
   PYTHONPATH=$PWD uv run python -m evals.runners.retrieval_eval --tenant <tenant_id> --k 5
   ```

## Case B: dimension change (e.g. multilingual-e5-large, 1024d)

As case A, plus the vector column resize **before** restarting the services:

```sql
-- run as a role with the needed privileges (see BYPASSRLS note in 0014)
DROP INDEX IF EXISTS ix_chunks_embedding_hnsw;
DELETE FROM chunks;
ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1024);
CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
```

The first `worker`/`api` start downloads the ONNX model (~2.2 GB) into the
`fastembed_cache` volume and can take a few minutes.

## Rollback

Set `EMBEDDING_MODEL`/`EMBEDDING_DIM` back, repeat the restart + chunk-clear
+ reindex steps for the old model.
