from __future__ import annotations

import logging
import uuid

from packages.cache.semantic import semantic_cache
from packages.storage import Document, DocumentStatus, Notebook, NotebookDocument
from packages.storage.db import tenant_session
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.worker.activities.ingestion_types import IngestionInput

log = logging.getLogger(__name__)


async def mark_document_processing(input: IngestionInput) -> None:
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


async def mark_visual_document_embedding(
    input: IngestionInput,
    warnings: list[str],
) -> None:
    async with tenant_session(input.tenant_id) as s:
        await s.execute(
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


async def invalidate_notebook_insights_for_document(
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


async def mark_document_done(input: IngestionInput) -> None:
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
            await invalidate_notebook_insights_for_document(
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


async def mark_document_failed(input: IngestionInput, error: str) -> None:
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
