from __future__ import annotations

import asyncio
from types import SimpleNamespace

from packages.auth import api_keys


class FakeResult:
    def __init__(self, row: object | None = None) -> None:
        self.row = row

    def scalar_one_or_none(self) -> object | None:
        return self.row


class FakeSession:
    def __init__(self, factory: FakeSessionFactory) -> None:
        self.factory = factory

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> FakeSession:
        return self

    async def execute(self, statement: object) -> FakeResult:
        self.factory.execute_count += 1
        statement_text = str(statement)
        if statement_text.startswith("SELECT"):
            self.factory.select_count += 1
            await asyncio.sleep(0)
            return FakeResult(SimpleNamespace(tenant_id="tenant-a"))
        self.factory.update_count += 1
        return FakeResult()


class FakeSessionFactory:
    def __init__(self) -> None:
        self.execute_count = 0
        self.select_count = 0
        self.update_count = 0

    def __call__(self) -> FakeSession:
        return FakeSession(self)


async def test_require_tenant_collapses_concurrent_same_key_lookups(monkeypatch) -> None:
    api_keys._AUTH_CACHE.clear()
    api_keys._AUTH_LOCKS.clear()
    factory = FakeSessionFactory()
    monkeypatch.setattr(api_keys, "async_session", factory)

    tenants = await asyncio.gather(*[
        api_keys.require_tenant("raw-test-key")
        for _ in range(20)
    ])

    assert tenants == ["tenant-a"] * 20
    assert factory.select_count == 1
    assert factory.update_count == 1
