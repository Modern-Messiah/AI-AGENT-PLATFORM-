from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from apps.api import main as api
from apps.api.main import app
from apps.api.routers import documents as document_routes
from fastapi.routing import APIRoute
from packages.storage import DocumentStatus


class _ScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeSession:
    def __init__(self, document) -> None:
        self.document = document
        self.flushed = False

    async def execute(self, statement):
        self.statement = statement
        return _ScalarResult(self.document)

    async def flush(self) -> None:
        self.flushed = True


class _FakeTenantSession:
    def __init__(self, document) -> None:
        self.session = _FakeSession(document)

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class _FakeTemporal:
    def __init__(self) -> None:
        self.calls = []

    async def start_workflow(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))


def test_document_reindex_route_is_registered() -> None:
    routes = {
        (route.path, method)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }

    assert ("/documents/{document_id}/reindex", "POST") in routes


async def test_reindex_document_starts_new_ingestion_workflow(monkeypatch) -> None:
    document_id = uuid.UUID("5ef2d843-ddaf-4ae3-a73d-d25f27fb8621")
    document = SimpleNamespace(
        id=document_id,
        tenant_id="tenant-a",
        filename="manual.pdf",
        mime_type="application/pdf",
        object_key="tenant-a/manual.pdf",
        size_bytes=2048,
        summary="Old summary.",
        suggested_questions=["Old question?"],
        status=DocumentStatus.done,
        error="old failure",
        created_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
    )
    fake_session = _FakeTenantSession(document)
    fake_temporal = _FakeTemporal()
    cleared: list[tuple[str, str]] = []

    monkeypatch.setattr(document_routes, "tenant_session", lambda tenant_id: fake_session)
    monkeypatch.setattr(api.app.state, "temporal", fake_temporal, raising=False)

    async def fake_invalidate(tenant_id: str, reason: str) -> None:
        cleared.append((tenant_id, reason))

    monkeypatch.setattr(document_routes, "invalidate_semantic_cache", fake_invalidate)

    request = SimpleNamespace(app=api.app)
    response = await document_routes.reindex_document(document_id, "tenant-a", request)

    assert fake_session.session.flushed is True
    assert response.status == DocumentStatus.pending
    assert response.error is None
    assert cleared == [("tenant-a", f"document-reindex:{document_id}")]

    [(args, kwargs)] = fake_temporal.calls
    ingestion_input = args[1]
    assert ingestion_input.document_id == str(document_id)
    assert ingestion_input.tenant_id == "tenant-a"
    assert ingestion_input.object_key == "tenant-a/manual.pdf"
    assert ingestion_input.filename == "manual.pdf"
    assert kwargs["id"].startswith(f"reindex-tenant-a-{document_id}-")
