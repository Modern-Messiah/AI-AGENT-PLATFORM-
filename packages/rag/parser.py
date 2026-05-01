"""Document → plain text.

PDF: pymupdf — best-in-class text extraction, handles complex layouts.
Everything else: markitdown (docx, pptx, xlsx, html, md, txt, images).
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import fitz  # pymupdf
from markitdown import MarkItDown

_md = MarkItDown()


def _parse_pdf(data: bytes) -> str:
    with fitz.open(stream=data, filetype="pdf") as doc:
        pages = [page.get_text("text").strip() for page in doc if page.get_text("text").strip()]
    if not pages:
        raise ValueError(
            "PDF не содержит текстового слоя — возможно, отсканирован или защищён"
        )
    return "\n\n".join(pages)


def _parse_sync(data: bytes, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as f:
        f.write(data)
        f.flush()
        result = _md.convert(f.name)
        return result.text_content or ""


async def parse_to_text(data: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower() or ".bin"
    if suffix == ".pdf":
        return await asyncio.to_thread(_parse_pdf, data)
    return await asyncio.to_thread(_parse_sync, data, suffix)
