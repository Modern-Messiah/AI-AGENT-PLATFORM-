"""FastEmbed wrapper. Model is loaded lazily once per process.

Two entry points mirror fastembed's asymmetric API:
- embed_texts(texts)  — passages, used at ingestion time (chunk indexing);
- embed_queries(texts) — user queries, used for retrieval and the semantic cache.

For symmetric models (bge) both are identical. For asymmetric models
(intfloat/multilingual-e5-*) fastembed applies the required
"query: "/"passage: " prefixes inside these calls.
"""

from __future__ import annotations

import asyncio
import os
import threading

from fastembed import TextEmbedding

from packages.core import settings

_embedder: TextEmbedding | None = None
_lock = threading.Lock()


def _get_embedder() -> TextEmbedding:
    global _embedder
    if _embedder is None:
        with _lock:
            if _embedder is None:
                cache_dir = os.environ.get("FASTEMBED_CACHE_PATH")
                _embedder = (
                    TextEmbedding(model_name=settings.embedding_model, cache_dir=cache_dir)
                    if cache_dir
                    else TextEmbedding(model_name=settings.embedding_model)
                )
    return _embedder


def _embed_passages_sync(texts: list[str]) -> list[list[float]]:
    return [vec.tolist() for vec in _get_embedder().passage_embed(texts)]


def _embed_queries_sync(texts: list[str]) -> list[list[float]]:
    return [vec.tolist() for vec in _get_embedder().query_embed(texts)]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed document passages (ingestion). Offloaded to a thread — FastEmbed is sync/CPU."""
    if not texts:
        return []
    return await asyncio.to_thread(_embed_passages_sync, texts)


async def embed_queries(texts: list[str]) -> list[list[float]]:
    """Embed user queries (retrieval, semantic cache). Offloaded to a thread."""
    if not texts:
        return []
    return await asyncio.to_thread(_embed_queries_sync, texts)
