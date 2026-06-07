from __future__ import annotations

from packages.cache import semantic as semantic_module
from packages.cache.semantic import SemanticCache


class _FakePipeline:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.executed = False

    def delete(self, *keys: str) -> _FakePipeline:
        self.deleted.extend(keys)
        return self

    async def execute(self) -> None:
        self.executed = True


class _FakeRedis:
    def __init__(self) -> None:
        self.pipeline_instance = _FakePipeline()

    async def zrange(self, key: str, start: int, end: int) -> list[bytes]:
        assert key == "scache:tenant-a:idx"
        assert (start, end) == (0, -1)
        return [b"entry-one", b"entry-two"]

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        assert transaction is False
        return self.pipeline_instance


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
