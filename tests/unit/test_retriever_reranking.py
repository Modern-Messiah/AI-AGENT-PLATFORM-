from packages.rag.retriever import (
    RetrievedChunk,
    candidate_limit_for_scope,
    effective_max_distance_for_scope,
    rerank_chunks,
)


def _chunk(
    chunk_id: str,
    content: str,
    score: float,
    *,
    page: int = 4,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="document-1",
        filename="incident-bot.pdf",
        content=content,
        score=score,
        metadata={"page": page},
        chunk_idx=int(chunk_id.rsplit("-", 1)[-1]),
    )


def test_reranking_promotes_exact_russian_diagram_evidence() -> None:
    candidates = [
        _chunk(
            "chunk-1",
            "Общие вопросы диагностики: перезагружали ли роутер?",
            0.76,
        ),
        _chunk(
            "chunk-2",
            "Схема 2. Первичное решение проблемы. Если перезагрузка роутера "
            "не помогла, проверить индикаторы, кабель и расположение. "
            "Если повторная проверка не помогла, создать тикет.",
            0.62,
        ),
        _chunk(
            "chunk-3",
            "Описание систем мониторинга и обработки обращений.",
            0.74,
        ),
    ]

    ranked = rerank_chunks(
        "Что происходит по схеме 2, если перезагрузка роутера не помогла?",
        candidates,
    )

    assert ranked[0].chunk_id == "chunk-2"


def test_reranking_keeps_semantic_order_when_lexical_evidence_is_equal() -> None:
    candidates = [
        _chunk("chunk-1", "Проверка состояния клиента.", 0.81),
        _chunk("chunk-2", "Проверка состояния узла.", 0.72),
    ]

    ranked = rerank_chunks("Как выполняется диагностика?", candidates)

    assert [chunk.chunk_id for chunk in ranked] == ["chunk-1", "chunk-2"]


def test_reranking_promotes_title_page_metadata_queries() -> None:
    candidates = [
        _chunk(
            "chunk-8",
            "Таблица интеграций: webhook, backend, статусы обращений и проверки.",
            0.55,
            page=8,
        ),
        _chunk(
            "chunk-1",
            "Техническое задание. Версия: 1.0. Автор: Тимиров Рустам. "
            "Дата: 05.03.2026.",
            0.20,
            page=1,
        ),
    ]

    ranked = rerank_chunks(
        "Кто автор документа, какая версия и дата указаны на титульной странице?",
        candidates,
    )

    assert ranked[0].chunk_id == "chunk-1"


def test_scoped_document_search_uses_a_wider_candidate_pool() -> None:
    assert candidate_limit_for_scope(
        default_limit=12,
        scoped_limit=32,
        document_id="document-1",
        document_ids=None,
    ) == 32
    assert candidate_limit_for_scope(
        default_limit=12,
        scoped_limit=32,
        document_id=None,
        document_ids=None,
    ) == 12


def test_single_document_scope_disables_distance_cutoff() -> None:
    assert effective_max_distance_for_scope(
        configured_max_distance=0.75,
        document_id="document-1",
        document_ids=None,
    ) == 0
    assert effective_max_distance_for_scope(
        configured_max_distance=0.75,
        document_id=None,
        document_ids=["document-1", "document-2"],
    ) == 0.75
