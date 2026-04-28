"""Lazy async Redis client. One shared connection pool per process."""

from __future__ import annotations

from functools import lru_cache

import redis.asyncio as aioredis

from packages.core import settings


@lru_cache(maxsize=1)
def get_redis() -> aioredis.Redis:
    # decode_responses=False — we store raw bytes (msgpack/json).
    return aioredis.from_url(settings.redis_url, decode_responses=False)
