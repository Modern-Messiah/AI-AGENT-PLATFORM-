from __future__ import annotations

from packages.rag.multilang_ocr import parse_ocr_languages, select_best_ocr
from packages.rag.visual import OCRResult


def test_parse_ocr_languages() -> None:
    assert parse_ocr_languages("ru") == ["ru"]
    assert parse_ocr_languages("ru,en") == ["ru", "en"]
    assert parse_ocr_languages(" ru , en , de ") == ["ru", "en", "de"]
    assert parse_ocr_languages(",,") == []


def test_select_best_prefers_more_characters_over_confidence() -> None:
    winner = select_best_ocr(
        [
            ("ru", OCRResult(text="Квитанция об оплате услуг связи", confidence=0.61)),
            ("en", OCRResult(text="ok", confidence=0.99)),
        ]
    )
    assert winner.text == "Квитанция об оплате услуг связи"


def test_select_best_breaks_ties_by_confidence() -> None:
    winner = select_best_ocr(
        [
            ("ru", OCRResult(text="одинаковая длина", confidence=0.7)),
            ("en", OCRResult(text="same length here", confidence=0.9)),
        ]
    )
    assert winner.confidence == 0.9


def test_select_best_handles_empty_inputs() -> None:
    assert select_best_ocr([]) == OCRResult(text="", confidence=None)
    assert select_best_ocr([("ru", OCRResult(text="", confidence=None))]).text == ""


def test_single_language_skips_ocr_dispatch(monkeypatch) -> None:
    from packages.rag import multilang_ocr

    async def unused(*args, **kwargs):  # pragma: no cover
        raise AssertionError

    called: list[bytes] = []

    def fake_single(image_bytes: bytes) -> OCRResult:
        called.append(image_bytes)
        return OCRResult(text="текст", confidence=0.9)

    monkeypatch.setattr(multilang_ocr, "run_paddle_ocr", fake_single)
    monkeypatch.setattr(multilang_ocr, "run_paddle_ocr_multilang", unused)

    result = multilang_ocr.run_multilang_ocr(b"img", "ru")
    assert result.text == "текст"
    assert called == [b"img"]


def test_multi_language_runs_all_and_selects(monkeypatch) -> None:
    from packages.rag import multilang_ocr

    def fake_multi(image_bytes: bytes, languages: list[str]) -> list[OCRResult]:
        assert languages == ["ru", "en"]
        return [
            OCRResult(text="только русский", confidence=0.8),
            OCRResult(text="full english sentence wins", confidence=0.7),
        ]

    monkeypatch.setattr(multilang_ocr, "run_paddle_ocr_multilang", fake_multi)

    result = multilang_ocr.run_multilang_ocr(b"img", "ru,en")
    assert result.text == "full english sentence wins"
