"""Ingestion activities: download → parse → chunk → embed → store.

Each step is available as an activity. Text ingestion combines parse, chunk, embed,
and store into ingest_text_document to keep Temporal histories small, while individual
activities remain available for visual workflows and history replay.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from packages.core import settings
from packages.rag import build_document_insights, embed_texts
from packages.rag.parser import ParsedSegment
from packages.rag.visual import (
    render_visual_pages,
    split_visual_sections,
)
from packages.storage import (
    DocumentAssetStatus,
    object_store,
)
from temporalio import activity

from apps.worker.activities.heartbeat import heartbeat_safe
from apps.worker.activities.ingestion_types import (
    ChunkBatch,
    IngestionInput,
    ParsedDoc,
    VisualBatchInput,
    VisualBatchRef,
    VisualManifest,
    VisualPageAnalysis,
)
from apps.worker.activities.ingestion_status import (
    invalidate_notebook_insights_for_document,
    mark_document_done,
    mark_document_failed,
    mark_document_processing,
    mark_visual_document_embedding,
)
from apps.worker.activities.document_chunks import (
    build_chunk_batch,
    parse_original_document,
    store_chunk_batch,
)
from apps.worker.activities.visual_analysis import (
    analyze_visual_page,
    await_with_heartbeat as _await_with_heartbeat,
)
from apps.worker.activities.visual_storage import (
    prepare_visual_manifest,
    update_visual_progress,
    upsert_document_asset,
)

log = logging.getLogger(__name__)


_upsert_document_asset = upsert_document_asset
_update_visual_progress = update_visual_progress
_invalidate_notebook_insights_for_document = invalidate_notebook_insights_for_document


@activity.defn
async def mark_processing(input: IngestionInput) -> None:
    await mark_document_processing(input)


@activity.defn
async def prepare_visual_document(input: IngestionInput) -> VisualManifest:
    return await prepare_visual_manifest(input)


@activity.defn
async def process_visual_batch(batch: VisualBatchInput) -> VisualBatchRef:
    input = batch.ingestion
    started = time.monotonic()
    data = await asyncio.to_thread(object_store.get, input.object_key)
    pages = await asyncio.to_thread(
        render_visual_pages,
        data,
        input.filename,
        batch.start_page,
        batch.end_page,
    )
    warnings: list[str] = []
    segments: list[dict[str, object]] = []
    vision_calls = 0
    unrecognized_pages = 0
    ocr_latency_ms = 0
    vision_latency_ms = 0

    for page in pages:
        heartbeat_safe(
            {
                "document_id": input.document_id,
                "page": page.page_number,
                "total_pages": batch.end_page,
            }
        )
        asset_kind = "page" if input.filename.lower().endswith(".pdf") else "image"
        preview_key = (
            f"{input.tenant_id}/{input.document_id}/assets/"
            f"{asset_kind}-{page.page_number}.webp"
        )
        await asyncio.to_thread(
            object_store.put,
            preview_key,
            page.preview_bytes,
            "image/webp",
        )

        analysis: VisualPageAnalysis | None = None
        try:
            analysis = await _await_with_heartbeat(
                analyze_visual_page(page),
                details={
                    "document_id": input.document_id,
                    "page": page.page_number,
                    "stage": "ocr-vision",
                },
            )
            if analysis.vision_description or analysis.warning:
                vision_calls += 1
            ocr_latency_ms += analysis.ocr_latency_ms
            vision_latency_ms += analysis.vision_latency_ms
            if analysis.warning:
                warnings.append(analysis.warning)
            if not analysis.text.strip():
                raise ValueError("no text or visual description extracted")
            asset_id = await _upsert_document_asset(
                input,
                page,
                preview_object_key=preview_key,
                analysis=analysis,
                status=DocumentAssetStatus.done,
            )
            metadata = {
                "page": page.page_number,
                "asset_id": asset_id,
                "asset_kind": asset_kind,
                "preview_available": True,
            }
            page_segments = split_visual_sections(
                analysis.ocr_text,
                analysis.vision_description,
            )
            segments.extend(
                {"text": text, "metadata": metadata}
                for text in page_segments
                if text.strip()
            )
        except Exception as exc:  # noqa: BLE001
            if analysis is None or not analysis.text.strip():
                unrecognized_pages += 1
            warning = f"page {page.page_number}: {exc}"
            warnings.append(warning)
            await _upsert_document_asset(
                input,
                page,
                preview_object_key=preview_key,
                analysis=None,
                status=DocumentAssetStatus.failed,
                error=str(exc)[:2000],
            )
        await _update_visual_progress(input)
        heartbeat_safe(
            {
                "document_id": input.document_id,
                "page": page.page_number,
                "stage": "page-complete",
            }
        )

    batch_key = (
        f"{input.tenant_id}/{input.document_id}/visual-batches/"
        f"{batch.start_page}-{batch.end_page}.json"
    )
    payload = json.dumps(
        {"segments": segments, "warnings": warnings},
        ensure_ascii=False,
    ).encode("utf-8")
    await asyncio.to_thread(
        object_store.put,
        batch_key,
        payload,
        "application/json",
    )
    log.info(
        "visual batch processed | tenant=%s document=%s pages=%s-%s "
        "ocr_latency_ms=%s vision_calls=%s vision_latency_ms=%s "
        "unrecognized_pages=%s warnings=%s latency_ms=%s",
        input.tenant_id,
        input.document_id,
        batch.start_page,
        batch.end_page,
        ocr_latency_ms,
        vision_calls,
        vision_latency_ms,
        unrecognized_pages,
        len(warnings),
        int((time.monotonic() - started) * 1000),
    )
    return VisualBatchRef(
        object_key=batch_key,
        processed_pages=len(pages),
        warnings=warnings,
    )


@activity.defn
async def parse_document(input: IngestionInput) -> ParsedDoc:
    return await parse_original_document(input)


@activity.defn
async def chunk_and_embed(parsed: ParsedDoc) -> ChunkBatch:
    return await build_chunk_batch(
        parsed,
        embedding_model=settings.embedding_model,
        embedder=embed_texts,
    )


@activity.defn
async def ingest_text_document(input: IngestionInput) -> int:
    heartbeat_safe({"document_id": input.document_id, "stage": "parse-start"})
    parsed = await parse_original_document(input)
    heartbeat_safe({"document_id": input.document_id, "stage": "parse-complete"})
    batch = await build_chunk_batch(
        parsed,
        embedding_model=settings.embedding_model,
        embedder=embed_texts,
        document_id=input.document_id,
    )
    heartbeat_safe({"document_id": input.document_id, "stage": "embed-complete"})
    written = await store_chunk_batch(input, batch)
    heartbeat_safe({"document_id": input.document_id, "stage": "store-complete"})
    return written


@activity.defn
async def store_chunks(input: IngestionInput, batch: ChunkBatch) -> int:
    return await store_chunk_batch(input, batch)


@activity.defn
async def finalize_visual_document(
    input: IngestionInput,
    batches: list[VisualBatchRef],
) -> int:
    segments: list[ParsedSegment] = []
    warnings: list[str] = []
    for batch in batches:
        payload = json.loads(
            (await asyncio.to_thread(object_store.get, batch.object_key)).decode("utf-8")
        )
        warnings.extend(str(item) for item in payload.get("warnings", []))
        for item in payload.get("segments", []):
            text = str(item.get("text", "")).strip()
            metadata = item.get("metadata", {})
            if text and isinstance(metadata, dict):
                segments.append(ParsedSegment(text=text, metadata=metadata))

    if not segments:
        raise ValueError("visual document contains no extractable content")

    await mark_visual_document_embedding(input, warnings)

    insights = build_document_insights(segments, filename=input.filename)
    batch = await build_chunk_batch(
        ParsedDoc(
            segments=[
                {
                    "text": segment.text,
                    "metadata": segment.metadata,
                }
                for segment in segments
            ],
            summary=insights.summary,
            suggested_questions=insights.suggested_questions,
            warnings=warnings,
        ),
        embedding_model=settings.embedding_model,
        embedder=embed_texts,
        document_id=input.document_id,
    )
    written = await store_chunks(input, batch)

    for reference in batches:
        try:
            await asyncio.to_thread(object_store.delete, reference.object_key)
        except Exception as exc:  # noqa: BLE001
            log.warning("visual batch cleanup failed | key=%s error=%s", reference.object_key, exc)
    return written


@activity.defn
async def mark_done(input: IngestionInput) -> None:
    await mark_document_done(input)


@activity.defn
async def mark_failed(input: IngestionInput, error: str) -> None:
    await mark_document_failed(input, error)
