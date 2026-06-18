from __future__ import annotations

import logging
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from apps.api.main import DocumentResponse, UrlCheckResponse, app
from apps.api.routers import documents as documents_router
from apps.api.services import url_sources
from apps.api.services.url_sources import (
    FetchedUrlSource,
    UrlImageSource,
    UrlSourceError,
    extract_html_image_sources,
    extract_html_title,
    html_to_text,
    safe_url_filename,
    url_image_sidecar_key,
    url_image_sidecar_payload,
    validate_fetch_url,
)
from fastapi.routing import APIRoute
from packages.storage import DocumentStatus


def test_url_source_routes_are_registered() -> None:
    routes = {
        (route.path, method)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }

    assert ("/documents/url/check", "POST") in routes
    assert ("/documents/url", "POST") in routes


def test_url_check_response_schema() -> None:
    response = UrlCheckResponse(
        ok=True,
        url="https://example.com/docs",
        final_url="https://example.com/docs",
        content_type="text/html",
        title="Example Docs",
        size_bytes=1024,
    )

    assert response.ok is True
    assert response.title == "Example Docs"


def test_document_response_includes_url_source_metadata() -> None:
    response = DocumentResponse(
        id="document-1",
        tenant_id="tenant-a",
        filename="example-docs.txt",
        status=DocumentStatus.pending,
        source_type="url",
        source_url="https://example.com/docs",
        source_title="Example Docs",
        source_checked_at="2026-06-17T00:00:00+00:00",
    )

    payload = response.model_dump()

    assert payload["source_type"] == "url"
    assert payload["source_url"] == "https://example.com/docs"
    assert payload["source_title"] == "Example Docs"
    assert payload["source_checked_at"] == "2026-06-17T00:00:00+00:00"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file.txt",
        "http://user:pass@example.com/private",
        "http://localhost:8000/health",
        "http://127.0.0.1:8000/health",
        "http://10.0.0.5/private",
        "http://169.254.169.254/latest/meta-data",
    ],
)
async def test_validate_fetch_url_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(UrlSourceError):
        await validate_fetch_url(url)


async def test_validate_fetch_url_rejects_private_dns(monkeypatch) -> None:
    def fake_getaddrinfo(*args, **kwargs):
        return [(None, None, None, None, ("192.168.1.15", 0))]

    monkeypatch.setattr("apps.api.services.url_sources.socket.getaddrinfo", fake_getaddrinfo)

    with pytest.raises(UrlSourceError, match="private"):
        await validate_fetch_url("https://docs.example.com/page")


async def test_validate_fetch_url_allows_host_docker_internal_only_for_local_e2e(monkeypatch) -> None:
    def fake_getaddrinfo(*args, **kwargs):
        return [(None, None, None, None, ("192.168.65.2", 0))]

    monkeypatch.setattr("apps.api.services.url_sources.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        url_sources,
        "settings",
        SimpleNamespace(
            app_env="local",
            e2e_allow_local_url_sources=True,
            http_fetch_allowed_domains=[],
        ),
    )

    assert (
        await validate_fetch_url("http://host.docker.internal:8765/page.html")
        == "http://host.docker.internal:8765/page.html"
    )


async def test_validate_fetch_url_rejects_host_docker_internal_outside_local_e2e(monkeypatch) -> None:
    def fake_getaddrinfo(*args, **kwargs):
        return [(None, None, None, None, ("192.168.65.2", 0))]

    monkeypatch.setattr("apps.api.services.url_sources.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        url_sources,
        "settings",
        SimpleNamespace(
            app_env="production",
            e2e_allow_local_url_sources=True,
            http_fetch_allowed_domains=[],
        ),
    )

    with pytest.raises(UrlSourceError, match="HTTP_FETCH_ALLOWED_DOMAINS"):
        await validate_fetch_url("http://host.docker.internal:8765/page.html")


async def test_validate_fetch_url_accepts_public_dns(monkeypatch) -> None:
    def fake_getaddrinfo(*args, **kwargs):
        return [(None, None, None, None, ("93.184.216.34", 0))]

    monkeypatch.setattr("apps.api.services.url_sources.socket.getaddrinfo", fake_getaddrinfo)

    assert await validate_fetch_url("https://docs.example.com/page") == "https://docs.example.com/page"


async def test_validate_fetch_url_enforces_allowlist_for_public_ip(monkeypatch) -> None:
    monkeypatch.setattr(url_sources.settings, "http_fetch_allowed_domains", ["docs.example.com"])

    with pytest.raises(UrlSourceError, match="HTTP_FETCH_ALLOWED_DOMAINS"):
        await validate_fetch_url("https://93.184.216.34/page")


def test_html_helpers_extract_readable_text_and_title() -> None:
    html = b"""
    <html>
      <head><title>Example &amp; Docs</title><script>alert(1)</script></head>
      <body><nav>Menu</nav><h1>Hello</h1><p>Readable <b>content</b>.</p></body>
    </html>
    """

    assert extract_html_title(html) == "Example & Docs"
    assert "Hello" in html_to_text(html)
    assert "Readable content." in html_to_text(html)
    assert "alert" not in html_to_text(html)


