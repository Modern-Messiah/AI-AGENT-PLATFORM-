"""Deterministic document summaries for the knowledge-base UI."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from packages.rag.parser import ParsedSegment

_SPACE_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_MAX_SOURCE_CHARS = 4_000
_MAX_SUMMARY_CHARS = 700


@dataclass
class DocumentInsights:
    summary: str = ""
    suggested_questions: list[str] = field(default_factory=list)


@dataclass
class NotebookInsightSource:
    filename: str
    summary: str = ""
    suggested_questions: list[str] = field(default_factory=list)


@dataclass
class NotebookInsights:
    summary: str = ""
    suggested_questions: list[str] = field(default_factory=list)
    key_topics: list[str] = field(default_factory=list)


def _normalize_text(text: str) -> str:
    return _SPACE_RE.sub(" ", text).strip()


def _trim_at_word(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    content_limit = max_chars - 3
    trimmed = text[:content_limit].rsplit(" ", 1)[0].strip()
    return f"{trimmed}..." if trimmed else text[:max_chars].strip()


def build_document_insights(
    segments: list[ParsedSegment],
    *,
    filename: str,
) -> DocumentInsights:
    text = _normalize_text(" ".join(segment.text for segment in segments))[:_MAX_SOURCE_CHARS]
    if not text:
        return DocumentInsights()

    sentences = [sentence.strip() for sentence in _SENTENCE_RE.split(text) if sentence.strip()]
    summary_parts: list[str] = []
    used_chars = 0
    for sentence in sentences[:5]:
        next_len = used_chars + len(sentence) + (1 if summary_parts else 0)
        if next_len > _MAX_SUMMARY_CHARS:
            break
        summary_parts.append(sentence)
        used_chars = next_len
        if len(summary_parts) >= 3:
            break

    summary = " ".join(summary_parts) if summary_parts else text
    summary = _trim_at_word(summary, _MAX_SUMMARY_CHARS)

    return DocumentInsights(
        summary=summary,
        suggested_questions=[
            f"Кратко объясни, что внутри {filename}?",
            f"Какие ключевые факты есть в {filename}?",
            f"Какие выводы можно сделать из {filename}?",
        ],
    )


_MAX_NOTEBOOK_SUMMARY_CHARS = 900
_TOPIC_RE = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9-]{3,}")
_STOPWORDS = {
    "and",
    "into",
    "that",
    "the",
    "this",
    "with",
    "внутри",
    "документ",
    "документы",
    "какие",
    "можно",
    "сделать",
    "факты",
    "выводы",
}


def _extract_key_topics(text: str, limit: int = 6) -> list[str]:
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    positions: dict[str, int] = {}
    for raw in _TOPIC_RE.findall(text):
        key = raw.lower()
        if key in _STOPWORDS:
            continue
        counts[key] = counts.get(key, 0) + 1
        labels.setdefault(key, raw[:1].upper() + raw[1:])
        positions.setdefault(key, len(positions))

    ranked = sorted(counts, key=lambda item: (-counts[item], positions[item]))
    return [labels[item] for item in ranked[:limit]]


def build_notebook_insights(
    sources: list[NotebookInsightSource],
    *,
    title: str,
) -> NotebookInsights:
    useful_sources = [source for source in sources if _normalize_text(source.summary)]
    if not useful_sources:
        return NotebookInsights()

    summary_parts = [
        f"{source.filename}: {_normalize_text(source.summary)}"
        for source in useful_sources[:4]
    ]
    summary = _trim_at_word(" ".join(summary_parts), _MAX_NOTEBOOK_SUMMARY_CHARS)
    title = title.strip() or "коллекции"
    topic_text = " ".join(
        [source.filename for source in useful_sources]
        + [source.summary for source in useful_sources]
    )

    return NotebookInsights(
        summary=summary,
        suggested_questions=[
            f"Что объединяет документы в {title}?",
            f"Какие ключевые темы повторяются в {title}?",
            f"Какие выводы можно сделать по коллекции {title}?",
        ],
        key_topics=_extract_key_topics(topic_text),
    )
