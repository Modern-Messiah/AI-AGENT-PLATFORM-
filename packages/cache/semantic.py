"""Semantic cache backed by Redis.

On cache miss the caller runs the LLM and then stores the result here.
On cache hit the result is returned without any LLM call.

Storage layout (plain Redis — no vector-search module required):
  scache:{tenant_id}:idx          — Redis SET  of entry UUIDs for the tenant
  scache:{tenant_id}:{entry_uuid} — Redis STRING (JSON) with vec + result, TTL-d

Lookup scans at most _MAX_SCAN entries per tenant via a single pipeline batch,
then computes cosine in numpy. Scales to a few thousand cached queries; swap for
Redis Stack vector search when the index grows beyond that.
"""

from __future__ import annotations

import json
import logging
import uuid

import numpy as np

from packages.agents.schemas import AgentRunOutput
from packages.cache.redis import get_redis
from packages.rag.embedder import embed_texts

log = logging.getLogger(__name__)

_TTL_SECONDS = 3600       # 1 hour per entry
_THRESHOLD = 0.92         # cosine similarity required for a hit
_MAX_SCAN = 500           # max entries to scan per lookup


class SemanticCache:
    def _idx_key(self, tenant_id: str) -> str:
        return f"scache:{tenant_id}:idx"

    def _entry_key(self, tenant_id: str, entry_id: str) -> str:
        return f"scache:{tenant_id}:{entry_id}"

    async def get(self, query: str, tenant_id: str) -> AgentRunOutput | None:
        r = get_redis()
        idx_key = self._idx_key(tenant_id)

        entry_ids = [eid.decode() for eid in await r.smembers(idx_key)]
        if not entry_ids:
            return None

        entry_ids = entry_ids[:_MAX_SCAN]

        # Batch-fetch all entries in one round trip.
        pipe = r.pipeline(transaction=False)
        for eid in entry_ids:
            pipe.get(self._entry_key(tenant_id, eid))
        raw_values = await pipe.execute()

        query_vec = (await embed_texts([query]))[0].astype(np.float32)
        query_norm = np.linalg.norm(query_vec)

        best_sim = _THRESHOLD
        best_result: AgentRunOutput | None = None
        expired: list[str] = []

        for eid, raw in zip(entry_ids, raw_values):
            if raw is None:
                expired.append(eid)
                continue
            data = json.loads(raw)
            cached_vec = np.array(data["vec"], dtype=np.float32)
            sim = float(
                np.dot(query_vec, cached_vec)
                / (query_norm * np.linalg.norm(cached_vec) + 1e-8)
            )
            if sim > best_sim:
                best_sim = sim
                best_result = AgentRunOutput(**data["result"])

        # Clean up expired ids from the index (fire-and-forget).
        if expired:
            await r.srem(idx_key, *expired)

        if best_result is not None:
            log.info("semantic cache hit | tenant=%s sim=%.4f", tenant_id, best_sim)
        return best_result

    async def set(self, query: str, tenant_id: str, result: AgentRunOutput) -> None:
        r = get_redis()
        vec = (await embed_texts([query]))[0].astype(np.float32)
        entry_id = str(uuid.uuid4())

        data = json.dumps({"vec": vec.tolist(), "result": result.model_dump()})

        pipe = r.pipeline(transaction=False)
        pipe.set(self._entry_key(tenant_id, entry_id), data, ex=_TTL_SECONDS)
        pipe.sadd(self._idx_key(tenant_id), entry_id)
        pipe.expire(self._idx_key(tenant_id), _TTL_SECONDS)
        await pipe.execute()


semantic_cache = SemanticCache()
