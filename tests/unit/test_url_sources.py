from __future__ import annotations

import io
import logging
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
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
        (path, method.upper())
        for path, methods in app.openapi()["paths"].items()
        for method in methods
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
        source_type="url",
    )

    assert response.ok is True
    assert response.title == "Example Docs"
    assert response.source_type == "url"


def test_github_url_check_response_schema() -> None:
    response = UrlCheckResponse(
        ok=True,
        url="https://github.com/acme/docs",
        final_url="https://github.com/acme/docs",
        content_type="text/plain; charset=utf-8",
        title="GitHub: acme/docs",
        size_bytes=2048,
        source_type="github",
        file_count=12,
        preview_files=["README.md", "docs/install.md"],
    )

    assert response.source_type == "github"
    assert response.file_count == 12
    assert response.preview_files == ["README.md", "docs/install.md"]


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


async def test_fetch_url_source_sends_project_user_agent(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_validate(url: str) -> str:
        return url

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url: str):
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=b"<html><body><main><p>Hello from docs.</p></main></body></html>",
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(url_sources, "validate_fetch_url", fake_validate)
    monkeypatch.setattr(url_sources.httpx, "AsyncClient", FakeAsyncClient)

    fetched = await url_sources.fetch_url_source("https://docs.example.com/page")

    user_agent = (captured.get("headers") or {}).get("User-Agent", "")
    assert user_agent.startswith("AI-Agent-Platform/")
    assert "Hello from docs." in fetched.data.decode()


