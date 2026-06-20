from __future__ import annotations

import json

from packages.cache import semantic as semantic_module
from packages.agents.schemas import AgentRunOutput
from packages.cache.semantic import SemanticCache


class _FakePipeline:
    def __init__(self, raw_values: list[str | bytes | None] | None = None) -> None:
        self.deleted: list[str] = []
        self.get_keys: list[str] = []
        self.set_calls: list[tuple[str, str, int | None]] = []
        self.zadd_calls: list[tuple[str, dict[str, float]]] = []
        self.expire_calls: list[tuple[str, int]] = []
        self.zremrangebyrank_calls: list[tuple[str, int, int]] = []
        self.raw_values = raw_values
        self.executed = False

    def delete(self, *keys: str) -> _FakePipeline:
        self.deleted.extend(keys)
        return self

    def get(self, key: str) -> _FakePipeline:
        self.get_keys.append(key)
        return self

    def set(self, key: str, value: str, ex: int | None = None) -> _FakePipeline:
        self.set_calls.append((key, value, ex))
        return self

    def zadd(self, key: str, mapping: dict[str, float]) -> _FakePipeline:
        self.zadd_calls.append((key, mapping))
        return self

    def expire(self, key: str, ttl: int) -> _FakePipeline:
        self.expire_calls.append((key, ttl))
        return self

    def zremrangebyrank(self, key: str, start: int, end: int) -> _FakePipeline:
        self.zremrangebyrank_calls.append((key, start, end))
        return self

    async def execute(self):
        self.executed = True
        if self.raw_values is not None:
            return self.raw_values
        if self.get_keys:
            return [
                json.dumps({
                    "vec": [1.0, 0.0],
                    "result": AgentRunOutput(
                        answer="cached answer",
                        confidence=0.8,
                        sources=[],
                        cached=True,
                    ).model_dump(),
                })
                for _key in self.get_keys
            ]
        return None


class _FakeRedis:
    def __init__(
        self,
        *,
        entry_ids: list[bytes | str] | None = None,
        raw_values: list[str | bytes | None] | None = None,
    ) -> None:
        self.pipeline_instance = _FakePipeline(raw_values)
        self.entry_ids = entry_ids or [b"entry-one", b"entry-two"]
        self.zrange_calls: list[tuple[str, int, int, bool]] = []
        self.zrem_calls: list[tuple[str, tuple[str, ...]]] = []

    async def zrange(self, key: str, start: int, end: int, desc: bool = False) -> list[bytes]:
        assert key == "scache:tenant-a:idx"
        self.zrange_calls.append((key, start, end, desc))
        return self.entry_ids

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        assert transaction is False
        return self.pipeline_instance

    async def zrem(self, key: str, *values: str) -> int:
        self.zrem_calls.append((key, values))
        return len(values)

    async def keys(self, pattern: str) -> list[str]:
        raise AssertionError(f"semantic cache must not use global Redis keys scan: {pattern}")

    async def scan_iter(self, match: str):
        raise AssertionError(f"semantic cache must not use Redis scan_iter: {match}")


async def test_clear_removes_tenant_index_and_all_cached_entries(monkeypatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(semantic_module, "get_redis", lambda: redis)

    await SemanticCache().clear("tenant-a")

    assert redis.pipeline_instance.deleted == [
        "scache:tenant-a:entry-one",
        "scache:tenant-a:entry-two",
        "scache:tenant-a:idx",
    ]
    assert redis.zrange_calls == [
        ("scache:tenant-a:idx", 0, -1, False)
    ]
    assert redis.pipeline_instance.executed is True


async def test_get_uses_bounded_tenant_index_without_global_key_scan(monkeypatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(semantic_module, "get_redis", lambda: redis)

    async def fake_embed_texts(values: list[str]) -> list[list[float]]:
        assert values == ["query"]
        return [[1.0, 0.0]]

    monkeypatch.setattr(semantic_module, "embed_texts", fake_embed_texts)

    result = await SemanticCache().get("query", "tenant-a")

    assert result is not None
    assert result.answer == "cached answer"
    assert redis.zrange_calls == [
        ("scache:tenant-a:idx", 0, semantic_module._MAX_SCAN - 1, True)
    ]
    assert redis.pipeline_instance.get_keys == [
        "scache:tenant-a:entry-one",
        "scache:tenant-a:entry-two",
    ]


async def test_get_removes_stale_index_members_without_embedding_when_all_entries_invalid(monkeypatch) -> None:
    redis = _FakeRedis(
        entry_ids=[b"missing", b"malformed", b"not-object", b"empty-answer", b"bad-vector"],
        raw_values=[
            None,
            b"{not-json",
            json.dumps(["not", "an", "object"]),
            json.dumps({"vec": [1.0, 0.0], "result": {"answer": "   "}}),
            json.dumps({"vec": "not-a-vector", "result": {"answer": "cached"}}),
        ],
    )
    monkeypatch.setattr(semantic_module, "get_redis", lambda: redis)

    async def fake_embed_texts(values: list[str]) -> list[list[float]]:
        raise AssertionError("embedding should not run when no valid cache payloads remain")

    monkeypatch.setattr(semantic_module, "embed_texts", fake_embed_texts)

    result = await SemanticCache().get("query", "tenant-a")

    assert result is None
    assert redis.zrem_calls == [
        (
            "scache:tenant-a:idx",
            ("missing", "malformed", "not-object", "empty-answer", "bad-vector"),
        )
    ]


async def test_set_caps_tenant_index(monkeypatch) -> None:
    redis = _FakeRedis(entry_ids=[])
    monkeypatch.setattr(semantic_module, "get_redis", lambda: redis)

    async def fake_embed_texts(values: list[str]) -> list[list[float]]:
        assert values == ["query"]
        return [[1.0, 0.0]]

    monkeypatch.setattr(semantic_module, "embed_texts", fake_embed_texts)
    monkeypatch.setattr(semantic_module.uuid, "uuid4", lambda: "entry-fixed")
    monkeypatch.setattr(semantic_module.time, "time", lambda: 123.45)

    await SemanticCache().set(
        "query",
        "tenant-a",
        AgentRunOutput(answer="answer", confidence=0.8, sources=[], cached=False),
    )

    assert redis.pipeline_instance.set_calls
    assert redis.pipeline_instance.zadd_calls == [
        ("scache:tenant-a:idx", {"entry-fixed": 123.45})
    ]
    assert redis.pipeline_instance.expire_calls == [
        ("scache:tenant-a:idx", semantic_module._TTL_SECONDS)
    ]
    assert redis.pipeline_instance.zremrangebyrank_calls == [
        ("scache:tenant-a:idx", 0, -(semantic_module._MAX_INDEX + 1))
    ]
