from __future__ import annotations

from pathlib import Path

COMPOSE = Path("docker-compose.yml").read_text()


def test_api_container_receives_runtime_guardrail_environment() -> None:
    expected = [
        "ALLOWED_ORIGINS:",
        "HTTP_FETCH_ALLOWED_DOMAINS:",
        "AGENT_QUERY_MAX_CHARS:",
        "AGENT_RATE_LIMIT_PER_MINUTE:",
        "LLM_TIMEOUT_SECONDS:",
        "MAX_UPLOAD_BYTES:",
        "MAX_BULK_TOTAL_BYTES:",
        "BUDGET_ALERT_USD_PER_CALL:",
        "ENABLE_CODE_EXEC:",
    ]

    for item in expected:
        assert item in COMPOSE


def test_worker_container_receives_runtime_guardrail_environment() -> None:
    worker_section = COMPOSE.split("  worker:", maxsplit=1)[1].split("  ui:", maxsplit=1)[0]
    expected = [
        "HTTP_FETCH_ALLOWED_DOMAINS:",
        "LLM_TIMEOUT_SECONDS:",
        "BUDGET_ALERT_USD_PER_CALL:",
        "ENABLE_CODE_EXEC:",
    ]

    for item in expected:
        assert item in worker_section


def test_api_container_receives_rag_environment() -> None:
    api_section = COMPOSE.split("  api:", maxsplit=1)[1].split("  worker:", maxsplit=1)[0]
    expected = [
        "EMBEDDING_MODEL:",
        "EMBEDDING_DIM:",
        "RETRIEVAL_MAX_DISTANCE:",
        "RETRIEVAL_TOP_K:",
        "FAST_RAG_CANDIDATE_K:",
        "SCOPED_RAG_CANDIDATE_K:",
        "FAST_RAG_TOP_K:",
        "FAST_RAG_PER_DOCUMENT_K:",
        "FAST_RAG_CONTEXT_MAX_CHARS:",
        "HYBRID_SEARCH_ENABLED:",
    ]

    for item in expected:
        assert item in api_section


def test_worker_container_receives_rag_environment() -> None:
    worker_section = COMPOSE.split("  worker:", maxsplit=1)[1].split("  ui:", maxsplit=1)[0]
    expected = [
        "EMBEDDING_MODEL:",
        "EMBEDDING_DIM:",
        "EMBEDDING_BATCH_SIZE:",
        "CHUNK_SIZE:",
        "CHUNK_OVERLAP:",
        "OCR_LANGUAGE:",
        "RETRIEVAL_MAX_DISTANCE:",
        "RETRIEVAL_TOP_K:",
        "HYBRID_SEARCH_ENABLED:",
    ]

    for item in expected:
        assert item in worker_section
