"""Shared Redis sliding-window rate limiter.

One window implementation for every rate-limited route family (agent chat,
auth, URL ingest): callers pick their key namespace, window length, limit
and label; the zset bookkeeping and Retry-After math live here so the
sliding-window algorithm is not re-implemented per limiter.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import HTTPException


async def check_sliding_window_limit(
    redis: Any,
    key: str,
    *,
    limit: int,
    window_ms: int,
    label: str,
    now_ms: int | None = None,
) -> None:
    """Count one event against `key` and raise 429 past `limit` per window.

    Redis errors propagate to the caller — the fail-open/fail-closed
    decision is the caller's (see enforce_* services).
    """
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    member = f"{now_ms}:{uuid.uuid4().hex}"
    window_start = now_ms - window_ms

    pipe = redis.pipeline(transaction=True)
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zadd(key, {member: now_ms})
    pipe.zcard(key)
    pipe.expire(key, window_ms // 1000 + 60)
    _removed, _added, count, _expired = await pipe.execute()

    if count <= limit:
        return

    await redis.zrem(key, member)
    oldest = await redis.zrange(key, 0, 0, withscores=True)
    oldest_score = float(oldest[0][1]) if oldest else float(now_ms)
    retry_after = max(
        1,
        min(window_ms // 1000, int((oldest_score + window_ms - now_ms + 999) // 1000)),
    )
    raise HTTPException(
        status_code=429,
        detail=f"rate limit exceeded: {limit} {label}",
        headers={"Retry-After": str(retry_after)},
    )
