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
    api_keys._AUTH_NEGATIVE_CACHE.clear()
    factory = FakeSessionFactory()
    monkeypatch.setattr(api_keys, "async_session", factory)

    tenants = await asyncio.gather(*[api_keys.require_tenant("raw-test-key") for _ in range(20)])

    assert tenants == ["tenant-a"] * 20
    assert factory.select_count == 1
    assert factory.update_count == 1


async def test_require_tenant_returns_401_for_missing_api_key(monkeypatch) -> None:
    api_keys._AUTH_CACHE.clear()
    api_keys._AUTH_LOCKS.clear()
    api_keys._AUTH_NEGATIVE_CACHE.clear()
    factory = FakeSessionFactory()
    monkeypatch.setattr(api_keys, "async_session", factory)

    with pytest.raises(HTTPException) as exc_info:
        await api_keys.require_tenant(None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "missing credentials: X-API-Key or Bearer session"
    assert factory.execute_count == 0


async def test_require_actor_resolves_key_owner_identity(monkeypatch) -> None:
    api_keys._AUTH_CACHE.clear()
    api_keys._AUTH_LOCKS.clear()
    api_keys._AUTH_NEGATIVE_CACHE.clear()
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
    api_keys._AUTH_NEGATIVE_CACHE.clear()
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


async def test_invalid_key_is_negatively_cached_without_db_hits(monkeypatch) -> None:
    api_keys._AUTH_CACHE.clear()
    api_keys._AUTH_LOCKS.clear()
    api_keys._AUTH_NEGATIVE_CACHE.clear()
    factory = FakeSessionFactory()
    factory.select_row = None  # None is replaced by the default row in __init__
    monkeypatch.setattr(api_keys, "async_session", factory)

    with pytest.raises(HTTPException) as first:
        await api_keys.require_actor("definitely-not-a-key")
    with pytest.raises(HTTPException) as second:
        await api_keys.require_actor("definitely-not-a-key")

    assert first.value.status_code == 401
    assert second.value.detail == first.value.detail
    # Only the first request reaches the DB; the replay is served from the
    # negative cache — key spraying must be nearly free to reject.
    assert factory.select_count == 1


async def test_invalid_keys_do_not_grow_the_lock_dict(monkeypatch) -> None:
    api_keys._AUTH_CACHE.clear()
    api_keys._AUTH_LOCKS.clear()
    api_keys._AUTH_NEGATIVE_CACHE.clear()
    factory = FakeSessionFactory()
    factory.select_row = None  # None is replaced by the default row in __init__
    monkeypatch.setattr(api_keys, "async_session", factory)

    for i in range(50):
        with pytest.raises(HTTPException):
            await api_keys.require_actor(f"spray-{i}")

    # One lock per key sprayed used to accumulate forever; now locks are
    # dropped as soon as nobody waits on them.
    assert len(api_keys._AUTH_LOCKS) == 0


async def test_negative_cache_expires_and_rechecks_the_db(monkeypatch) -> None:
    api_keys._AUTH_CACHE.clear()
    api_keys._AUTH_LOCKS.clear()
    api_keys._AUTH_NEGATIVE_CACHE.clear()
    factory = FakeSessionFactory()
    factory.select_row = None  # None is replaced by the default row in __init__
    monkeypatch.setattr(api_keys, "async_session", factory)

    with pytest.raises(HTTPException):
        await api_keys.require_actor("maybe-created-later")
    # Expire the negative entry: the key may have just been created.
    key_hash = api_keys._hash("maybe-created-later")
    api_keys._AUTH_NEGATIVE_CACHE[key_hash] = 0.0
    factory.select_row = (
        SimpleNamespace(id=uuid.uuid4(), tenant_id="tenant-a", name="newly-created"),
        None,
        None,
        None,
    )

    actor = await api_keys.require_actor("maybe-created-later")

    assert actor.tenant_id == "tenant-a"
    assert factory.select_count == 2
