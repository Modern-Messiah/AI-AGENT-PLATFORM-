"""Multilingual OCR: run every configured language, keep the best result.

OCR_LANGUAGE accepts a comma-separated list (e.g. "ru,en"; default "ru").
Each language gets its own lazily-initialized PaddleOCR engine — they are
heavy, initialized once per process and reused. The winner per page is
picked by (characters recognized, confidence): mixed-language documents
stop losing whichever script the single engine did not know.
"""

from __future__ import annotations

import logging

from packages.rag.visual import OCRResult, run_paddle_ocr, run_paddle_ocr_multilang

log = logging.getLogger(__name__)

__all__ = ["run_multilang_ocr", "select_best_ocr"]


def parse_ocr_languages(raw: str) -> list[str]:
    return [lang.strip() for lang in raw.split(",") if lang.strip()]


def select_best_ocr(results: list[tuple[str, OCRResult]]) -> OCRResult:
    """Pick the winner among per-language results.

    More recognized characters beats confidence: an engine that read the
    page wins over a confident engine that read almost nothing.
    """
    if not results:
        return OCRResult(text="", confidence=None)
    ranked = sorted(
        results,
        key=lambda item: (len(item[1].text), item[1].confidence or 0.0),
        reverse=True,
    )
    winner_lang, winner = ranked[0]
    if len(results) > 1:
        log.info(
            "multilang ocr picked %s | chars=%d confidence=%s candidates=%s",
            winner_lang,
            len(winner.text),
            winner.confidence,
            {lang: len(res.text) for lang, res in results},
        )
    return winner


def run_multilang_ocr(image_bytes: bytes, languages_raw: str | None = None) -> OCRResult:
    """OCR the page with every configured language, best result wins."""
    from packages.core import settings

    langs = parse_ocr_languages(languages_raw or settings.ocr_language)
    if len(langs) <= 1:
        return run_paddle_ocr(image_bytes)
    results = run_paddle_ocr_multilang(image_bytes, langs)
    return select_best_ocr(list(zip(langs, results, strict=True)))
