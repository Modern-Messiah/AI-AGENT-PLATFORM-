"""Ingestion activities: download → parse → chunk → embed → store.

Each is its own activity so Temporal can retry them independently and so
the workflow can fan out where useful (e.g. embed in batches).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from packages.cache.semantic import semantic_cache
from packages.rag import build_document_insights, chunk_segments, embed_texts, parse_to_segments
from packages.rag.parser import ParsedSegment
from packages.rag.summaries import (
    DocumentInsights,
    NotebookInsightSource,
    build_notebook_insights,
)
from packages.storage import (
    Chunk,
    Document,
    DocumentStatus,
    Notebook,
    NotebookDocument,
    object_store,
)
from packages.storage.db import tenant_session
from sqlalchemy import select, update
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
    metadata: list[dict[str, object]] = field(default_factory=list)
    summary: str = ""
    suggested_questions: list[str] = field(default_factory=list)


@activity.defn
async def mark_processing(input: IngestionInput) -> None:
    async with tenant_session(input.tenant_id) as s:
        await s.execute(
            update(Document)
            .where(Document.id == uuid.UUID(input.document_id))
            .values(status=DocumentStatus.processing, error=None)
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
        metadata=[chunk.metadata for chunk in chunks],
        summary=parsed.insights.summary,
        suggested_questions=parsed.insights.suggested_questions,
    )


@activity.defn
async def store_chunks(input: IngestionInput, batch: ChunkBatch) -> int:
    document_id = uuid.UUID(input.document_id)
    async with tenant_session(input.tenant_id) as s:
        # Idempotency: drop any existing chunks for this document before re-insert.
        # On retry we re-embed but never duplicate rows.
        await s.execute(Chunk.__table__.delete().where(Chunk.document_id == document_id))
        await s.execute(
            update(Document)
            .where(Document.id == document_id)
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


async def _refresh_notebook_insights_for_document(
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

    refreshed = 0
    now = datetime.now(timezone.utc)
    for notebook in notebooks:
        ready_documents = (
            await session.execute(
                select(Document)
                .join(NotebookDocument, NotebookDocument.document_id == Document.id)
                .where(
                    Document.tenant_id == tenant_id,
                    Document.status == DocumentStatus.done,
                    NotebookDocument.tenant_id == tenant_id,
                    NotebookDocument.notebook_id == notebook.id,
                )
                .order_by(NotebookDocument.created_at, Document.created_at.desc())
            )
        ).scalars().all()
        insights = build_notebook_insights(
            [
                NotebookInsightSource(
                    filename=doc.filename,
                    summary=doc.summary or "",
                    suggested_questions=doc.suggested_questions or [],
                )
                for doc in ready_documents
            ],
            title=notebook.title,
        )
        if not insights.summary:
            notebook.summary = None
            notebook.suggested_questions = []
            notebook.key_topics = []
            notebook.insights_updated_at = None
            continue

        notebook.summary = insights.summary
        notebook.suggested_questions = insights.suggested_questions
        notebook.key_topics = insights.key_topics
        notebook.insights_updated_at = now
        notebook.updated_at = now
        refreshed += 1
    return refreshed


@activity.defn
async def mark_done(input: IngestionInput) -> None:
    document_id = uuid.UUID(input.document_id)
    async with tenant_session(input.tenant_id) as s:
        await s.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(status=DocumentStatus.done)
        )

    try:
        async with tenant_session(input.tenant_id) as s:
            await _refresh_notebook_insights_for_document(
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
            .where(Document.id == uuid.UUID(input.document_id))
            .values(status=DocumentStatus.failed, error=error[:2000])
        )
