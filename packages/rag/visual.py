"""Pure helpers shared by visual document ingestion activities."""

from __future__ import annotations

import json
import platform
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz  # type: ignore[import-untyped]
from PIL import Image, ImageOps

from packages.core import settings

_VISUAL_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
_BATCH_SIZE = 4
_MIN_USEFUL_TEXT_CHARS = 80
_MIN_OCR_CONFIDENCE = 0.72
_OCR_LOCK = threading.Lock()
_VISUAL_SECTION_HEADING = re.compile(r"(?m)^(#{2,4}\s+.+)$")
_MEANINGFUL_VISUAL_HEADING = re.compile(
    r"(schema|diagram|flow|table|chart|схем|диаграм|таблиц|граф)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OCRResult:
    text: str
    confidence: float | None


@dataclass(frozen=True)
class VisualPage:
    page_number: int
    preview_bytes: bytes
    width: int
    height: int
    text_layer: str
    has_visuals: bool


def is_visual_filename(filename: str) -> bool:
    return Path(filename).suffix.lower() in _VISUAL_SUFFIXES


def build_page_batches(total_pages: int, batch_size: int = _BATCH_SIZE) -> list[tuple[int, int]]:
    if total_pages <= 0:
        return []
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    return [
        (start, min(start + batch_size - 1, total_pages))
        for start in range(1, total_pages + 1, batch_size)
    ]


def needs_vision_analysis(
    text: str,
    confidence: float | None,
    *,
    has_visuals: bool,
) -> bool:
    normalized = " ".join(text.split())
    if len(normalized) < _MIN_USEFUL_TEXT_CHARS:
        return True
    if confidence is not None and confidence < _MIN_OCR_CONFIDENCE:
        return True
    return has_visuals


def merge_visual_text(ocr_text: str, vision_description: str) -> str:
    ocr_text = ocr_text.strip()
    vision_description = vision_description.strip()
    if ocr_text and vision_description:
        return (
            f"Recognized text:\n{ocr_text}\n\n"
            f"Visual description:\n{vision_description}"
        )
    if ocr_text:
        return ocr_text
    if vision_description:
        return f"Visual description:\n{vision_description}"
    return ""


def split_visual_sections(ocr_text: str, vision_description: str) -> list[str]:
    """Keep OCR and each meaningful diagram/table section independently searchable."""
    sections: list[str] = []
    ocr_text = ocr_text.strip()
    vision_description = vision_description.strip()
    if ocr_text:
        sections.append(f"Recognized text:\n{ocr_text}")
    if not vision_description:
        return sections

    matches = list(_VISUAL_SECTION_HEADING.finditer(vision_description))
    visual_sections: list[str] = []
    for index, match in enumerate(matches):
        heading = match.group(1)
        if not _MEANINGFUL_VISUAL_HEADING.search(heading):
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(
            vision_description
        )
        block = vision_description[match.start() : end].strip()
        if block:
            visual_sections.append(block)

    if visual_sections:
        sections.extend(visual_sections)
    else:
        sections.append(f"Visual description:\n{vision_description}")
    return sections
def _paddle_payload(item: object) -> dict[str, Any]:
    if isinstance(item, dict):
        payload = item
    else:
        payload = getattr(item, "json", {})
        if callable(payload):
            payload = payload()
        if isinstance(payload, str):
            payload = json.loads(payload)
    if not isinstance(payload, dict):
        return {}
    result = payload.get("res", payload)
    return result if isinstance(result, dict) else {}


def extract_paddle_ocr_result(results: list[object]) -> OCRResult:
    texts: list[str] = []
    scores: list[float] = []
    for item in results:
        payload = _paddle_payload(item)
        raw_texts = payload.get("rec_texts", [])
        raw_scores = payload.get("rec_scores", [])
        if isinstance(raw_texts, list):
            texts.extend(str(text).strip() for text in raw_texts if str(text).strip())
        if isinstance(raw_scores, list):
            scores.extend(float(score) for score in raw_scores)
    confidence = round(sum(scores) / len(scores), 4) if scores else None
    return OCRResult(text="\n".join(texts), confidence=confidence)


def _paddle_ocr_options(machine: str | None = None) -> dict[str, object]:
    architecture = (machine or platform.machine()).lower()
    if architecture in {"aarch64", "arm64"}:
        # Native Paddle inference crashes in Linux ARM64 containers. PaddleOCR
        # publishes equivalent ONNX models that run through ONNX Runtime.
        return {
            "engine": "onnxruntime",
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
        }
    return {
        "use_doc_orientation_classify": True,
        "use_doc_unwarping": True,
        "use_textline_orientation": True,
    }


@lru_cache(maxsize=1)
def _paddle_ocr():
    from paddleocr import PaddleOCR

    return PaddleOCR(
        lang=settings.ocr_language,
        **_paddle_ocr_options(),
    )


def run_paddle_ocr(image_bytes: bytes) -> OCRResult:
    import numpy as np

    with Image.open(BytesIO(image_bytes)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        with _OCR_LOCK:
            results = list(_paddle_ocr().predict(input=np.asarray(image)))
    return extract_paddle_ocr_result(results)


def visual_page_count(data: bytes, filename: str) -> int:
    if Path(filename).suffix.lower() != ".pdf":
        return 1
    with fitz.open(stream=data, filetype="pdf") as document:
        return len(document)


def _fit_within(width: int, height: int, max_dimension: int) -> tuple[int, int]:
    largest = max(width, height)
    if largest <= max_dimension:
        return width, height
    scale = max_dimension / largest
    return max(1, round(width * scale)), max(1, round(height * scale))


def _webp_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="WEBP", quality=82, method=4)
    return output.getvalue()


def render_visual_pages(
    data: bytes,
    filename: str,
    start_page: int,
    end_page: int,
) -> list[VisualPage]:
    suffix = Path(filename).suffix.lower()
    max_dimension = settings.visual_render_max_dimension
    if suffix != ".pdf":
        if start_page != 1 or end_page != 1:
            return []
        with Image.open(BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            return [
                VisualPage(
                    page_number=1,
                    preview_bytes=_webp_bytes(image),
                    width=image.width,
                    height=image.height,
                    text_layer="",
                    has_visuals=True,
                )
            ]

    pages: list[VisualPage] = []
    with fitz.open(stream=data, filetype="pdf") as document:
        for page_number in range(start_page, min(end_page, len(document)) + 1):
            page = document[page_number - 1]
            rect = page.rect
            target_width, target_height = _fit_within(
                round(rect.width * 2),
                round(rect.height * 2),
                max_dimension,
            )
            matrix = fitz.Matrix(
                target_width / rect.width,
                target_height / rect.height,
            )
            pixmap = page.get_pixmap(matrix=matrix, alpha=False, colorspace=fitz.csRGB)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            pages.append(
                VisualPage(
                    page_number=page_number,
                    preview_bytes=_webp_bytes(image),
                    width=image.width,
                    height=image.height,
                    text_layer=page.get_text("text").strip(),
                    has_visuals=bool(page.get_images(full=True) or page.get_drawings()),
                )
            )
    return pages
