"""Document → plain text via markitdown.

Covers pdf, docx, pptx, xlsx, html, md, txt, images (OCR if backend
present). For unsupported types markitdown raises — let it propagate so
the activity fails and Temporal records the failure.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from markitdown import MarkItDown

_md = MarkItDown()


def _parse_sync(data: bytes, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as f:
        f.write(data)
        f.flush()
        result = _md.convert(f.name)
        return result.text_content or ""


async def parse_to_text(data: bytes, filename: str) -> str:
    suffix = Path(filename).suffix or ".bin"
    return await asyncio.to_thread(_parse_sync, data, suffix)
