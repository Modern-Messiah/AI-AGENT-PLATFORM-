from __future__ import annotations

import pytest
from packages.core import settings
from packages.rag.query_expansion import expand_query
from packages.rag.retriever import RetrievedChunk, merge_variant_results


async def test_expand_query_returns_paraphrases_with_original_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "query_expansion_enabled", True)

    async def fake_complete(model, messages, *, max_tokens):
        assert '"target_language": null' in messages[1]["content"]
        return '{"variants": ["как настроить беспроводную сеть маршрутизатора", "параметры wi-fi точки доступа"]}'

    variants = await expand_query(
        "как поменять параметры wifi роутера?",
        complete_json=fake_complete,
    )

    assert variants[0] == "как поменять параметры wifi роутера?"
    assert len(variants) == 3


async def test_expand_query_adds_translation_for_mixed_language_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "query_expansion_enabled", True)

    async def fake_complete(model, messages, *, max_tokens):
        assert '"target_language": "en"' in messages[1]["content"]
        return '{"variants": ["why are citations empty in the answer"]}'

    variants = await expand_query(
        "почему пустые цитаты в ответе",
        corpus_langs=["ru", "en"],
        complete_json=fake_complete,
    )

    assert any("citations" in variant for variant in variants)


async def test_expand_query_falls_back_to_original_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "query_expansion_enabled", True)

    async def broken(model, messages, *, max_tokens):
        raise RuntimeError("provider down")

    assert await expand_query("вопрос", complete_json=broken) == ["вопрос"]


async def test_expand_query_disabled_returns_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "query_expansion_enabled", False)
    assert await expand_query("вопрос") == ["вопрос"]


def _chunk(chunk_id: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="doc",
        filename="f.pdf",
        content="c",
        score=score,
        metadata={},
    )


def test_merge_variant_results_prefers_consensus_and_keeps_best_score() -> None:
    primary = [_chunk("a", 0.30), _chunk("b", 0.25)]
    variant = [_chunk("b", 0.40), _chunk("c", 0.35)]

    merged = merge_variant_results([primary, variant], limit=10)

    # "b" appears in both lists — RRF consensus puts it first
    assert merged[0].chunk_id == "b"
    assert merged[0].score == 0.40  # best score kept
    assert {chunk.chunk_id for chunk in merged} == {"a", "b", "c"}


def test_merge_variant_results_respects_limit() -> None:
    merged = merge_variant_results(
        [[_chunk("a", 0.1)], [_chunk("b", 0.2)], [_chunk("c", 0.3)]],
        limit=2,
    )
    assert len(merged) == 2


async def test_retrieve_chunks_with_expansion_applies_llm_rerank_and_slices_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.rag.query_expansion import retrieve_chunks_with_expansion

    monkeypatch.setattr(settings, "query_expansion_enabled", True)
    monkeypatch.setattr(settings, "llm_rerank_enabled", True)
    monkeypatch.setattr(settings, "rerank_candidate_k", 20)

    # 15 chunks with high score >= 0.55 so query expansion is skipped
    fake_chunks = [_chunk(f"c_{i}", 0.8 - i * 0.01) for i in range(15)]

    async def fake_retrieve(*args, **kwargs):
        return list(fake_chunks)

    rerank_called = []

    async def fake_llm_rerank(query, chunks):
        rerank_called.append(len(chunks))
        # reverse order as a test
        return list(reversed(chunks))

    monkeypatch.setattr("packages.rag.query_expansion.retrieve_chunks", fake_retrieve)
    monkeypatch.setattr("packages.rag.query_expansion.rerank_chunks_with_llm", fake_llm_rerank)

    results = await retrieve_chunks_with_expansion("test query", "acme", k=5)
    assert len(rerank_called) == 1
    assert rerank_called[0] == 15
    # Result must be sliced to k=5, NOT returning all 15 chunks!
    assert len(results) == 5
    assert results[0].chunk_id == "c_14"


async def test_retrieve_chunks_empty_document_ids_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.rag.retriever import retrieve_chunks

    res = await retrieve_chunks("query", "acme", document_ids=[])
    assert res == []

