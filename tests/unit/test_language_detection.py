from __future__ import annotations

from packages.rag.lang import detect_language


def test_detects_russian() -> None:
    assert detect_language("Инструкция по настройке сети и сертификатов") == "ru"


def test_detects_english() -> None:
    assert detect_language("Deployment guide with firewall rules") == "en"


def test_mixed_text_with_cyrillic_majority_is_russian() -> None:
    assert detect_language("Требования к среде: нужен Python 3.12 и uvicorn") == "ru"


def test_text_with_rare_cyrillic_words_is_english() -> None:
    # mostly Latin with one borrowed Russian word stays English
    assert detect_language("Run the deploy script, check sputnik logs and restart") == "en"


def test_no_letters_returns_none() -> None:
    assert detect_language("12345 67890 !!! ???") is None
    assert detect_language("") is None
