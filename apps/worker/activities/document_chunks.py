from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable

from packages.core import settings
from packages.rag import build_document_insights, chunk_segments, parse_to_segments
from packages.rag.parser import ParsedSegment
from packages.storage import Chunk, Document, object_store
from packages.storage.db import tenant_session
from sqlalchemy import update

from apps.worker.activities.heartbeat import heartbeat_safe
from apps.worker.activities.ingestion_types import ChunkBatch, IngestionInput, ParsedDoc
from apps.worker.activities.url_visuals import append_url_visual_segments


async def parse_original_document(input: IngestionInput) -> ParsedDoc:
    data = await asyncio.to_thread(object_store.get, input.object_key)
    segments = await parse_to_segments(data, input.filename)
    url_visuals = await append_url_visual_segments(input, segments)
    segments = url_visuals.segments
    insights = build_document_insights(segments, filename=input.filename)
    return ParsedDoc(
        segments=[
            {
                "text": segment.text,
                "metadata": segment.metadata,
            }
            for segment in segments
        ],
        summary=insights.summary,
        suggested_questions=insights.suggested_questions,
        warnings=url_visuals.warnings,
    )


def _to_parsed_segments(parsed: ParsedDoc) -> list[ParsedSegment]:
    segments: list[ParsedSegment] = []
    for item in parsed.segments:
        if isinstance(item, ParsedSegment):
            segments.append(item)
            continue
        text = str(item.get("text", "")).strip()
        metadata = item.get("metadata", {})
        if text:
            segments.append(ParsedSegment(
                text=text,
                metadata=metadata if isinstance(metadata, dict) else {},
            ))
    return segments


async def build_chunk_batch(
    parsed: ParsedDoc,
    *,
    embedding_model: str,
    embedder: Callable[[list[str]], Awaitable[list[list[float]]]],
    batch_size: int | None = None,
    document_id: str | None = None,
) -> ChunkBatch:
    effective_batch_size = (
        batch_size if batch_size is not None else settings.embedding_batch_size
    )
    if effective_batch_size <= 0:
        raise ValueError("batch_size must be positive")

    segments = _to_parsed_segments(parsed)
    if not segments and parsed.text.strip():
        segments = [ParsedSegment(text=parsed.text)]
    chunks = chunk_segments(segments)
    if not chunks:
        raise ValueError("document contains no extractable text")
    contents = [chunk.content for chunk in chunks]

    start_details: dict[str, object] = {
        "stage": "embedding-start",
        "total_chunks": len(contents),
    }
    if document_id:
        start_details["document_id"] = document_id
    heartbeat_safe(start_details)

    embeddings: list[list[float]] = []
    for i in range(0, len(contents), effective_batch_size):
        batch_contents = contents[i : i + effective_batch_size]
        batch_embeddings = await embedder(batch_contents)
        embeddings.extend(batch_embeddings)
        embed_details: dict[str, object] = {
            "stage": "embedding",
            "embedded_chunks": len(embeddings),
            "total_chunks": len(contents),
        }
        if document_id:
            embed_details["document_id"] = document_id
        heartbeat_safe(embed_details)

    return ChunkBatch(
        contents=contents,
        embeddings=embeddings,
        metadata=[
            {
                **chunk.metadata,
                "embedding_model": embedding_model,
            }
            for chunk in chunks
        ],
        summary=parsed.summary,
        suggested_questions=parsed.suggested_questions,
        warnings=parsed.warnings,
    )


async def store_chunk_batch(input: IngestionInput, batch: ChunkBatch) -> int:
    document_id = uuid.UUID(input.document_id)
    heartbeat_safe({
        "document_id": input.document_id,
        "stage": "store-start",
        "total_chunks": len(batch.contents),
    })
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
                warnings=batch.warnings,
            )
        )
        chunk_rows = [
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
        store_batch_size = 200
        for i in range(0, len(chunk_rows), store_batch_size):
            s.add_all(chunk_rows[i : i + store_batch_size])
            await s.flush()
            heartbeat_safe({
                "document_id": input.document_id,
                "stage": "storing-chunks",
                "stored_chunks": min(i + store_batch_size, len(chunk_rows)),
                "total_chunks": len(chunk_rows),
            })
    return len(batch.contents)
