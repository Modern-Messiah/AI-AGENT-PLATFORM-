from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from apps.api import main as api
from apps.api.main import app
from apps.api.routers import documents as document_routes
from apps.api.services.url_sources import (
    FetchedUrlSource,
    UrlImageSource,
    url_image_sidecar_key,
    url_image_sidecar_payload,
)
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
        (path, method.upper())
        for path, methods in app.openapi()["paths"].items()
        for method in methods
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
        created_at=datetime(2026, 6, 7, tzinfo=UTC),
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
    assert response.document.status == DocumentStatus.pending
    assert response.document.error is None
    assert response.changed is True
    assert response.workflow_started is True
    assert cleared == [("tenant-a", f"document-reindex:{document_id}")]

    [(args, kwargs)] = fake_temporal.calls
    ingestion_input = args[1]
    assert ingestion_input.document_id == str(document_id)
    assert ingestion_input.tenant_id == "tenant-a"
    assert ingestion_input.object_key == "tenant-a/manual.pdf"
    assert ingestion_input.filename == "manual.pdf"
    assert kwargs["id"].startswith(f"reindex-tenant-a-{document_id}-")


async def test_reindex_url_document_refetches_source(monkeypatch) -> None:
    document_id = uuid.UUID("73e28adf-6f7a-442e-9077-4554fe49f6b3")
    checked_at = datetime(2026, 6, 7, tzinfo=UTC)
    document = SimpleNamespace(
        id=document_id,
        tenant_id="tenant-url",
        filename="old-title.txt",
        mime_type="text/plain",
        object_key="tenant-url/source.txt",
        size_bytes=9,
        source_type="url",
        source_url="https://example.com/old",
        source_title="Old title",
        source_checked_at=checked_at,
        summary="Old summary.",
        suggested_questions=["Old question?"],
        status=DocumentStatus.done,
        processing_stage="done",
        processed_pages=1,
        total_pages=1,
        warnings=["old warning"],
        error="old failure",
        created_at=checked_at,
    )
    fake_session = _FakeTenantSession(document)
    fake_temporal = _FakeTemporal()
    fetched_urls: list[str] = []
    stored: list[tuple[str, bytes, str | None]] = []

    async def fake_fetch_url_source(url: str) -> FetchedUrlSource:
        fetched_urls.append(url)
        return FetchedUrlSource(
            requested_url=url,
            final_url="https://example.com/new",
            title="New title",
            filename="new-title.txt",
            content_type="text/plain",
            data=b"fresh url body",
        )

    def fake_put(object_key: str, data: bytes, content_type: str | None = None) -> None:
        stored.append((object_key, data, content_type))

    def fake_get(object_key: str) -> bytes:
        if object_key == "tenant-url/source.txt":
            return b"old url body"
        if object_key == url_image_sidecar_key("tenant-url/source.txt"):
            return b'{"images":[]}'
        raise FileNotFoundError(object_key)

    monkeypatch.setattr(document_routes, "tenant_session", lambda tenant_id: fake_session)
    monkeypatch.setattr(api.app.state, "temporal", fake_temporal, raising=False)
    monkeypatch.setattr(document_routes, "fetch_url_source", fake_fetch_url_source)
    monkeypatch.setattr(document_routes.object_store, "get", fake_get)
    monkeypatch.setattr(document_routes.object_store, "put", fake_put)

    async def fake_invalidate(tenant_id: str, reason: str) -> None:
        return None

    monkeypatch.setattr(document_routes, "invalidate_semantic_cache", fake_invalidate)

    request = SimpleNamespace(app=api.app)
    response = await document_routes.reindex_document(document_id, "tenant-url", request)

    assert fetched_urls == ["https://example.com/old"]
    assert stored == [
        ("tenant-url/source.txt", b"fresh url body", "text/plain"),
        (
            url_image_sidecar_key("tenant-url/source.txt"),
            b'{"images":[]}',
            "application/json",
        ),
    ]
    assert document.filename == "new-title.txt"
    assert document.mime_type == "text/plain"
    assert document.size_bytes == len(b"fresh url body")
    assert document.source_url == "https://example.com/new"
    assert document.source_title == "New title"
    assert document.source_checked_at != checked_at
    assert response.document.filename == "new-title.txt"
    assert response.document.source_url == "https://example.com/new"
    assert response.changed is True
    assert response.workflow_started is True

    [(args, _kwargs)] = fake_temporal.calls
    ingestion_input = args[1]
    assert ingestion_input.object_key == "tenant-url/source.txt"
    assert ingestion_input.filename == "new-title.txt"


