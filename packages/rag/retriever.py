"""Vector search over pgvector with tenant filter."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from packages.core import settings
from packages.rag.embedder import embed_texts
from packages.storage import Chunk, Document
from packages.storage.db import tenant_session


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    filename: str
    content: str
    score: float
    metadata: dict


async def retrieve_chunks(
    query: str,
    tenant_id: str,
    k: int | None = None,
    max_distance: float | None = None,
) -> list[RetrievedChunk]:
    k = k or settings.retrieval_top_k
    max_distance = settings.retrieval_max_distance if max_distance is None else max_distance
    [query_vec] = await embed_texts([query])

    async with tenant_session(tenant_id) as session:
        # cosine_distance: 0 = identical, 2 = opposite. Score = 1 - distance.
        distance = Chunk.embedding.cosine_distance(query_vec)
        stmt = (
            select(Chunk, Document.filename, distance.label("distance"))
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.tenant_id == tenant_id)
            .order_by(distance)
            .limit(k)
        )
        if max_distance > 0:
            stmt = stmt.where(distance <= max_distance)
        rows = (await session.execute(stmt)).all()

    return [
        RetrievedChunk(
            chunk_id=str(chunk.id),
            document_id=str(chunk.document_id),
            filename=filename,
            content=chunk.content,
            score=1.0 - float(distance),
            metadata=chunk.chunk_metadata,
        )
        for chunk, filename, distance in rows
    ]
