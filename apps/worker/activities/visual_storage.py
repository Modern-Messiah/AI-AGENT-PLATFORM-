from __future__ import annotations

import asyncio
import logging
import uuid

from packages.rag.visual import VisualPage, build_page_batches, is_visual_filename, visual_page_count
from packages.storage import Chunk, Document, DocumentAsset, DocumentAssetStatus, object_store
from packages.storage.db import tenant_session
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from apps.worker.activities.ingestion_types import (
    IngestionInput,
    VisualManifest,
    VisualPageAnalysis,
)

log = logging.getLogger(__name__)


async def upsert_document_asset(
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


async def update_visual_progress(input: IngestionInput) -> None:
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


async def prepare_visual_manifest(input: IngestionInput) -> VisualManifest:
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
