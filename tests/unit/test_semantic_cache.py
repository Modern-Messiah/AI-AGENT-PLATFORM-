from __future__ import annotations

import json

from packages.cache import semantic as semantic_module
from packages.agents.schemas import AgentRunOutput
from packages.cache.semantic import SemanticCache


class _FakePipeline:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.get_keys: list[str] = []
        self.executed = False

    def delete(self, *keys: str) -> _FakePipeline:
        self.deleted.extend(keys)
        return self

    def get(self, key: str) -> _FakePipeline:
        self.get_keys.append(key)
        return self

    async def execute(self):
        self.executed = True
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
    def __init__(self) -> None:
        self.pipeline_instance = _FakePipeline()
        self.zrange_calls: list[tuple[str, int, int, bool]] = []

    async def zrange(self, key: str, start: int, end: int, desc: bool = False) -> list[bytes]:
        assert key == "scache:tenant-a:idx"
        self.zrange_calls.append((key, start, end, desc))
        return [b"entry-one", b"entry-two"]

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        assert transaction is False
        return self.pipeline_instance

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
