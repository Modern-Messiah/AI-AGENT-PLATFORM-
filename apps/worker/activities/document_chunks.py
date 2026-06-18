from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from packages.rag import build_document_insights, chunk_segments, parse_to_segments
from packages.rag.parser import ParsedSegment
from packages.storage import Chunk, Document, object_store
from packages.storage.db import tenant_session
from sqlalchemy import update

from apps.worker.activities.ingestion_types import ChunkBatch, IngestionInput, ParsedDoc
from apps.worker.activities.url_visuals import append_url_visual_segments


async def parse_original_document(input: IngestionInput) -> ParsedDoc:
    data = object_store.get(input.object_key)
    segments = await parse_to_segments(data, input.filename)
    segments = await append_url_visual_segments(input, segments)
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
) -> ChunkBatch:
    segments = _to_parsed_segments(parsed)
    if not segments and parsed.text.strip():
        segments = [ParsedSegment(text=parsed.text)]
    chunks = chunk_segments(segments)
    if not chunks:
        raise ValueError("document contains no extractable text")
    contents = [chunk.content for chunk in chunks]
    embeddings = await embedder(contents)
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
    )


async def store_chunk_batch(input: IngestionInput, batch: ChunkBatch) -> int:
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
