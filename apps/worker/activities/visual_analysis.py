from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from packages.llm import complete_vision_text
from packages.rag.visual import (
    OCRResult,
    VisualPage,
    merge_visual_text,
    needs_vision_analysis,
    run_paddle_ocr,
)
from apps.worker.activities.heartbeat import heartbeat_safe
from apps.worker.activities.ingestion_types import VisualPageAnalysis


async def analyze_visual_page(
    page: VisualPage,
    *,
    ocr_reader: Callable[[bytes], OCRResult] = run_paddle_ocr,
    vision_reader: Callable[..., Awaitable[str]] = complete_vision_text,
) -> VisualPageAnalysis:
    text_layer = page.text_layer.strip()
    ocr_latency_ms = 0
    if len(" ".join(text_layer.split())) >= 80:
        ocr = OCRResult(text=text_layer, confidence=1.0)
    else:
        ocr_started = time.monotonic()
        ocr = await asyncio.to_thread(ocr_reader, page.preview_bytes)
        ocr_latency_ms = int((time.monotonic() - ocr_started) * 1000)
        if not ocr.text and text_layer:
            ocr = OCRResult(text=text_layer, confidence=ocr.confidence)

    vision_description = ""
    vision_latency_ms = 0
    if needs_vision_analysis(
        ocr.text,
        ocr.confidence,
        has_visuals=page.has_visuals,
    ):
        vision_started = time.monotonic()
        try:
            vision_description = await vision_reader(
                page.preview_bytes,
                "image/webp",
                prompt=(
                    f"Analyze page {page.page_number} of a knowledge-base document. "
                    "Extract diagram and table semantics that OCR cannot preserve. "
                    "For diagrams, describe nodes, conditions, directed transitions, and loops "
                    "in execution order. For tables, preserve headers and row relationships. "
                    "Use the same language as the page. Be factual and concise. "
                    "Describe only visual content that is actually visible on this page. "
                    "Do not reconstruct or infer diagrams that are only mentioned in text. "
                    "Do not describe colors, typography, spacing, or decoration unless they "
                    "change the meaning."
                ),
            )
        except Exception as exc:  # noqa: BLE001
            vision_latency_ms = int((time.monotonic() - vision_started) * 1000)
            return VisualPageAnalysis(
                text=ocr.text.strip(),
                ocr_text=ocr.text,
                ocr_confidence=ocr.confidence,
                vision_description="",
                warning=f"page {page.page_number}: vision analysis failed: {exc}",
                ocr_latency_ms=ocr_latency_ms,
                vision_latency_ms=vision_latency_ms,
            )
        vision_latency_ms = int((time.monotonic() - vision_started) * 1000)

    return VisualPageAnalysis(
        text=merge_visual_text(ocr.text, vision_description),
        ocr_text=ocr.text,
        ocr_confidence=ocr.confidence,
        vision_description=vision_description,
        ocr_latency_ms=ocr_latency_ms,
        vision_latency_ms=vision_latency_ms,
    )


async def await_with_heartbeat(
    awaitable: Awaitable[VisualPageAnalysis],
    *,
    details: dict[str, object],
    interval_seconds: float = 20.0,
) -> VisualPageAnalysis:
    task = asyncio.create_task(awaitable)
    while not task.done():
        heartbeat_safe(details)
        try:
            return await asyncio.wait_for(
                asyncio.shield(task),
                timeout=interval_seconds,
            )
        except TimeoutError:
            continue
    return await task
