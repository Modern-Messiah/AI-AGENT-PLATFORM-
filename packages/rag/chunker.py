"""Recursive character chunker. Tokens-aware variant comes if eval shows quality issues."""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from packages.core import settings


def chunk_text(text: str) -> list[str]:
    if not text.strip():
        return []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return [c for c in splitter.split_text(text) if c.strip()]
