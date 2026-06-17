from __future__ import annotations

import pytest
from fastapi import HTTPException

from apps.api.main import _check_agent_rate_limit


class FakeRedisPipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self.ops: list[tuple[str, tuple[object, ...]]] = []

    def zremrangebyscore(self, *args: object) -> FakeRedisPipeline:
        self.ops.append(("zremrangebyscore", args))
        return self

    def zadd(self, *args: object) -> FakeRedisPipeline:
        self.ops.append(("zadd", args))
        return self

    def zcard(self, *args: object) -> FakeRedisPipeline:
        self.ops.append(("zcard", args))
        return self

    def expire(self, *args: object) -> FakeRedisPipeline:
        self.ops.append(("expire", args))
        return self

    async def execute(self) -> list[object]:
        results: list[object] = []
        for name, args in self.ops:
            results.append(await getattr(self.redis, name)(*args))
        return results


class FakeRedis:
    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}
        self.expires: dict[str, int] = {}

    def pipeline(self, *, transaction: bool) -> FakeRedisPipeline:
        assert transaction is True
        return FakeRedisPipeline(self)

    async def zremrangebyscore(self, key: str, min_score: float, max_score: float) -> int:
        zset = self.zsets.setdefault(key, {})
        removed = [
            member for member, score in zset.items()
            if min_score <= score <= max_score
        ]
        for member in removed:
            del zset[member]
        return len(removed)

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        zset = self.zsets.setdefault(key, {})
        added = 0
        for member, score in mapping.items():
            if member not in zset:
                added += 1
            zset[member] = score
        return added

    async def zcard(self, key: str) -> int:
        return len(self.zsets.setdefault(key, {}))

    async def expire(self, key: str, seconds: int) -> bool:
        self.expires[key] = seconds
        return True

    async def zrem(self, key: str, member: str) -> int:
        zset = self.zsets.setdefault(key, {})
        if member not in zset:
            return 0
        del zset[member]
        return 1

    async def zrange(self, key: str, start: int, end: int, *, withscores: bool) -> list[tuple[str, float]]:
        assert start == 0
        assert end == 0
        assert withscores is True
        ordered = sorted(self.zsets.setdefault(key, {}).items(), key=lambda item: item[1])
        return ordered[:1]


async def test_agent_rate_limit_uses_rolling_window_across_minute_boundary() -> None:
    redis = FakeRedis()

    await _check_agent_rate_limit(redis, "tenant-a", limit=2, now_ms=59_000)
    await _check_agent_rate_limit(redis, "tenant-a", limit=2, now_ms=59_500)

    with pytest.raises(HTTPException) as exc_info:
        await _check_agent_rate_limit(redis, "tenant-a", limit=2, now_ms=60_000)

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "59"}
    assert await redis.zcard("rl:tenant-a:agent") == 2


async def test_agent_rate_limit_allows_requests_after_window_expires() -> None:
    redis = FakeRedis()

    await _check_agent_rate_limit(redis, "tenant-a", limit=2, now_ms=1_000)
    await _check_agent_rate_limit(redis, "tenant-a", limit=2, now_ms=2_000)
    await _check_agent_rate_limit(redis, "tenant-a", limit=2, now_ms=62_000)

    assert await redis.zcard("rl:tenant-a:agent") == 1
