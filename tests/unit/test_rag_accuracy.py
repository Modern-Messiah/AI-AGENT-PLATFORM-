"""Unit tests for the RAG accuracy package.

Covers the three deterministic improvements: language-aware noise filter
(cross-lingual queries keep their hits), numeric/phrase rerank boosts, and
the faithfulness verdict plumbing (refusal of fully-unsupported answers,
confidence penalty, sentence splitting). The verifier LLM leg is faked.
"""

from __future__ import annotations

import pytest
from packages.core import settings
from packages.rag.citations import CitationSource, calibrate_confidence
from packages.rag.faithfulness import (
    FaithfulnessVerdict,
    split_answer_sentences,
    verify_answer_faithfulness,
)
from packages.rag.retriever import (
    RetrievedChunk,
    filter_unsupported_query_chunks,
    rerank_chunks,
)


def _chunk(content: str, score: float, idx: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        document_id="d",
        chunk_id="c",
        filename="doc.txt",
        content=content,
        score=score,
        chunk_idx=idx,
        metadata={},
    )


# ── language-aware filter ────────────────────────────────────────────────────


def test_crosslingual_query_keeps_semantic_hits() -> None:
    """EN question over an RU corpus: zero lexical overlap is expected,
    not noise — the hit must survive at a lower semantic bar."""
    chunks = [_chunk("Оплата тарифа «Команда» — 4900 рублей в месяц.", 0.50)]

    assert filter_unsupported_query_chunks("how much does the team plan cost", chunks) == chunks


def test_same_language_noise_is_still_filtered() -> None:
    """RU question over an RU corpus with weak scores and no lexical
    overlap stays noise and is dropped."""
    chunks = [_chunk("Совершенно посторонний текст про грибы и погоду.", 0.40)]

    assert filter_unsupported_query_chunks("как настроить vpn шлюз", chunks) == []


def test_strong_semantic_passes_even_same_language() -> None:
    chunks = [_chunk("гейт недоступен проверьте токен", 0.80)]
    assert filter_unsupported_query_chunks("шлюз не отвечает", chunks) == chunks


# ── rerank boosts ────────────────────────────────────────────────────────────


def test_numbers_match_outranks_semantic_lookalike() -> None:
    """The chunk carrying the asked-for code beats a semantically closer
    chunk without it."""
    with_code = _chunk("Код TIMEOUT_504_GATEWAY: проверьте очередь.", 0.45)
    lookalike = _chunk("Код ошибки шлюза при таймауте апстрима.", 0.60)

    ranked = rerank_chunks("ошибка 504 TIMEOUT_504_GATEWAY", [lookalike, with_code])

    assert ranked[0] is with_code


def test_exact_phrase_boost() -> None:
    phrase_chunk = _chunk("... инструкция по настройке беспроводной сети ...", 0.40)
    other = _chunk("настройка проводного подключения", 0.55)

    ranked = rerank_chunks("инструкция по настройке беспроводной сети", [other, phrase_chunk])

    assert ranked[0] is phrase_chunk


# ── faithfulness plumbing ────────────────────────────────────────────────────


def test_sentence_splitting() -> None:
    answer = "Первое предложение. Второе предложение! Третье?"
    assert len(split_answer_sentences(answer)) == 3
    assert split_answer_sentences("  ") == []


def _sources() -> list[CitationSource]:
    return [
        CitationSource(
            id=1,
            document_id="d",
            chunk_id="c",
            filename="doc.txt",
            page=1,
            chunk_index=0,
            excerpt="Бэкап делается в 03:15 UTC каждый день.",
            score=0.9,
        )
    ]


async def test_fully_unsupported_answer_is_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "answer_verification_enabled", True)

    async def fake_complete(model: str, messages: object, *, max_tokens: int) -> str:
        return '{"supported": [], "unsupported": [1, 2]}'

    import packages.rag.faithfulness as faith

    monkeypatch.setattr(faith, "complete_chat_json", fake_complete)

    verdict = await verify_answer_faithfulness(
        "Резервные копии хранятся вечно. Восстановление невозможно.", _sources()
    )
    assert verdict.verified is False
    assert verdict.unsupported_sentences == [1, 2]
    assert verdict.unsupported_ratio == 1.0


async def test_verifier_outage_degrades_not_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "answer_verification_enabled", True)

    async def broken(model: str, messages: object, *, max_tokens: int) -> str:
        raise RuntimeError("weak model down")

    import packages.rag.faithfulness as faith

    monkeypatch.setattr(faith, "complete_chat_json", broken)

    verdict = await verify_answer_faithfulness("Бэкап в 03:15. Хранится 30 дней.", _sources())
    assert verdict.verified is False
    assert verdict.error


async def test_disabled_verification_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "answer_verification_enabled", False)

    called = []

    async def must_not_run(model: str, messages: object, *, max_tokens: int) -> str:
        called.append(1)
        return "{}"

    import packages.rag.faithfulness as faith

    monkeypatch.setattr(faith, "complete_chat_json", must_not_run)

    verdict = await verify_answer_faithfulness("Любой текст.", _sources())
    assert verdict.verified is True and verdict.error == "disabled"
    assert not called


# ── confidence with verdict ─────────────────────────────────────────────────


def test_confidence_penalised_by_unsupported_share() -> None:
    chunk = _chunk("источник", 0.9)
    sources = _sources()

    clean = calibrate_confidence([chunk], sources, "текст", verdict=FaithfulnessVerdict())
    half = calibrate_confidence(
        [chunk],
        sources,
        "текст",
        verdict=FaithfulnessVerdict(
            verified=False, total_sentences=4, unsupported_sentences=[1, 2]
        ),
    )
    unverified = calibrate_confidence(
        [chunk], sources, "текст", verdict=FaithfulnessVerdict(verified=False, error="boom")
    )

    assert half < clean
    assert unverified <= 0.75
    assert clean >= unverified >= half or clean > half