async def test_reindex_github_document_rewrites_image_sidecar(monkeypatch) -> None:
    document_id = uuid.UUID("e672ed1c-809e-41a1-b252-2b90de6f5e4d")
    checked_at = datetime(2026, 6, 7, tzinfo=UTC)
    document = SimpleNamespace(
        id=document_id,
        tenant_id="tenant-github",
        filename="GitHub_old_repo.txt",
        mime_type="text/plain",
        object_key="tenant-github/source.txt",
        size_bytes=9,
        source_type="github",
        source_url="https://github.com/acme/docs/tree/main/docs",
        source_title="GitHub: acme/docs",
        source_checked_at=checked_at,
        summary="Old summary.",
        suggested_questions=["Old question?"],
        status=DocumentStatus.done,
        processing_stage="done",
        processed_pages=1,
        total_pages=1,
        warnings=["old warning"],
        error=None,
        created_at=checked_at,
    )
    fake_session = _FakeTenantSession(document)
    fake_temporal = _FakeTemporal()
    stored: list[tuple[str, bytes, str | None]] = []

    async def fake_fetch_url_source(url: str) -> FetchedUrlSource:
        assert url == "https://github.com/acme/docs/tree/main/docs"
        return FetchedUrlSource(
            requested_url=url,
            final_url=url,
            title="GitHub: acme/docs",
            filename="GitHub_acme_docs.txt",
            content_type="text/plain; charset=utf-8",
            data=b"fresh github body",
            image_sources=[
                UrlImageSource(
                    url="https://raw.githubusercontent.com/acme/docs/main/docs/flow.png",
                    alt="Flow",
                    title="Payment flow",
                )
            ],
            source_type="github",
            discovered_files=["docs/README.md"],
        )

    def fake_put(object_key: str, data: bytes, content_type: str | None = None) -> None:
        stored.append((object_key, data, content_type))

    def fake_get(object_key: str) -> bytes:
        if object_key == "tenant-github/source.txt":
            return b"old github body"
        if object_key == url_image_sidecar_key("tenant-github/source.txt"):
            return b'{"images":[]}'
        raise FileNotFoundError(object_key)

    monkeypatch.setattr(document_routes, "tenant_session", lambda tenant_id: fake_session)
    monkeypatch.setattr(api.app.state, "temporal", fake_temporal, raising=False)
    monkeypatch.setattr(document_routes, "fetch_url_source", fake_fetch_url_source)
    monkeypatch.setattr(document_routes.object_store, "get", fake_get)
    monkeypatch.setattr(document_routes.object_store, "put", fake_put)

    async def fake_invalidate(tenant_id: str, reason: str) -> None:
        return None

    monkeypatch.setattr(document_routes, "invalidate_semantic_cache", fake_invalidate)

    request = SimpleNamespace(app=api.app)
    response = await document_routes.reindex_document(document_id, "tenant-github", request)

    assert stored == [
        (
            "tenant-github/source.txt",
            b"fresh github body",
            "text/plain; charset=utf-8",
        ),
        (
            url_image_sidecar_key("tenant-github/source.txt"),
            (
                b'{"images":[{"url":"https://raw.githubusercontent.com/acme/docs/main/'
                b'docs/flow.png","alt":"Flow","title":"Payment flow"}]}'
            ),
            "application/json",
        ),
    ]
    assert document.filename == "GitHub_acme_docs.txt"
    assert document.source_type == "github"
    assert document.source_checked_at != checked_at
    assert response.document.status == DocumentStatus.pending
    assert response.changed is True
    assert response.workflow_started is True

    [(args, kwargs)] = fake_temporal.calls
    ingestion_input = args[1]
    assert ingestion_input.object_key == "tenant-github/source.txt"
    assert ingestion_input.filename == "GitHub_acme_docs.txt"
    assert kwargs["id"].startswith(f"reindex-tenant-github-{document_id}-")


