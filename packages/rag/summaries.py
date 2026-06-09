"""Deterministic document summaries for the knowledge-base UI."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from packages.llm import complete_chat_json
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
    chunks: list[str] = field(default_factory=list)


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


_AI_NOTEBOOK_MODEL = "deepseek/deepseek-v4-flash"
_AI_NOTEBOOK_MAX_CONTEXT_CHARS = 60_000
_AI_NOTEBOOK_MAX_SOURCE_CHARS = 8_000
_AI_NOTEBOOK_MAX_TOKENS = 1_200


class _GeneratedNotebookInsights(BaseModel):
    summary: str = Field(min_length=40, max_length=1_400)
    key_topics: list[str] = Field(min_length=3, max_length=6)
    suggested_questions: list[str] = Field(min_length=3, max_length=3)


def _source_context(sources: list[NotebookInsightSource]) -> list[dict[str, str]]:
    source_texts: list[tuple[str, str]] = []
    for source in sources:
        parts = [source.summary, *source.chunks]
        text = _normalize_text(" ".join(part for part in parts if part.strip()))
        if text:
            source_texts.append((source.filename, text))

    if not source_texts:
        return []

    per_source_chars = min(
        _AI_NOTEBOOK_MAX_SOURCE_CHARS,
        max(200, _AI_NOTEBOOK_MAX_CONTEXT_CHARS // len(source_texts)),
    )
    return [
        {
            "filename": filename,
            "content": _trim_at_word(text, per_source_chars),
        }
        for filename, text in source_texts
    ]


async def generate_notebook_insights(
    sources: list[NotebookInsightSource],
    *,
    title: str,
    complete_json: Callable[..., Awaitable[str]] | None = None,
) -> NotebookInsights:
    """Generate a concise collection-wide overview from indexed source text."""
    source_context = _source_context(sources)
    if not source_context:
        return NotebookInsights()

    completion = complete_json or complete_chat_json
    messages = [
        {
            "role": "system",
            "content": (
                "Ты создаёшь обзор коллекции документов строго по переданным источникам. "
                "Верни только валидный JSON без markdown. Формат JSON: "
                '{"summary":"2-4 предложения","key_topics":["тема"],'
                '"suggested_questions":["вопрос"]}. '
                "summary должен синтезировать содержание всех источников, а не копировать "
                "сырой текст, команды или начинаться с имени файла. key_topics: 3-6 коротких "
                "тем без дублей. suggested_questions: ровно 3 конкретных вопроса на русском "
                "для дальнейшего чата; вместе они должны охватывать разные источники. "
                "Не выдумывай факты и не используй название коллекции как подстановку "
                "в шаблонный вопрос."
            ),
        },
        {
            "role": "user",
            "content": (
                "Создай JSON-обзор этой коллекции:\n"
                + json.dumps(
                    {
                        "title": title.strip(),
                        "sources": source_context,
                    },
                    ensure_ascii=False,
                )
            ),
        },
    ]
    raw = await completion(
        _AI_NOTEBOOK_MODEL,
        messages,
        max_tokens=_AI_NOTEBOOK_MAX_TOKENS,
    )
    generated = _GeneratedNotebookInsights.model_validate_json(raw)

    return NotebookInsights(
        summary=_normalize_text(generated.summary),
        key_topics=[_normalize_text(topic) for topic in generated.key_topics],
        suggested_questions=[
            _normalize_text(question) for question in generated.suggested_questions
        ],
    )
