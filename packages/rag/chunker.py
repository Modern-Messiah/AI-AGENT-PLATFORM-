"""Structure-aware chunker.

- Markdown headings (MarkItDown output for docx/html/md sources) split
  first: the heading text rides along in chunk metadata and stays inside
  the chunk content, so retrieval matches section titles.
- Char budgets account for script: Cyrillic averages ~2 chars/token vs ~4
  for Latin, so a fixed char budget produces ~2x larger token chunks for
  Russian. Cyrillic-dominant text gets a proportionally smaller budget.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from langchain_text_splitters import RecursiveCharacterTextSplitter

from packages.core import settings
from packages.rag.parser import ParsedSegment

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)
_CYRILLIC_RE = re.compile("[\\u0430-\\u044f\\u0451\\u0410-\\u042f\\u0401]")  # a-ya, yo, A-YA, YO
_LATIN_RE = re.compile(r"[a-zA-Z]")

# Cyrillic text needs ~40% fewer chars for the same token budget.
_CYRILLIC_BUDGET_FACTOR = 0.6
_CYRILLIC_MIN_BUDGET = 400


@dataclass
class TextChunk:
    content: str
    metadata: dict[str, object] = field(default_factory=dict)


@lru_cache(maxsize=4)
def _splitter_for(chunk_size: int, chunk_overlap: int) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def _budget_for(text: str) -> tuple[int, int]:
    """(chunk_size, overlap) scaled down for Cyrillic-dominant text."""
    cyrillic = len(_CYRILLIC_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    letters = cyrillic + latin
    if letters == 0 or cyrillic / letters < 0.3:
        return settings.chunk_size, settings.chunk_overlap
    budget = max(_CYRILLIC_MIN_BUDGET, int(settings.chunk_size * _CYRILLIC_BUDGET_FACTOR))
    overlap = max(60, int(settings.chunk_overlap * budget / settings.chunk_size))
    return budget, overlap


def _split_by_headings(text: str) -> list[tuple[str, str, str]]:
    """[(heading_level, heading_text, section_text)] in document order.

    Section text includes the heading line itself — headings help retrieval.
    Text before the first heading becomes a heading-less preamble section.
    """
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("", "", text)]
    sections: list[tuple[str, str, str]] = []
    preamble = text[: matches[0].start()]
    if preamble.strip():
        sections.append(("", "", preamble))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        level, title = match.group(1), match.group(2).strip()
        body = text[match.start() : end]
        if body.strip():
            sections.append((level, title, body))
    return sections


def chunk_segments(segments: list[ParsedSegment]) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for segment in segments:
        for _level, heading, section_text in _split_by_headings(segment.text):
            if not section_text.strip():
                continue
            budget, overlap = _budget_for(section_text)
            splitter = _splitter_for(budget, overlap)
            for content in splitter.split_text(section_text):
                if not content.strip():
                    continue
                metadata = dict(segment.metadata)
                if heading:
                    metadata["heading"] = heading
                chunks.append(TextChunk(content=content, metadata=metadata))
    return chunks


def chunk_text(text: str) -> list[str]:
    if not text.strip():
        return []
    return [chunk.content for chunk in chunk_segments([ParsedSegment(text=text)])]
