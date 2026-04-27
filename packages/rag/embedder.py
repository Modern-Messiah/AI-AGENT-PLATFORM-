"""FastEmbed wrapper. Model is loaded lazily once per process."""

from __future__ import annotations

import asyncio
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
                _embedder = TextEmbedding(model_name=settings.embedding_model)
    return _embedder


def _embed_sync(texts: list[str]) -> list[list[float]]:
    return [vec.tolist() for vec in _get_embedder().embed(texts)]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. Offloaded to a thread — FastEmbed is sync/CPU."""
    if not texts:
        return []
    return await asyncio.to_thread(_embed_sync, texts)
