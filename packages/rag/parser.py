"""Document → plain text.

PDF: pypdf (reliable text layer extraction).
Everything else: markitdown (docx, pptx, xlsx, html, md, txt, images).
"""

from __future__ import annotations

import asyncio
import io
import tempfile
from pathlib import Path

import pypdf
from markitdown import MarkItDown

_md = MarkItDown()


def _parse_pdf(data: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        text = text.strip()
        if text:
            pages.append(text)
    if not pages:
        raise ValueError("PDF содержит только изображения или защищён от копирования — текст не извлечён")
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
