from __future__ import annotations

import pytest
from apps.api.services import url_source_limits
from apps.api.services.rate_limit import check_sliding_window_limit
from fastapi import HTTPException


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
        removed = [member for member, score in zset.items() if min_score <= score <= max_score]
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

    async def zrange(
        self, key: str, start: int, end: int, *, withscores: bool
    ) -> list[tuple[str, float]]:
        assert start == 0
        assert end == 0
        assert withscores is True
        ordered = sorted(self.zsets.setdefault(key, {}).items(), key=lambda item: item[1])
        return ordered[:1]


async def test_url_ingest_limit_rejects_past_hourly_budget() -> None:
    redis = FakeRedis()
    hour_ms = url_source_limits._WINDOW_MS

    await check_sliding_window_limit(
        redis, "rl:tenant-a:url_ingest", limit=2, window_ms=hour_ms, label="x", now_ms=1_000
    )
    await check_sliding_window_limit(
        redis, "rl:tenant-a:url_ingest", limit=2, window_ms=hour_ms, label="x", now_ms=2_000
    )

    with pytest.raises(HTTPException) as exc_info:
        await check_sliding_window_limit(
            redis, "rl:tenant-a:url_ingest", limit=2, window_ms=hour_ms, label="x", now_ms=3_000
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": str(3598)}
    assert await redis.zcard("rl:tenant-a:url_ingest") == 2


async def test_url_ingest_limit_window_rolls_over() -> None:
    redis = FakeRedis()
    hour_ms = url_source_limits._WINDOW_MS

    for ms in (1_000, 2_000):
        await check_sliding_window_limit(
            redis, "rl:t:url_ingest", limit=2, window_ms=hour_ms, label="x", now_ms=ms
        )
    # Older entries fall out of the window, new requests are allowed again.
    await check_sliding_window_limit(
        redis, "rl:t:url_ingest", limit=2, window_ms=hour_ms, label="x", now_ms=hour_ms + 2_500
    )

    assert await redis.zcard("rl:t:url_ingest") == 1


async def test_enforce_url_ingest_limit_disabled_when_zero(monkeypatch) -> None:
    def broken_redis():
        raise RuntimeError("redis down")

    monkeypatch.setattr(url_source_limits, "get_redis", broken_redis)
    monkeypatch.setattr(url_source_limits.settings, "url_ingest_rate_per_hour", 0)

    # Must not touch Redis at all — otherwise this raises via fail-closed.
    await url_source_limits.enforce_url_ingest_limit("tenant-a", "/documents/url")


async def test_enforce_url_ingest_limit_fail_closed_rejects_when_redis_down(
    monkeypatch,
) -> None:
    def broken_redis():
        raise RuntimeError("redis down")

    monkeypatch.setattr(url_source_limits, "get_redis", broken_redis)
    monkeypatch.setattr(url_source_limits.settings, "url_ingest_rate_per_hour", 20)
    monkeypatch.setattr(url_source_limits.settings, "rate_limit_fail_closed", True)

    with pytest.raises(HTTPException) as exc_info:
        await url_source_limits.enforce_url_ingest_limit("tenant-a", "/documents/url")
    assert exc_info.value.status_code == 503


async def test_enforce_url_ingest_limit_fail_open_passes_when_redis_down(monkeypatch) -> None:
    def broken_redis():
        raise RuntimeError("redis down")

    monkeypatch.setattr(url_source_limits, "get_redis", broken_redis)
    monkeypatch.setattr(url_source_limits.settings, "url_ingest_rate_per_hour", 20)
    monkeypatch.setattr(url_source_limits.settings, "rate_limit_fail_closed", False)

    await url_source_limits.enforce_url_ingest_limit("tenant-a", "/documents/url")
