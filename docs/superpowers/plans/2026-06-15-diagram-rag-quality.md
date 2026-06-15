# Diagram RAG Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Russian questions about diagrams retrieve complete diagram logic and preserve every selected citation in the LLM context.

**Architecture:** pgvector remains the candidate generator. A small pure-Python reranker adds Unicode lexical relevance, visual descriptions are sectioned before chunking, and context assembly allocates space fairly across citations. A 384-dimensional multilingual embedding model is available as an opt-in without a database migration.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, pgvector, FastEmbed, LangChain text splitters, pytest.

---

### Task 1: Lexical Reranking

**Files:**
- Modify: `packages/rag/retriever.py`
- Test: `tests/unit/test_retriever_reranking.py`

- [ ] Write tests proving an exact Russian diagram title outranks generic high-scoring chunks.
- [ ] Run the focused test and confirm it fails before implementation.
- [ ] Add Unicode tokenization, lexical scoring, and deterministic reranking helpers.
- [ ] Run the focused test and confirm it passes.

### Task 2: Fair Context Allocation

**Files:**
- Modify: `packages/rag/citations.py`
- Test: `tests/unit/test_rag_citations.py`

- [ ] Add a test with six long citations and an 8,000-character budget.
- [ ] Confirm the current greedy implementation drops the sixth citation.
- [ ] Allocate a minimum excerpt budget per citation and distribute remaining space.
- [ ] Confirm all six citation markers and useful excerpts appear.

### Task 3: Diagram-Aware Visual Segments

**Files:**
- Modify: `packages/rag/visual.py`
- Modify: `apps/worker/activities/ingestion.py`
- Test: `tests/unit/test_visual_ingestion.py`

- [ ] Add a test for two Markdown diagram sections on one visual page.
- [ ] Confirm generic splitting separates a heading from its flow description.
- [ ] Add a pure helper that returns page text plus self-contained visual sections.
- [ ] Store each section as a separate `ParsedSegment` with the same page and asset metadata.

### Task 4: Multilingual Embeddings

**Files:**
- Modify: `packages/core/settings.py`
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `apps/worker/activities/ingestion.py`
- Modify: `packages/rag/retriever.py`
- Test: `tests/unit/test_ingestion_metadata.py`
- Test: `tests/unit/test_retriever_reranking.py`

- [ ] Document `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` as an opt-in model that requires complete reindexing.
- [ ] Store `embedding_model` in chunk metadata.
- [ ] Keep the existing model as the backward-compatible default.
- [ ] Verify the worktree can reindex all local documents with the opt-in model.

### Task 5: Diagram-Focused Vision

**Files:**
- Modify: `apps/worker/activities/ingestion.py`
- Test: `tests/unit/test_ingestion_metadata.py`

- [ ] Add a test asserting the Vision prompt requests nodes, conditions, transitions, and loops.
- [ ] Replace the generic formatting prompt with a concise diagram/table extraction prompt.
- [ ] Verify text-only pages still skip Vision.

### Task 6: End-to-End Verification

**Files:**
- No production file changes.

- [ ] Run backend unit tests.
- [ ] Run frontend tests.
- [ ] Rebuild API and worker containers.
- [ ] Reindex the incident-bot PDF.
- [ ] Run the three acceptance questions and inspect cited pages.
- [ ] Review container logs for errors.
