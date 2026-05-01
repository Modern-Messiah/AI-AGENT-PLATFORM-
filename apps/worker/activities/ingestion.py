"""Ingestion activities: download → parse → chunk → embed → store.

Each is its own activity so Temporal can retry them independently and so
the workflow can fan out where useful (e.g. embed in batches).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import update
from temporalio import activity

from packages.rag import chunk_text, embed_texts, parse_to_text
from packages.storage import Chunk, Document, DocumentStatus, object_store
from packages.storage.db import tenant_session


@dataclass
class IngestionInput:
    document_id: str
    tenant_id: str
    object_key: str
    filename: str


@dataclass
class ParsedDoc:
    text: str


@dataclass
class ChunkBatch:
    contents: list[str]
    embeddings: list[list[float]]


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
    text = await parse_to_text(data, input.filename)
    return ParsedDoc(text=text)


@activity.defn
async def chunk_and_embed(parsed: ParsedDoc) -> ChunkBatch:
    contents = chunk_text(parsed.text)
    if not contents:
        raise ValueError("document contains no extractable text")
    embeddings = await embed_texts(contents)
    return ChunkBatch(contents=contents, embeddings=embeddings)


@activity.defn
async def store_chunks(input: IngestionInput, batch: ChunkBatch) -> int:
    document_id = uuid.UUID(input.document_id)
    async with tenant_session(input.tenant_id) as s:
        # Idempotency: drop any existing chunks for this document before re-insert.
        # On retry we re-embed but never duplicate rows.
        await s.execute(
            Chunk.__table__.delete().where(Chunk.document_id == document_id)
        )
        s.add_all(
            [
                Chunk(
                    document_id=document_id,
                    tenant_id=input.tenant_id,
                    chunk_idx=i,
                    content=content,
                    embedding=embedding,
                    chunk_metadata={"filename": input.filename},
                )
                for i, (content, embedding) in enumerate(zip(batch.contents, batch.embeddings))
            ]
        )
    return len(batch.contents)


@activity.defn
async def mark_done(input: IngestionInput) -> None:
    async with tenant_session(input.tenant_id) as s:
        await s.execute(
            update(Document)
            .where(Document.id == uuid.UUID(input.document_id))
            .values(status=DocumentStatus.done)
        )


@activity.defn
async def mark_failed(input: IngestionInput, error: str) -> None:
    async with tenant_session(input.tenant_id) as s:
        await s.execute(
            update(Document)
            .where(Document.id == uuid.UUID(input.document_id))
            .values(status=DocumentStatus.failed, error=error[:2000])
        )
