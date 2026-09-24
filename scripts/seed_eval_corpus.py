#!/usr/bin/env python3
"""Seed the CI retrieval-eval corpus into PostgreSQL.

Creates (or replaces) a tenant with fixed documents and chunks embedded
with the CURRENT embedding model, so evals measure the live retrieval
stack (multilingual embeddings + hybrid search) against a deterministic
corpus.

Usage:
    DATABASE_URL=postgresql+asyncpg://postgres:...@localhost:5432/app \
    uv run python scripts/seed_eval_corpus.py \
        --corpus evals/datasets/ci_corpus.json
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.core import settings
from packages.rag import detect_language, embed_texts
from packages.storage import Chunk, Document, DocumentStatus
from packages.storage.db import tenant_session
from sqlalchemy import delete


async def seed(corpus: dict) -> int:
    tenant_id = corpus["tenant"]
    documents = corpus["documents"]

    async with tenant_session(tenant_id) as s:
        await s.execute(delete(Chunk).where(Chunk.tenant_id == tenant_id))
        await s.execute(delete(Document).where(Document.tenant_id == tenant_id))

    total_chunks = 0
    for doc in documents:
        contents = doc["chunks"]
        embeddings = await embed_texts(contents)
        document_id = uuid.uuid4()
        async with tenant_session(tenant_id) as s:
            s.add(
                Document(
                    id=document_id,
                    tenant_id=tenant_id,
                    filename=doc["filename"],
                    mime_type="text/plain",
                    object_key=f"{tenant_id}/{document_id}/{doc['filename']}",
                    size_bytes=sum(len(content) for content in contents),
                    status=DocumentStatus.done,
                )
            )
            for idx, (content, embedding) in enumerate(zip(contents, embeddings, strict=True)):
                s.add(
                    Chunk(
                        document_id=document_id,
                        tenant_id=tenant_id,
                        chunk_idx=idx,
                        content=content,
                        embedding=embedding,
                        chunk_metadata={
                            "filename": doc["filename"],
                            "embedding_model": settings.embedding_model,
                            "lang": detect_language(content),
                        },
                    )
                )
        total_chunks += len(contents)
        print(f"seeded {doc['filename']}: {len(contents)} chunk(s)")

    print(f"\ntenant={tenant_id} documents={len(documents)} chunks={total_chunks}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("evals/datasets/ci_corpus.json"),
    )
    args = parser.parse_args()

    import asyncio

    return asyncio.run(seed(json.loads(args.corpus.read_text())))


if __name__ == "__main__":
    sys.exit(main())
