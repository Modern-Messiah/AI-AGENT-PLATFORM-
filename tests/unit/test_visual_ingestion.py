from packages.rag.visual import (
    OCRResult,
    _paddle_ocr_options,
    build_page_batches,
    extract_paddle_ocr_result,
    is_visual_filename,
    merge_visual_text,
    needs_vision_analysis,
    split_visual_sections,
)


def test_visual_file_detection_supports_images_and_pdf() -> None:
    for filename in ("scan.pdf", "photo.png", "photo.jpg", "photo.jpeg", "photo.webp"):
        assert is_visual_filename(filename)

    assert not is_visual_filename("notes.txt")
    assert not is_visual_filename("sheet.csv")


def test_page_batches_cover_every_page_four_at_a_time() -> None:
    assert build_page_batches(0) == []
    assert build_page_batches(1) == [(1, 1)]
    assert build_page_batches(10) == [(1, 4), (5, 8), (9, 10)]


def test_vision_is_used_for_sparse_low_confidence_or_complex_pages() -> None:
    assert needs_vision_analysis("", None, has_visuals=False)
    assert needs_vision_analysis("short text", 0.55, has_visuals=False)
    assert needs_vision_analysis("Readable text " * 20, 0.95, has_visuals=True)
    assert not needs_vision_analysis("Readable text " * 20, 0.95, has_visuals=False)


def test_ocr_and_vision_text_are_combined_without_empty_sections() -> None:
    assert merge_visual_text("Invoice total: 42", "") == "Invoice total: 42"
    assert merge_visual_text("", "A bar chart comparing two quarters.") == (
        "Visual description:\nA bar chart comparing two quarters."
    )
    assert merge_visual_text("Invoice total: 42", "A photographed invoice.") == (
        "Recognized text:\nInvoice total: 42\n\n"
        "Visual description:\nA photographed invoice."
    )


def test_visual_sections_keep_each_diagram_heading_with_its_flow() -> None:
    sections = split_visual_sections(
        "Схема 1. Проверка оплаты\nСхема 2. Первичное решение проблемы",
        """
## Анализ страницы

### Схема 1. Проверка оплаты
Ветка B2C проверяет технологию и оплату.

### Схема 2. Первичное решение проблемы
Если перезагрузка не помогла, проверяются индикаторы и кабель.
Если это не помогло, создаётся тикет.
""",
    )

    assert sections[0].startswith("Recognized text:")
    assert sections[1] == (
        "### Схема 1. Проверка оплаты\n"
        "Ветка B2C проверяет технологию и оплату."
    )
    assert sections[2] == (
        "### Схема 2. Первичное решение проблемы\n"
        "Если перезагрузка не помогла, проверяются индикаторы и кабель.\n"
        "Если это не помогло, создаётся тикет."
    )


def test_paddle_result_normalization_joins_text_and_averages_confidence() -> None:
    result = extract_paddle_ocr_result(
        [
            {
                "res": {
                    "rec_texts": ["Счёт", "Total 42"],
                    "rec_scores": [0.91, 0.81],
                }
            }
        ]
    )

    assert result == OCRResult(text="Счёт\nTotal 42", confidence=0.86)


def test_empty_paddle_result_has_no_confidence() -> None:
    assert extract_paddle_ocr_result([]) == OCRResult(text="", confidence=None)


def test_paddle_ocr_uses_onnx_models_on_arm64() -> None:
    assert _paddle_ocr_options("aarch64") == {
        "engine": "onnxruntime",
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }


def test_paddle_ocr_keeps_native_pipeline_on_x86() -> None:
    assert _paddle_ocr_options("x86_64") == {
        "use_doc_orientation_classify": True,
        "use_doc_unwarping": True,
        "use_textline_orientation": True,
    }
