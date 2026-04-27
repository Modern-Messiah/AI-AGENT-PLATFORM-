"""Vector search over pgvector with tenant filter."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from packages.core import settings
from packages.rag.embedder import embed_texts
from packages.storage import Chunk, async_session


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    content: str
    score: float
    metadata: dict


async def retrieve_chunks(
    query: str,
    tenant_id: str,
    k: int | None = None,
) -> list[RetrievedChunk]:
    k = k or settings.retrieval_top_k
    [query_vec] = await embed_texts([query])

    async with async_session() as session:
        # cosine_distance: 0 = identical, 2 = opposite. Score = 1 - distance.
        distance = Chunk.embedding.cosine_distance(query_vec)
        stmt = (
            select(Chunk, distance.label("distance"))
            .where(Chunk.tenant_id == tenant_id)
            .order_by(distance)
            .limit(k)
        )
        rows = (await session.execute(stmt)).all()

    return [
        RetrievedChunk(
            chunk_id=str(chunk.id),
            document_id=str(chunk.document_id),
            content=chunk.content,
            score=1.0 - float(distance),
            metadata=chunk.chunk_metadata,
        )
        for chunk, distance in rows
    ]
