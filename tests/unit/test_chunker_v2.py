from __future__ import annotations

from packages.core import settings
from packages.rag.chunker import TextChunk, _budget_for, _split_by_headings, chunk_segments
from packages.rag.parser import ParsedSegment


def test_split_by_headings_extracts_sections_and_preamble() -> None:
    text = (
        "Вводный текст без заголовка.\n\n"
        "## Настройка сети\n\nСодержимое раздела сети.\n\n"
        "### Firewall\n\nСодержимое про firewall.\n"
    )

    sections = _split_by_headings(text)

    assert [heading for _level, heading, _body in sections] == [
        "",
        "Настройка сети",
        "Firewall",
    ]
    # heading lines stay inside their section text (helps retrieval)
    assert "## Настройка сети" in sections[1][2]
    assert "### Firewall" in sections[2][2]


def test_chunk_segments_carries_heading_metadata() -> None:
    text = "## Deploy\n\nЗапуск сервиса через uvicorn. " * 30
    chunks = chunk_segments([ParsedSegment(text=text, metadata={"page": 3})])

    assert chunks
    assert all(chunk.metadata.get("heading") == "Deploy" for chunk in chunks)
    assert all(chunk.metadata.get("page") == 3 for chunk in chunks)
    assert any("## Deploy" in chunk.content for chunk in chunks)


def test_budget_shrinks_for_cyrillic_dominant_text() -> None:
    cyrillic_budget, cyrillic_overlap = _budget_for("настройка сертификата " * 50)
    latin_budget, _ = _budget_for("configure the certificate " * 50)

    assert latin_budget == settings.chunk_size
    assert cyrillic_budget == int(settings.chunk_size * 0.6)
    assert cyrillic_overlap < settings.chunk_overlap


def test_mixed_text_with_latin_majority_keeps_full_budget() -> None:
    budget, overlap = _budget_for("mostly latin text with слово cyrillic words " * 20)
    assert budget == settings.chunk_size
    assert overlap == settings.chunk_overlap


def test_long_cyrillic_text_produces_smaller_chunks_than_latin() -> None:
    # equal char counts: the Russian text must come out in smaller pieces
    # (≈ equal token budgets) than the English one
    ru_segments = [
        ParsedSegment(text=("Требования к инфраструктуре. Подробное описание. " * 80), metadata={})
    ]
    en_segments = [
        ParsedSegment(
            text=("Infrastructure requirements. A detailed description. " * 80), metadata={}
        )
    ]

    ru_chunks = chunk_segments(ru_segments)
    en_chunks = chunk_segments(en_segments)

    assert max(len(chunk.content) for chunk in ru_chunks) < max(
        len(chunk.content) for chunk in en_chunks
    )


def test_chunk_segments_without_headings_matches_plain_split() -> None:
    text = "Простой текст из нескольких предложений. " * 100
    chunks = chunk_segments([ParsedSegment(text=text, metadata={"page": 1})])

    assert chunks
    assert "heading" not in chunks[0].metadata
    assert all(isinstance(chunk, TextChunk) for chunk in chunks)
