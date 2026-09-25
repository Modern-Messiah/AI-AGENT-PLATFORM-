# Upgrade notes — September 2026 improvement program

This release is a coordinated quality/platform push (65+ commits): multilingual
RAG, hybrid retrieval, conversation memory, a UI overhaul, and an operations
layer (readiness/metrics/key management/TLS/sandbox). Most of it is
transparent, but a few points REQUIRE ACTION on upgrade.

## Required actions

### 1. Reindex every document (mandatory)

The default embedding model changed from `BAAI/bge-small-en-v1.5`
(English-only) to `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
(multilingual). Vectors from different models are incompatible even at equal
dimensions — retrieval over old chunks degrades silently. Follow
`docs/runbooks/reindex-after-embedding-change.md` (backup → set env → clear
chunks → `scripts/reindex_all.py` → verify). Chunking also changed
(markdown-heading boundaries + Cyrillic token budgets), which the same reindex
picks up.

### 2. Migration 0016 runs automatically, rewrites the chunks table

Adds a stored generated `tsv` column (`simple` + `russian` lexemes) and a GIN
index for hybrid search. Applied by the `migrate` service on `docker compose
up`; the table rewrite is instantaneous at small scale. No data loss.

### 3. MinIO image replaced

MinIO removed the server image from Docker Hub (and gated quay.io). The
compose file now pins `bitnamilegacy/minio` — same binary and S3 API. If you
pin images yourself, read the note in `.env.example` and prefer your own
mirror for production.

## New environment variables (all optional, sane defaults)

| Variable | Default | Purpose |
|---|---|---|
| `HYBRID_SEARCH_ENABLED` | `true` | Vector+FTS hybrid retrieval; `false` = pure vector |
| `EMBEDDING_BATCH_SIZE` | `256` | Worker embedding batch size |
| `CODE_EXEC_SANDBOX_IMAGE` | empty | Docker sandbox for the opt-in code tool |
| `HITL_WEBHOOK_URL` / `HITL_WEBHOOK_BASE_URL` | empty | Reviewer notifications on pending approvals |
| `MINIO_SECURE` | `false` | MinIO client TLS |
| `TLS_DOMAIN` / `TLS_EMAIL` | empty | Caddy TLS profile (`docker compose --profile tls up -d`) |
| `QUERY_EXPANSION_*`, chat-history flags | see `settings.py` | Retrieval escalation knobs |

## New endpoints

- `GET /health/ready` — dependency readiness (PG/Redis/CH/MinIO/Temporal),
  per-check status, 503 when degraded; results cached 5s.
- `GET /metrics` — Prometheus exposition (request counters/latency by route
  template, agent tokens, cache hit ratio).
- `GET /auth/keys`, `DELETE /auth/keys/{id}` — admin key listing/revocation
  (X-Admin-Secret). Revocation evicts the in-process cache via Redis pub/sub
  within milliseconds; reissue via POST is the rotation path.

## Behaviour changes worth knowing

- **Chat has memory**: the UI sends `session_id`; follow-ups are condensed
  into standalone queries (weak model, best-effort fallback). Disable with
  `QUERY_CONDENSATION_ENABLED=false`.
- **Weak retrievals escalate**: below the trigger score the query is
  paraphrased (and translated for mixed-language corpora) and variants are
  RRF-merged. Needs provider keys; degrades to the original query without
  them. `QUERY_EXPANSION_ENABLED=false` restores single-shot retrieval.
- **Confidence is calibrated** (retrieval-evidence-based, not a constant) and
  shown in the chat UI as high/medium/low.
- **Answers render as sanitized markdown** with code highlighting.
- **Document summaries are LLM-generated** (heuristic fallback);
  `AI_DOCUMENT_INSIGHTS_ENABLED=false` restores the old behavior.
- **Markerless answers keep top-2 sources** instead of dropping provenance.
- **Context budget 16k chars, score-weighted** across sources.

## CI

Four green jobs: backend tests, frontend build, compose validation, and a
retrieval-quality gate (live pgvector + real embeddings, recall@5 ≥ 90% on a
deterministic RU/EN corpus). Known hard cases live in
`evals/datasets/KNOWN_GAPS.md` with fix directions — both documented gaps are
closed by query expansion (verified live; CI runs keyless so it exercises the
fallback path).

## Rollback highlights

Every new behaviour has a kill-switch env (see table above); the embedding
rollback procedure is in the reindex runbook. The otel dependency cap
(`<1.44`) and pytest `pythonpath` fix restore a runnable test suite on the
previous revision if needed.
