from __future__ import annotations

import uuid
from types import SimpleNamespace

from apps.api import main as api
from packages.storage import DocumentAssetStatus


class _ScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeSession:
    def __init__(self, asset) -> None:
        self.asset = asset
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _ScalarResult(self.asset)


class _FakeTenantSession:
    def __init__(self, asset) -> None:
        self.session = _FakeSession(asset)

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


async def test_asset_content_is_tenant_scoped_and_returns_webp(monkeypatch) -> None:
    document_id = uuid.UUID("5ef2d843-ddaf-4ae3-a73d-d25f27fb8621")
    asset_id = uuid.UUID("7d96274d-79ad-461b-a84d-b9f2a49eced6")
    asset = SimpleNamespace(
        id=asset_id,
        document_id=document_id,
        tenant_id="tenant-a",
        preview_object_key="tenant-a/document/page-2.webp",
        status=DocumentAssetStatus.done,
    )
    fake_session = _FakeTenantSession(asset)
    requested_keys: list[str] = []

    monkeypatch.setattr(api, "tenant_session", lambda tenant_id: fake_session)

    def fake_get(key: str) -> bytes:
        requested_keys.append(key)
        return b"webp-preview"

    monkeypatch.setattr(api.object_store, "get", fake_get)

    response = await api.get_document_asset_content(document_id, asset_id, "tenant-a")

    query = str(fake_session.session.statement)
    assert "document_assets.id" in query
    assert "document_assets.document_id" in query
    assert "document_assets.tenant_id" in query
    assert requested_keys == ["tenant-a/document/page-2.webp"]
    assert response.media_type == "image/webp"
    assert response.body == b"webp-preview"
