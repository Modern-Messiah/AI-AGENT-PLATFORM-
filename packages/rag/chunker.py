"""Recursive character chunker. Tokens-aware variant comes if eval shows quality issues."""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_text_splitters import RecursiveCharacterTextSplitter

from packages.core import settings
from packages.rag.parser import ParsedSegment

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=settings.chunk_size,
    chunk_overlap=settings.chunk_overlap,
    separators=["\n\n", "\n", ". ", " ", ""],
)


@dataclass
class TextChunk:
    content: str
    metadata: dict = field(default_factory=dict)


def chunk_segments(segments: list[ParsedSegment]) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for segment in segments:
        chunks.extend(
            TextChunk(content=content, metadata=dict(segment.metadata))
            for content in _splitter.split_text(segment.text)
            if content.strip()
        )
    return chunks


def chunk_text(text: str) -> list[str]:
    if not text.strip():
        return []
    return [chunk.content for chunk in chunk_segments([ParsedSegment(text=text)])]