async def test_reindex_github_document_reports_no_changes_without_workflow(monkeypatch) -> None:
    document_id = uuid.UUID("59f40866-02e3-42f8-9944-d422353242ff")
    checked_at = datetime(2026, 6, 7, tzinfo=UTC)
    image_sources = [
        UrlImageSource(
            url="https://raw.githubusercontent.com/acme/docs/main/docs/flow.png",
            alt="Flow",
            title="Payment flow",
        )
    ]
    document = SimpleNamespace(
        id=document_id,
        tenant_id="tenant-github",
        filename="GitHub_acme_docs.txt",
        mime_type="text/plain",
        object_key="tenant-github/source.txt",
        size_bytes=len(b"same github body"),
        source_type="github",
        source_url="https://github.com/acme/docs/tree/main/docs",
        source_title="GitHub: acme/docs",
        source_checked_at=checked_at,
        summary="Old summary.",
        suggested_questions=["Old question?"],
        status=DocumentStatus.done,
        processing_stage="done",
        processed_pages=1,
        total_pages=1,
        warnings=["old warning"],
        error=None,
        created_at=checked_at,
    )
    fake_session = _FakeTenantSession(document)
    fake_temporal = _FakeTemporal()
    stored: list[tuple[str, bytes, str | None]] = []
    cleared: list[tuple[str, str]] = []

    async def fake_fetch_url_source(url: str) -> FetchedUrlSource:
        assert url == "https://github.com/acme/docs/tree/main/docs"
        return FetchedUrlSource(
            requested_url=url,
            final_url=url,
            title="GitHub: acme/docs",
            filename="GitHub_acme_docs.txt",
            content_type="text/plain",
            data=b"same github body",
            image_sources=image_sources,
            source_type="github",
            discovered_files=["docs/README.md"],
        )

    def fake_get(object_key: str) -> bytes:
        if object_key == "tenant-github/source.txt":
            return b"same github body"
        if object_key == url_image_sidecar_key("tenant-github/source.txt"):
            return url_image_sidecar_payload(image_sources)
        raise FileNotFoundError(object_key)

    def fake_put(object_key: str, data: bytes, content_type: str | None = None) -> None:
        stored.append((object_key, data, content_type))

    async def fake_invalidate(tenant_id: str, reason: str) -> None:
        cleared.append((tenant_id, reason))

    monkeypatch.setattr(document_routes, "tenant_session", lambda tenant_id: fake_session)
    monkeypatch.setattr(api.app.state, "temporal", fake_temporal, raising=False)
    monkeypatch.setattr(document_routes, "fetch_url_source", fake_fetch_url_source)
    monkeypatch.setattr(document_routes.object_store, "get", fake_get)
    monkeypatch.setattr(document_routes.object_store, "put", fake_put)
    monkeypatch.setattr(document_routes, "invalidate_semantic_cache", fake_invalidate)

    request = SimpleNamespace(app=api.app)
    response = await document_routes.reindex_document(document_id, "tenant-github", request)

    assert stored == []
    assert cleared == []
    assert fake_temporal.calls == []
    assert document.status == DocumentStatus.done
    assert document.source_checked_at != checked_at
    assert document.warnings == ["old warning"]
    assert response.document.status == DocumentStatus.done
    assert response.document.source_checked_at == document.source_checked_at.isoformat()
    assert response.changed is False
    assert response.workflow_started is False
