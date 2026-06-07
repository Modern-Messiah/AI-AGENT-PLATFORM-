"""Document → plain text.

PDF: pymupdf — best-in-class text extraction, handles complex layouts.
Everything else: markitdown (docx, pptx, xlsx, html, md, txt, images).
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # type: ignore[import-untyped]  # pymupdf
from markitdown import MarkItDown

_md = MarkItDown()


@dataclass
class ParsedSegment:
    text: str
    metadata: dict[str, object] = field(default_factory=dict)


def _parse_pdf(data: bytes) -> list[ParsedSegment]:
    with fitz.open(stream=data, filetype="pdf") as doc:
        segments = []
        for page_number, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if text:
                segments.append(ParsedSegment(text=text, metadata={"page": page_number}))
    if not segments:
        raise ValueError("PDF не содержит текстового слоя — возможно, отсканирован или защищён")
    return segments


def _parse_sync(data: bytes, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as f:
        f.write(data)
        f.flush()
        result = _md.convert(f.name)
        return result.text_content or ""


async def parse_to_segments(data: bytes, filename: str) -> list[ParsedSegment]:
    suffix = Path(filename).suffix.lower() or ".bin"
    if suffix == ".pdf":
        return await asyncio.to_thread(_parse_pdf, data)
    text = await asyncio.to_thread(_parse_sync, data, suffix)
    return [ParsedSegment(text=text)] if text.strip() else []


async def parse_to_text(data: bytes, filename: str) -> str:
    """Backward-compatible plain-text view of parsed document segments."""
    segments = await parse_to_segments(data, filename)
    return "\n\n".join(segment.text for segment in segments)
