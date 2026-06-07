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