async def test_fetch_github_blob_source_uses_raw_file_without_github_api(monkeypatch) -> None:
    requested_urls: list[str] = []

    async def fake_validate(url: str) -> str:
        return url

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url: str):
            requested_urls.append(url)
            return httpx.Response(
                200,
                headers={"content-type": "text/plain; charset=utf-8"},
                content=b"# Project docs\n\nInstall with docker compose.",
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(url_sources, "validate_fetch_url", fake_validate)
    monkeypatch.setattr(url_sources.httpx, "AsyncClient", FakeAsyncClient)

    fetched = await url_sources.fetch_url_source(
        "https://github.com/acme/docs/blob/main/README.md"
    )
    text = fetched.data.decode()

    assert requested_urls == ["https://raw.githubusercontent.com/acme/docs/main/README.md"]
    assert fetched.source_type == "github"
    assert fetched.title == "GitHub: acme/docs"
    assert fetched.filename == "GitHub_acme_docs.txt"
    assert fetched.discovered_files == ["README.md"]
    assert "GitHub Repository: acme/docs" in text
    assert "--- FILE: README.md ---" in text
    assert "Install with docker compose." in text
    assert "api.github.com" not in "".join(requested_urls)


async def test_fetch_github_blob_collects_markdown_image_sources(monkeypatch) -> None:
    async def fake_validate(url: str) -> str:
        return url

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url: str):
            return httpx.Response(
                200,
                headers={"content-type": "text/plain; charset=utf-8"},
                content=(
                    b"# Project docs\n\n"
                    b"![Payment flow](docs/payment-flow.png)\n"
                    b"![Build badge](https://img.shields.io/badge/build-passing.svg)\n"
                    b'<img src="assets/table.webp" alt="Tariff table" title="Table">'
                ),
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(url_sources, "validate_fetch_url", fake_validate)
    monkeypatch.setattr(url_sources.httpx, "AsyncClient", FakeAsyncClient)

    fetched = await url_sources.fetch_url_source(
        "https://github.com/acme/docs/blob/main/README.md"
    )

    assert fetched.image_sources == [
        UrlImageSource(
            url="https://raw.githubusercontent.com/acme/docs/main/docs/payment-flow.png",
            alt="Payment flow",
            title="",
        ),
        UrlImageSource(
            url="https://raw.githubusercontent.com/acme/docs/main/assets/table.webp",
            alt="Tariff table",
            title="Table",
        ),
    ]


async def test_fetch_github_blob_resolves_root_relative_html_images(monkeypatch) -> None:
    async def fake_validate(url: str) -> str:
        return url

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url: str):
            return httpx.Response(
                200,
                headers={"content-type": "text/plain; charset=utf-8"},
                content=(
                    b"# Project docs\n\n"
                    b'<img src="/img/tutorial/payment.png" alt="Payment flow">'
                ),
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(url_sources, "validate_fetch_url", fake_validate)
    monkeypatch.setattr(url_sources.httpx, "AsyncClient", FakeAsyncClient)

    fetched = await url_sources.fetch_url_source(
        "https://github.com/acme/docs/blob/main/docs/README.md"
    )

    assert fetched.image_sources == [
        UrlImageSource(
            url="https://raw.githubusercontent.com/acme/docs/main/img/tutorial/payment.png",
            alt="Payment flow",
            title="",
        )
    ]


async def test_fetch_github_blob_ignores_unsupported_raw_svg_images(monkeypatch) -> None:
    async def fake_validate(url: str) -> str:
        return url

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url: str):
            return httpx.Response(
                200,
                headers={"content-type": "text/plain; charset=utf-8"},
                content=(
                    b"# Project docs\n\n"
                    b"![Vector](https://raw.githubusercontent.com/acme/docs/refs/heads/stable/diagram.svg)\n"
                    b"![Diagram](https://github.com/acme/docs/blob/main/docs/diagram.png)\n"
                ),
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(url_sources, "validate_fetch_url", fake_validate)
    monkeypatch.setattr(url_sources.httpx, "AsyncClient", FakeAsyncClient)

    fetched = await url_sources.fetch_url_source(
        "https://github.com/acme/docs/blob/main/README.md"
    )

    assert fetched.image_sources == [
        UrlImageSource(
            url="https://raw.githubusercontent.com/acme/docs/main/docs/diagram.png",
            alt="Diagram",
            title="",
        )
    ]


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


async def test_fetch_github_tree_source_filters_archive_path_and_noise(monkeypatch) -> None:
    requested_urls: list[str] = []
    archive = _zip_bytes(
        {
            "docs-main/README.md": b"# Root readme\n",
            "docs-main/docs/install.md": b"# Install\nUse docker compose up.",
            "docs-main/docs/assets/logo.png": b"not useful",
            "docs-main/docs/node_modules/pkg/README.md": b"skip dependency",
            "docs-main/src/main.py": b"print('skip source code for default docs import')",
        }
    )

    async def fake_validate(url: str) -> str:
        return url

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url: str):
            requested_urls.append(url)
            return httpx.Response(
                200,
                headers={"content-type": "application/zip"},
                content=archive,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(url_sources, "validate_fetch_url", fake_validate)
    monkeypatch.setattr(url_sources.httpx, "AsyncClient", FakeAsyncClient)

    fetched = await url_sources.fetch_url_source(
        "https://github.com/acme/docs/tree/main/docs"
    )
    text = fetched.data.decode()

    assert requested_urls == ["https://codeload.github.com/acme/docs/zip/refs/heads/main"]
    assert fetched.source_type == "github"
    assert fetched.discovered_files == ["docs/install.md"]
    assert "--- FILE: docs/install.md ---" in text
    assert "Use docker compose up." in text
    assert "Root readme" not in text
    assert "skip dependency" not in text
    assert "skip source code" not in text


async def test_fetch_github_tree_collects_markdown_image_sources(monkeypatch) -> None:
    archive = _zip_bytes(
        {
            "docs-main/docs/install.md": (
                b"# Install\n"
                b"![Network diagram](../assets/network.png \"Topology\")\n"
                b".. image:: ../assets/rst-flow.jpg\n"
            ),
            "docs-main/assets/network.png": b"not indexed as text",
            "docs-main/assets/rst-flow.jpg": b"not indexed as text",
            "docs-main/dist/README.md": b"![Noise](../assets/noise.png)",
        }
    )

    async def fake_validate(url: str) -> str:
        return url

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url: str):
            return httpx.Response(
                200,
                headers={"content-type": "application/zip"},
                content=archive,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(url_sources, "validate_fetch_url", fake_validate)
    monkeypatch.setattr(url_sources.httpx, "AsyncClient", FakeAsyncClient)

    fetched = await url_sources.fetch_url_source(
        "https://github.com/acme/docs/tree/main/docs"
    )

    assert fetched.image_sources == [
        UrlImageSource(
            url="https://raw.githubusercontent.com/acme/docs/main/assets/network.png",
            alt="Network diagram",
            title="Topology",
        ),
        UrlImageSource(
            url="https://raw.githubusercontent.com/acme/docs/main/assets/rst-flow.jpg",
            alt="",
            title="",
        ),
    ]


async def test_fetch_github_repo_indexes_architecture_diagram_sources(monkeypatch) -> None:
    archive = _zip_bytes(
        {
            "repo-main/README.md": (
                b"# Project\n\n"
                b"Architecture docs live in docs/architecture/c4.\n"
            ),
            "repo-main/docs/architecture/c4/L1 - System Context/docs.md": (
                b"# C4 docs\n\n![System context](L1_system_context.png)\n"
            ),
            "repo-main/docs/architecture/c4/L1 - System Context/L1_system_context.png": (
                b"not indexed as text"
            ),
            "repo-main/docs/architecture/c4/L1 - System Context/L1_system_context.puml": (
                b"@startuml\n"
                b"!include <C4/C4_Context>\n"
                b'Person(user, "Investor")\n'
                b'System(api, "Crypto Sentiment Pulse API")\n'
                b'Rel(user, api, "Reads market sentiment")\n'
                b"@enduml\n"
            ),
        }
    )

    async def fake_validate(url: str) -> str:
        return url

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url: str):
            return httpx.Response(
                200,
                headers={"content-type": "application/zip"},
                content=archive,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(url_sources, "validate_fetch_url", fake_validate)
    monkeypatch.setattr(url_sources.httpx, "AsyncClient", FakeAsyncClient)

    fetched = await url_sources.fetch_url_source("https://github.com/acme/repo")
    text = fetched.data.decode()

    assert "docs/architecture/c4/L1 - System Context/L1_system_context.puml" in fetched.discovered_files
    assert "--- FILE: docs/architecture/c4/L1 - System Context/L1_system_context.puml ---" in text
    assert 'System(api, "Crypto Sentiment Pulse API")' in text
    assert 'Rel(user, api, "Reads market sentiment")' in text
    assert fetched.image_sources == []


async def test_fetch_github_tree_keeps_more_architecture_images(monkeypatch) -> None:
    archive_entries = {
        "repo-main/docs/architecture/c4/docs.md": "\n".join(
            f"![Diagram {idx}](diagram-{idx}.png)" for idx in range(1, 13)
        ).encode()
    }
    archive_entries.update(
        {f"repo-main/docs/architecture/c4/diagram-{idx}.png": b"image" for idx in range(1, 13)}
    )
    archive = _zip_bytes(archive_entries)

    async def fake_validate(url: str) -> str:
        return url

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url: str):
            return httpx.Response(
                200,
                headers={"content-type": "application/zip"},
                content=archive,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(url_sources, "validate_fetch_url", fake_validate)
    monkeypatch.setattr(url_sources.httpx, "AsyncClient", FakeAsyncClient)

    fetched = await url_sources.fetch_url_source(
        "https://github.com/acme/repo/tree/main/docs/architecture/c4"
    )

    assert len(fetched.image_sources) == 12
    assert fetched.image_sources[-1] == UrlImageSource(
        url="https://raw.githubusercontent.com/acme/repo/main/docs/architecture/c4/diagram-12.png",
        alt="Diagram 12",
        title="",
    )


async def test_fetch_github_tree_skips_paired_diagram_images_when_source_is_indexed(monkeypatch) -> None:
    archive = _zip_bytes(
        {
            "repo-main/docs/architecture/c4/L2_container.puml": (
                b"@startuml\n"
                b'Container(api, "Backend API")\n'
                b"@enduml\n"
            ),
            "repo-main/docs/architecture/c4/L2_container.png": b"paired rendered diagram",
            "repo-main/docs/architecture/c4/logo.png": b"nearby noise without diagram source",
            "repo-main/docs/architecture/c4/random-screenshot.png": b"nearby image without matching stem",
        }
    )

    async def fake_validate(url: str) -> str:
        return url

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url: str):
            return httpx.Response(
                200,
                headers={"content-type": "application/zip"},
                content=archive,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(url_sources, "validate_fetch_url", fake_validate)
    monkeypatch.setattr(url_sources.httpx, "AsyncClient", FakeAsyncClient)

    fetched = await url_sources.fetch_url_source(
        "https://github.com/acme/repo/tree/main/docs/architecture/c4"
    )

    assert fetched.image_sources == []


async def test_fetch_github_tree_resolves_root_relative_images_from_tree_root(monkeypatch) -> None:
    archive = _zip_bytes(
        {
            "docs-main/docs/guide.md": (
                b"# Guide\n"
                b'<img src="/img/tutorial/payment.png" alt="Payment flow">'
            ),
        }
    )

    async def fake_validate(url: str) -> str:
        return url

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url: str):
            return httpx.Response(
                200,
                headers={"content-type": "application/zip"},
                content=archive,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(url_sources, "validate_fetch_url", fake_validate)
    monkeypatch.setattr(url_sources.httpx, "AsyncClient", FakeAsyncClient)

    fetched = await url_sources.fetch_url_source(
        "https://github.com/acme/docs/tree/main/docs"
    )

    assert fetched.image_sources == [
        UrlImageSource(
            url="https://raw.githubusercontent.com/acme/docs/main/docs/img/tutorial/payment.png",
            alt="Payment flow",
            title="",
        )
    ]


async def test_fetch_github_repo_root_tries_main_then_master(monkeypatch) -> None:
    requested_urls: list[str] = []
    archive = _zip_bytes(
        {
            "docs-master/README.md": b"# Docs\n",
            "docs-master/docs/usage.md": b"# Usage\nAsk questions.",
            "docs-master/package.json": b'{"scripts":{"test":"pytest"}}',
            "docs-master/dist/README.md": b"skip built artifact",
        }
    )

    async def fake_validate(url: str) -> str:
        return url

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url: str):
            requested_urls.append(url)
            status = 404 if url.endswith("/main") else 200
            content = b"" if status == 404 else archive
            return httpx.Response(
                status,
                headers={"content-type": "application/zip"},
                content=content,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(url_sources, "validate_fetch_url", fake_validate)
    monkeypatch.setattr(url_sources.httpx, "AsyncClient", FakeAsyncClient)

    fetched = await url_sources.fetch_url_source("https://github.com/acme/docs")
    text = fetched.data.decode()

    assert requested_urls == [
        "https://codeload.github.com/acme/docs/zip/refs/heads/main",
        "https://codeload.github.com/acme/docs/zip/refs/heads/master",
    ]
    assert fetched.source_type == "github"
    assert fetched.discovered_files == ["README.md", "docs/usage.md", "package.json"]
    assert "Ref: master" in text
    assert "--- FILE: README.md ---" in text
    assert "--- FILE: docs/usage.md ---" in text
    assert "--- FILE: package.json ---" in text
    assert "skip built artifact" not in text


async def test_fetch_github_tree_allows_large_archive_when_filtered_text_is_small(monkeypatch) -> None:
    requested_urls: list[str] = []
    archive = _zip_bytes(
        {
            "repo-main/docs/guide.md": b"# Guide\nSmall useful docs.",
            "repo-main/dist/large-build.txt": b"x" * 2048,
        }
    )

    async def fake_validate(url: str) -> str:
        return url

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url: str):
            requested_urls.append(url)
            return httpx.Response(
                200,
                headers={"content-type": "application/zip"},
                content=archive,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(url_sources.settings, "url_source_max_bytes", 512)
    monkeypatch.setattr(url_sources, "validate_fetch_url", fake_validate)
    monkeypatch.setattr(url_sources.httpx, "AsyncClient", FakeAsyncClient)

    fetched = await url_sources.fetch_url_source(
        "https://github.com/example/repo/tree/main/docs"
    )
    text = fetched.data.decode()

    assert requested_urls == ["https://codeload.github.com/example/repo/zip/refs/heads/main"]
    assert fetched.discovered_files == ["docs/guide.md"]
    assert "Small useful docs." in text
    assert "large-build" not in text


async def test_check_url_document_returns_github_metadata(monkeypatch) -> None:
    fetched = FetchedUrlSource(
        requested_url="https://github.com/acme/docs",
        final_url="https://github.com/acme/docs",
        title="GitHub: acme/docs",
        filename="GitHub_acme_docs.txt",
        content_type="text/plain; charset=utf-8",
        data=b"GitHub Repository: acme/docs",
        image_sources=[
            UrlImageSource(url="https://raw.githubusercontent.com/acme/docs/main/diagram.png"),
            UrlImageSource(url="https://raw.githubusercontent.com/acme/docs/main/screenshot.webp"),
        ],
        source_type="github",
        discovered_files=["README.md", "docs/install.md", "docs/usage.md"],
    )

    async def fake_fetch(url: str) -> FetchedUrlSource:
        assert url == "https://github.com/acme/docs"
        return fetched

    monkeypatch.setattr(documents_router, "fetch_url_source", fake_fetch)

    response = await documents_router.check_url_document(
        documents_router.UrlCheckRequest(url="https://github.com/acme/docs"),
        "tenant-a",
    )

    assert response.ok is True
    assert response.source_type == "github"
    assert response.file_count == 3
    assert response.image_count == 2
    assert response.preview_files == ["README.md", "docs/install.md", "docs/usage.md"]


class _FakeResult:
    def __init__(self, session: _FakeSession) -> None:
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
