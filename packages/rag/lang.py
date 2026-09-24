"""Script-based language detection for the RU/EN knowledge base.

Deliberately dependency-free and deterministic: the product's corpus is
Russian + English, and script share decides reliably. Ambiguous cases
(no letters, balanced scripts) return None instead of guessing.
"""

from __future__ import annotations

import re

_CYRILLIC_RE = re.compile("[\\u0430-\\u044f\\u0451\\u0410-\\u042f\\u0401]")  # a-ya, yo, A-YA, YO
_LATIN_RE = re.compile(r"[a-zA-Z]")

# Below this Cyrillic share a text is treated as Latin/other.
_CYRILLIC_SHARE_THRESHOLD = 0.3


def detect_language(text: str) -> str | None:
    """Return 'ru', 'en' or None (undetermined) for the given text."""
    cyrillic = len(_CYRILLIC_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    letters = cyrillic + latin
    if letters == 0:
        return None
    if cyrillic / letters >= _CYRILLIC_SHARE_THRESHOLD:
        return "ru"
    return "en"
