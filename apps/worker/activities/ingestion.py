"""Ingestion activities: download → parse → chunk → embed → store.

Each is its own activity so Temporal can retry them independently and so
the workflow can fan out where useful (e.g. embed in batches).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from packages.cache.semantic import semantic_cache
from packages.core import settings
from packages.llm import complete_vision_text
from packages.rag import build_document_insights, chunk_segments, embed_texts, parse_to_segments
from packages.rag.parser import ParsedSegment
from packages.rag.summaries import DocumentInsights
from packages.rag.visual import (
    OCRResult,
    VisualPage,
    build_page_batches,
    is_visual_filename,
    merge_visual_text,
    needs_vision_analysis,
    render_visual_pages,
    run_paddle_ocr,
    split_visual_sections,
    visual_page_count,
)
from packages.storage import (
    Chunk,
    Document,
    DocumentAsset,
    DocumentAssetStatus,
    DocumentStatus,
    Notebook,
    NotebookDocument,
    object_store,
)
from packages.storage.db import tenant_session
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio import activity

log = logging.getLogger(__name__)


@dataclass
class IngestionInput:
    document_id: str
    tenant_id: str
    object_key: str
    filename: str


@dataclass
class ParsedDoc:
    # `text` remains for Temporal compatibility with already-produced activity results.
    segments: list[ParsedSegment] = field(default_factory=list)
    text: str = ""
    insights: DocumentInsights = field(default_factory=DocumentInsights)


@dataclass
class ChunkBatch:
    contents: list[str]
    embeddings: list[list[float]]
    metadata: list[dict] = field(default_factory=list)
    summary: str = ""
    suggested_questions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VisualBatchRef:
    object_key: str
    processed_pages: int
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VisualManifest:
    is_visual: bool
    total_pages: int = 0
    batches: list[tuple[int, int]] = field(default_factory=list)


@dataclass(frozen=True)
class VisualBatchInput:
    ingestion: IngestionInput
    start_page: int
    end_page: int


@dataclass(frozen=True)
class VisualPageAnalysis:
    text: str
    ocr_text: str
    ocr_confidence: float | None
    vision_description: str
    warning: str | None = None
    ocr_latency_ms: int = 0
    vision_latency_ms: int = 0


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


async def _await_with_heartbeat(
    awaitable: Awaitable[VisualPageAnalysis],
    *,
    details: dict[str, object],
    interval_seconds: float = 20.0,
) -> VisualPageAnalysis:
    task = asyncio.create_task(awaitable)
    while not task.done():
        activity.heartbeat(details)
        try:
            return await asyncio.wait_for(
                asyncio.shield(task),
                timeout=interval_seconds,
            )
        except TimeoutError:
            continue
    return await task


async def _upsert_document_asset(
    input: IngestionInput,
    page: VisualPage,
    *,
    preview_object_key: str,
    analysis: VisualPageAnalysis | None,
    status: DocumentAssetStatus,
    error: str | None = None,
) -> str:
    asset_kind = "page" if input.filename.lower().endswith(".pdf") else "image"
    values = {
        "tenant_id": input.tenant_id,
        "document_id": uuid.UUID(input.document_id),
        "page_number": page.page_number,
        "asset_kind": asset_kind,
        "preview_object_key": preview_object_key,
        "ocr_text": analysis.ocr_text if analysis else "",
        "ocr_confidence": analysis.ocr_confidence if analysis else None,
        "vision_description": analysis.vision_description if analysis else "",
        "width": page.width,
        "height": page.height,
        "status": status,
        "error": error,
    }
    statement = pg_insert(DocumentAsset).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=[
            DocumentAsset.document_id,
            DocumentAsset.page_number,
            DocumentAsset.asset_kind,
        ],
        set_={
            key: getattr(statement.excluded, key)
            for key in values
            if key not in {"tenant_id", "document_id", "page_number", "asset_kind"}
        },
    ).returning(DocumentAsset.id)
    async with tenant_session(input.tenant_id) as session:
        result = await session.execute(statement)
        return str(result.scalar_one())


async def _update_visual_progress(input: IngestionInput) -> None:
    document_id = uuid.UUID(input.document_id)
    async with tenant_session(input.tenant_id) as session:
        processed = (
            await session.execute(
                select(func.count(DocumentAsset.id)).where(
                    DocumentAsset.document_id == document_id,
                    DocumentAsset.tenant_id == input.tenant_id,
                )
            )
        ).scalar_one()
        await session.execute(
            update(Document)
            .where(
                Document.id == document_id,
                Document.tenant_id == input.tenant_id,
            )
            .values(
                processing_stage="ocr",
                processed_pages=func.greatest(Document.processed_pages, processed),
            )
        )


@activity.defn
async def mark_processing(input: IngestionInput) -> None:
    async with tenant_session(input.tenant_id) as s:
        await s.execute(
            update(Document)
            .where(
                Document.id == uuid.UUID(input.document_id),
                Document.tenant_id == input.tenant_id,
            )
            .values(
                status=DocumentStatus.processing,
                processing_stage="preparing",
                error=None,
            )
        )


@activity.defn
async def prepare_visual_document(input: IngestionInput) -> VisualManifest:
    if not is_visual_filename(input.filename):
        return VisualManifest(is_visual=False)

    data = await asyncio.to_thread(object_store.get, input.object_key)
    total_pages = await asyncio.to_thread(visual_page_count, data, input.filename)
    if total_pages <= 0:
        raise ValueError("visual document contains no pages")

    document_id = uuid.UUID(input.document_id)
    async with tenant_session(input.tenant_id) as session:
        previous_assets = (
            await session.execute(
                select(DocumentAsset).where(
                    DocumentAsset.document_id == document_id,
                    DocumentAsset.tenant_id == input.tenant_id,
                )
            )
        ).scalars().all()
        await session.execute(
            delete(DocumentAsset).where(
                DocumentAsset.document_id == document_id,
                DocumentAsset.tenant_id == input.tenant_id,
            )
        )
        await session.execute(
            delete(Chunk).where(
                Chunk.document_id == document_id,
                Chunk.tenant_id == input.tenant_id,
            )
        )
        await session.execute(
            update(Document)
            .where(
                Document.id == document_id,
                Document.tenant_id == input.tenant_id,
            )
            .values(
                processing_stage="rendering",
                processed_pages=0,
                total_pages=total_pages,
                warnings=[],
                summary=None,
                suggested_questions=[],
            )
        )

    for asset in previous_assets:
        try:
            await asyncio.to_thread(object_store.delete, asset.preview_object_key)
        except Exception as exc:  # noqa: BLE001
            log.warning("stale asset cleanup failed | key=%s error=%s", asset.preview_object_key, exc)

    return VisualManifest(
        is_visual=True,
        total_pages=total_pages,
        batches=build_page_batches(total_pages),
    )


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
        activity.heartbeat(
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
        activity.heartbeat(
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
    data = object_store.get(input.object_key)
    segments = await parse_to_segments(data, input.filename)
    insights = build_document_insights(segments, filename=input.filename)
    return ParsedDoc(segments=segments, insights=insights)


@activity.defn
async def chunk_and_embed(parsed: ParsedDoc) -> ChunkBatch:
    segments = parsed.segments
    if not segments and parsed.text.strip():
        segments = [ParsedSegment(text=parsed.text)]
    chunks = chunk_segments(segments)
    if not chunks:
        raise ValueError("document contains no extractable text")
    contents = [chunk.content for chunk in chunks]
    embeddings = await embed_texts(contents)
    return ChunkBatch(
        contents=contents,
        embeddings=embeddings,
        metadata=[
            {
                **chunk.metadata,
                "embedding_model": settings.embedding_model,
            }
            for chunk in chunks
        ],
        summary=parsed.insights.summary,
        suggested_questions=parsed.insights.suggested_questions,
    )


@activity.defn
async def store_chunks(input: IngestionInput, batch: ChunkBatch) -> int:
    document_id = uuid.UUID(input.document_id)
    async with tenant_session(input.tenant_id) as s:
        # Idempotency: drop any existing chunks for this document before re-insert.
        # On retry we re-embed but never duplicate rows.
        await s.execute(
            Chunk.__table__.delete().where(
                Chunk.document_id == document_id,
                Chunk.tenant_id == input.tenant_id,
            )
        )
        await s.execute(
            update(Document)
            .where(
                Document.id == document_id,
                Document.tenant_id == input.tenant_id,
            )
            .values(
                summary=batch.summary or None,
                suggested_questions=batch.suggested_questions,
            )
        )
        s.add_all(
            [
                Chunk(
                    document_id=document_id,
                    tenant_id=input.tenant_id,
                    chunk_idx=i,
                    content=content,
                    embedding=embedding,
                    chunk_metadata={
                        "filename": input.filename,
                        **(batch.metadata[i] if i < len(batch.metadata) else {}),
                    },
                )
                for i, (content, embedding) in enumerate(
                    zip(batch.contents, batch.embeddings, strict=True)
                )
            ]
        )
    return len(batch.contents)


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

    async with tenant_session(input.tenant_id) as session:
        await session.execute(
            update(Document)
            .where(
                Document.id == uuid.UUID(input.document_id),
                Document.tenant_id == input.tenant_id,
            )
            .values(
                processing_stage="embedding",
                warnings=list(dict.fromkeys(warnings)),
            )
        )

    insights = build_document_insights(segments, filename=input.filename)
    batch = await chunk_and_embed(ParsedDoc(segments=segments, insights=insights))
    written = await store_chunks(input, batch)

    for reference in batches:
        try:
            await asyncio.to_thread(object_store.delete, reference.object_key)
        except Exception as exc:  # noqa: BLE001
            log.warning("visual batch cleanup failed | key=%s error=%s", reference.object_key, exc)
    return written


async def _invalidate_notebook_insights_for_document(
    session: AsyncSession,
    *,
    tenant_id: str,
    document_id: uuid.UUID,
) -> int:
    notebooks = (
        await session.execute(
            select(Notebook)
            .join(NotebookDocument, NotebookDocument.notebook_id == Notebook.id)
            .where(
                Notebook.tenant_id == tenant_id,
                NotebookDocument.tenant_id == tenant_id,
                NotebookDocument.document_id == document_id,
            )
            .order_by(Notebook.created_at)
        )
    ).scalars().all()
    if not notebooks:
        return 0

    for notebook in notebooks:
        notebook.summary = None
        notebook.suggested_questions = []
        notebook.key_topics = []
        notebook.insights_updated_at = None
    return len(notebooks)


@activity.defn
async def mark_done(input: IngestionInput) -> None:
    document_id = uuid.UUID(input.document_id)
    async with tenant_session(input.tenant_id) as s:
        await s.execute(
            update(Document)
            .where(
                Document.id == document_id,
                Document.tenant_id == input.tenant_id,
            )
            .values(
                status=DocumentStatus.done,
                processing_stage="done",
                processed_pages=Document.total_pages,
            )
        )

    try:
        async with tenant_session(input.tenant_id) as s:
            await _invalidate_notebook_insights_for_document(
                s,
                tenant_id=input.tenant_id,
                document_id=document_id,
            )
    except Exception as exc:
        log.warning(
            "notebook insights refresh failed | tenant=%s document=%s error=%s",
            input.tenant_id,
            input.document_id,
            exc,
        )

    try:
        await semantic_cache.clear(input.tenant_id)
    except Exception as exc:
        log.warning(
            "semantic cache invalidation failed | tenant=%s document=%s error=%s",
            input.tenant_id,
            input.document_id,
            exc,
        )


@activity.defn
async def mark_failed(input: IngestionInput, error: str) -> None:
    async with tenant_session(input.tenant_id) as s:
        await s.execute(
            update(Document)
            .where(
                Document.id == uuid.UUID(input.document_id),
                Document.tenant_id == input.tenant_id,
            )
            .values(
                status=DocumentStatus.failed,
                processing_stage="failed",
                error=error[:2000],
            )
        )
