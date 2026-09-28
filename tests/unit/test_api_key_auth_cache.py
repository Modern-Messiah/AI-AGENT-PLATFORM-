from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from packages.auth import api_keys


class FakeResult:
    def __init__(self, row: object | None = None) -> None:
        self.row = row

    def scalar_one_or_none(self) -> object | None:
        return self.row

    def first(self) -> object | None:
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
            return FakeResult(self.factory.select_row)
        self.factory.update_count += 1
        return FakeResult()


class FakeSessionFactory:
    def __init__(self, select_row: object | None = None) -> None:
        self.execute_count = 0
        self.select_count = 0
        self.update_count = 0
        self.select_row = select_row or (
            SimpleNamespace(id=uuid.uuid4(), tenant_id="tenant-a", name="laptop"),
            None,
            None,
            None,
        )

    def __call__(self) -> FakeSession:
        return FakeSession(self)


async def test_require_tenant_collapses_concurrent_same_key_lookups(monkeypatch) -> None:
    api_keys._AUTH_CACHE.clear()
    api_keys._AUTH_LOCKS.clear()
    factory = FakeSessionFactory()
    monkeypatch.setattr(api_keys, "async_session", factory)

    tenants = await asyncio.gather(*[api_keys.require_tenant("raw-test-key") for _ in range(20)])

    assert tenants == ["tenant-a"] * 20
    assert factory.select_count == 1
    assert factory.update_count == 1


async def test_require_tenant_returns_401_for_missing_api_key(monkeypatch) -> None:
    api_keys._AUTH_CACHE.clear()
    api_keys._AUTH_LOCKS.clear()
    factory = FakeSessionFactory()
    monkeypatch.setattr(api_keys, "async_session", factory)

    with pytest.raises(HTTPException) as exc_info:
        await api_keys.require_tenant(None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "missing API key"
    assert factory.execute_count == 0


async def test_require_actor_resolves_key_owner_identity(monkeypatch) -> None:
    api_keys._AUTH_CACHE.clear()
    api_keys._AUTH_LOCKS.clear()
    user_id = uuid.uuid4()
    factory = FakeSessionFactory()
    factory.select_row = (
        SimpleNamespace(id=uuid.uuid4(), tenant_id="tenant-a", name="laptop"),
        user_id,
        "member",
        "alice",
    )
    monkeypatch.setattr(api_keys, "async_session", factory)

    actor = await api_keys.require_actor("raw-test-key")

    assert actor.tenant_id == "tenant-a"
    assert actor.role == "member"
    assert actor.user_id == user_id
    assert actor.user_name == "alice"


async def test_require_actor_caches_identity_with_the_tenant(monkeypatch) -> None:
    api_keys._AUTH_CACHE.clear()
    api_keys._AUTH_LOCKS.clear()
    user_id = uuid.uuid4()
    factory = FakeSessionFactory()
    factory.select_row = (
        SimpleNamespace(id=uuid.uuid4(), tenant_id="tenant-b", name="desktop"),
        user_id,
        "admin",
        "bob",
    )
    monkeypatch.setattr(api_keys, "async_session", factory)

    await api_keys.require_actor("raw-test-key")
    actor = await api_keys.require_actor("raw-test-key")

    assert actor.user_id == user_id
    assert actor.user_name == "bob"
    assert factory.select_count == 1