def test_html_image_source_extraction_filters_noise_and_resolves_urls() -> None:
    html = b"""
    <html>
      <body>
        <img src="/static/logo.png" width="64" height="32" alt="Company logo">
        <img src="/diagrams/payment-flow.png" width="900" height="640" alt="Payment flow diagram">
        <img data-src="https://cdn.example.com/table.webp" alt="Tariff comparison table">
        <img srcset="/small.jpg 320w, /large.jpg 1200w" title="Network topology">
        <img src="data:image/png;base64,AAAA" alt="inline">
      </body>
    </html>
    """

    sources = extract_html_image_sources(html, "https://docs.example.com/help/index.html")

    assert sources == [
        UrlImageSource(
            url="https://docs.example.com/diagrams/payment-flow.png",
            alt="Payment flow diagram",
            title="",
        ),
        UrlImageSource(
            url="https://cdn.example.com/table.webp",
            alt="Tariff comparison table",
            title="",
        ),
        UrlImageSource(
            url="https://docs.example.com/large.jpg",
            alt="",
            title="Network topology",
        ),
    ]


def test_html_image_source_limit_uses_settings_and_logs(monkeypatch, caplog) -> None:
    html = "\n".join(
        f'<img src="/diagrams/flow-{index}.png" width="900" height="640" alt="Flow {index}">'
        for index in range(10)
    ).encode()
    monkeypatch.setattr(
        url_sources,
        "settings",
        SimpleNamespace(url_source_max_images=3),
    )

    with caplog.at_level(logging.INFO, logger="apps.api.services.url_sources"):
        sources = extract_html_image_sources(html, "https://docs.example.com/page.html")

    assert [source.url for source in sources] == [
        "https://docs.example.com/diagrams/flow-0.png",
        "https://docs.example.com/diagrams/flow-1.png",
        "https://docs.example.com/diagrams/flow-2.png",
    ]
    assert [
        record.message
        for record in caplog.records
        if "URL image source limit applied" in record.message
    ] == [
        (
            "URL image source limit applied | "
            "base_url=https://docs.example.com/page.html found=10 selected=3"
        )
    ]


def test_url_image_sidecar_payload_is_stable_json() -> None:
    sources = [
        UrlImageSource(
            url="https://docs.example.com/diagram.png",
            alt="Flow",
            title="Payment flow",
        )
    ]

    assert url_image_sidecar_key("tenant/doc/Example.txt") == "tenant/doc/Example.txt.url-images.json"
    assert url_image_sidecar_payload(sources) == (
        b'{"images":[{"url":"https://docs.example.com/diagram.png",'
        b'"alt":"Flow","title":"Payment flow"}]}'
    )


def test_safe_url_filename_uses_title_or_path() -> None:
    assert safe_url_filename("https://example.com/docs/guide.html", "Product Guide", "text/html") == "Product_Guide.txt"
    assert safe_url_filename("https://example.com/files/spec.pdf", None, "application/pdf") == "spec.pdf"


class _FakeResult:
    def __init__(self, session: "_FakeSession") -> None:
        self.session = session

    def scalar_one(self):
        return self.session.added[-1]


class _FakeSession:
    def __init__(self) -> None:
        self.added = []
        self.statements = []

    def add(self, value) -> None:
        self.added.append(value)

    async def execute(self, statement):
        self.statements.append(statement)
        return _FakeResult(self)


class _FakeTenantSession:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class _FakeTemporal:
    def __init__(self) -> None:
        self.started = []

    async def start_workflow(self, workflow, input, **kwargs):
        self.started.append((workflow, input, kwargs))


async def test_add_url_document_persists_metadata_and_starts_ingestion(monkeypatch) -> None:
    fetched = FetchedUrlSource(
        requested_url="https://example.com/docs",
        final_url="https://example.com/docs",
        title="Example Docs",
        filename="Example_Docs.txt",
        content_type="text/plain; charset=utf-8",
        data=b"Source URL: https://example.com/docs\n\nHello docs",
        image_sources=[
            UrlImageSource(
                url="https://example.com/diagram.png",
                alt="Payment flow",
                title="",
            )
        ],
    )
    fake_session = _FakeSession()
    stored_objects = []
    temporal = _FakeTemporal()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(temporal=temporal)))

    async def fake_fetch(url: str) -> FetchedUrlSource:
        assert url == "https://example.com/docs"
        return fetched

    monkeypatch.setattr(documents_router, "fetch_url_source", fake_fetch)
    monkeypatch.setattr(
        documents_router,
        "tenant_session",
        lambda tenant_id: _FakeTenantSession(fake_session),
    )
    monkeypatch.setattr(
        documents_router.object_store,
        "put",
        lambda key, data, content_type: stored_objects.append((key, data, content_type)),
    )
    async def fake_invalidate(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(documents_router, "invalidate_semantic_cache", fake_invalidate)

    response = await documents_router.add_url_document(
        documents_router.AddUrlDocumentRequest(url="https://example.com/docs"),
        request,
        "tenant-a",
    )

    assert response.source_type == "url"
    assert response.source_url == "https://example.com/docs"
    assert response.source_title == "Example Docs"
    assert response.size_bytes == len(fetched.data)
    assert response.status == DocumentStatus.pending
    assert stored_objects[0][1] == fetched.data
    assert stored_objects[0][2] == "text/plain; charset=utf-8"
    assert stored_objects[1][0] == f"{stored_objects[0][0]}.url-images.json"
    assert stored_objects[1][1] == (
        b'{"images":[{"url":"https://example.com/diagram.png",'
        b'"alt":"Payment flow","title":""}]}'
    )
    assert stored_objects[1][2] == "application/json"
    assert temporal.started
    assert temporal.started[0][1].filename == "Example_Docs.txt"
    assert fake_session.added[0].source_type == "url"
    assert fake_session.added[0].source_checked_at.replace(tzinfo=UTC) <= datetime.now(UTC)
