"""Semantic cache backed by Redis.

On cache miss the caller runs the LLM and then stores the result here.
On cache hit the result is returned without any LLM call.

Storage layout (plain Redis — no vector-search module required):
  scache:{tenant_id}:idx          — Redis ZSET (score=timestamp) of entry UUIDs
  scache:{tenant_id}:{entry_uuid} — Redis STRING (JSON) with vec + result, TTL-d

Lookup scans the newest _MAX_SCAN entries from the ZSET index, then computes
cosine in numpy. The ZSET is capped at _MAX_INDEX entries; oldest are evicted on
every write so the index never grows unbounded (unlike a plain SET).
"""

from __future__ import annotations

import json
import logging
import time
import uuid

import numpy as np

from packages.agents.schemas import AgentRunOutput
from packages.cache.redis import get_redis
from packages.rag.embedder import embed_texts

log = logging.getLogger(__name__)

_TTL_SECONDS = 3600       # 1 hour per entry
_THRESHOLD = 0.92         # cosine similarity required for a hit
_MAX_SCAN = 500           # max entries to scan per lookup
_MAX_INDEX = 1000         # hard cap on index size per tenant; oldest entries evicted first


class SemanticCache:
    def _idx_key(self, tenant_id: str) -> str:
        return f"scache:{tenant_id}:idx"

    def _entry_key(self, tenant_id: str, entry_id: str) -> str:
        return f"scache:{tenant_id}:{entry_id}"

    async def get(self, query: str, tenant_id: str) -> AgentRunOutput | None:
        r = get_redis()
        idx_key = self._idx_key(tenant_id)

        # Fetch the newest _MAX_SCAN entries (highest scores = most recent timestamps).
        entry_ids = [
            eid.decode() if isinstance(eid, bytes) else eid
            for eid in await r.zrange(idx_key, 0, _MAX_SCAN - 1, desc=True)
        ]
        if not entry_ids:
            return None

        # Batch-fetch all entries in one round trip.
        pipe = r.pipeline(transaction=False)
        for eid in entry_ids:
            pipe.get(self._entry_key(tenant_id, eid))
        raw_values = await pipe.execute()

        query_vec = np.array((await embed_texts([query]))[0], dtype=np.float32)
        query_norm = np.linalg.norm(query_vec)

        best_sim = _THRESHOLD
        best_result: AgentRunOutput | None = None
        expired: list[str] = []

        for eid, raw in zip(entry_ids, raw_values):
            if raw is None:
                expired.append(eid)
                continue
            data = json.loads(raw)
            result_data = data.get("result") or {}
            answer = result_data.get("answer")
            if not isinstance(answer, str) or not answer.strip():
                expired.append(eid)
                continue
            cached_vec = np.array(data["vec"], dtype=np.float32)
            sim = float(
                np.dot(query_vec, cached_vec)
                / (query_norm * np.linalg.norm(cached_vec) + 1e-8)
            )
            if sim > best_sim:
                best_sim = sim
                best_result = AgentRunOutput(**result_data)

        # Clean up expired ids from the index (fire-and-forget).
        if expired:
            await r.zrem(idx_key, *expired)

        if best_result is not None:
            log.info("semantic cache hit | tenant=%s sim=%.4f", tenant_id, best_sim)
        return best_result

    async def set(self, query: str, tenant_id: str, result: AgentRunOutput) -> None:
        if not result.answer.strip():
            log.warning("semantic cache skip empty answer | tenant=%s", tenant_id)
            return

        r = get_redis()
        vec = np.array((await embed_texts([query]))[0], dtype=np.float32)
        entry_id = str(uuid.uuid4())

        data = json.dumps({"vec": vec.tolist(), "result": result.model_dump()})

        pipe = r.pipeline(transaction=False)
        pipe.set(self._entry_key(tenant_id, entry_id), data, ex=_TTL_SECONDS)
        # Add to ZSET with current timestamp as score so we can sort by recency.
        pipe.zadd(self._idx_key(tenant_id), {entry_id: time.time()})
        pipe.expire(self._idx_key(tenant_id), _TTL_SECONDS)
        # Trim to _MAX_INDEX by removing oldest entries (rank 0 … N-_MAX_INDEX-1).
        pipe.zremrangebyrank(self._idx_key(tenant_id), 0, -(_MAX_INDEX + 1))
        await pipe.execute()


semantic_cache = SemanticCache()
