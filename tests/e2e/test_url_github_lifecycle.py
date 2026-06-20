from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest

from tests.e2e.test_smoke import (
    _DEFAULT_API_BASE,
    _RUN_E2E,
    _create_api_key,
    _delete_tenant_api_keys,
    _wait_document_done,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not _RUN_E2E,
        reason="set RUN_E2E_SMOKE=1 to run live source lifecycle tests",
    ),
]


class _MutableUrlFixtureHandler(BaseHTTPRequestHandler):
    sentinel = "URL_LIFECYCLE_SENTINEL_ALPHA"

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path == "/source.html":
            body = (
                "<!doctype html><html><head><title>Mutable URL lifecycle</title></head>"
                "<body>"
                "<h1>Mutable URL source</h1>"
                f"<p>{self.sentinel} belongs to source lifecycle e2e.</p>"
                "</body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, _format: str, *_args: Any) -> None:
        return


class _MutableFixtureServer:
    def __init__(self) -> None:
        self.server = ThreadingHTTPServer(("0.0.0.0", 0), _MutableUrlFixtureHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def container_url(self) -> str:
        return f"http://host.docker.internal:{self.server.server_port}/source.html"

    def set_sentinel(self, value: str) -> None:
        _MutableUrlFixtureHandler.sentinel = value

    def __enter__(self) -> "_MutableFixtureServer":
        self.thread.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def _add_url_document(client: httpx.Client, headers: dict[str, str], url: str) -> str:
    response = client.post("/documents/url", headers=headers, json={"url": url})
    response.raise_for_status()
    return str(response.json()["id"])


def _chunk_text(client: httpx.Client, headers: dict[str, str], document_id: str) -> str:
    response = client.get(
        f"/documents/{document_id}/chunks",
        headers=headers,
        params={"limit": 100},
    )
    response.raise_for_status()
    chunks = response.json()
    assert chunks, "document should have indexed chunks"
    return "\n".join(str(chunk["excerpt"]) for chunk in chunks)


def _reindex(client: httpx.Client, headers: dict[str, str], document_id: str) -> dict[str, Any]:
    response = client.post(f"/documents/{document_id}/reindex", headers=headers)
    response.raise_for_status()
    return response.json()


@pytest.mark.skipif(
    os.getenv("E2E_ALLOW_LOCAL_URL_SOURCES", "").strip().lower()
    not in {"1", "true", "yes"},
    reason="set E2E_ALLOW_LOCAL_URL_SOURCES=true and recreate api/worker containers",
)
def test_url_source_reindex_detects_no_change_then_change_and_delete() -> None:
    api_base = os.getenv("E2E_API_BASE_URL", _DEFAULT_API_BASE).rstrip("/")
    tenant_id = f"e2e-url-lifecycle-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    document_id: str | None = None

    with _MutableFixtureServer() as fixture, httpx.Client(
        base_url=api_base,
        timeout=httpx.Timeout(180.0),
    ) as client:
        client.get("/health").raise_for_status()
        api_key = _create_api_key(client, tenant_id)
        headers = _headers(api_key)

        try:
            check = client.post(
                "/documents/url/check",
                headers=headers,
                json={"url": fixture.container_url},
            )
            check.raise_for_status()
            check_payload = check.json()
            assert check_payload["ok"] is True
            assert check_payload["source_type"] == "url"

            document_id = _add_url_document(client, headers, fixture.container_url)
            _wait_document_done(client, headers=headers, document_id=document_id)
            assert "URL_LIFECYCLE_SENTINEL_ALPHA" in _chunk_text(client, headers, document_id)

            no_change = _reindex(client, headers, document_id)
            assert no_change["changed"] is False
            assert no_change["workflow_started"] is False

            fixture.set_sentinel("URL_LIFECYCLE_SENTINEL_BRAVO")
            changed = _reindex(client, headers, document_id)
            assert changed["changed"] is True
            assert changed["workflow_started"] is True
            _wait_document_done(client, headers=headers, document_id=document_id)
            chunk_text = _chunk_text(client, headers, document_id)
            assert "URL_LIFECYCLE_SENTINEL_BRAVO" in chunk_text
            assert "URL_LIFECYCLE_SENTINEL_ALPHA" not in chunk_text

            delete_response = client.delete(f"/documents/{document_id}", headers=headers)
            assert delete_response.status_code == 204
            document_id = None
        finally:
            if document_id:
                client.delete(f"/documents/{document_id}", headers=headers)
            asyncio.run(_delete_tenant_api_keys(tenant_id))


@pytest.mark.skipif(
    os.getenv("RUN_E2E_GITHUB", "").strip().lower() not in {"1", "true", "yes"},
    reason="set RUN_E2E_GITHUB=1 with E2E_GITHUB_URL and E2E_GITHUB_EXPECTED_SUBSTRING",
)
def test_github_source_lifecycle_no_change_reindex_and_delete() -> None:
    github_url = os.getenv("E2E_GITHUB_URL", "").strip()
    expected = os.getenv("E2E_GITHUB_EXPECTED_SUBSTRING", "").strip()
    if not github_url or not expected:
        pytest.skip("E2E_GITHUB_URL and E2E_GITHUB_EXPECTED_SUBSTRING are required")

    api_base = os.getenv("E2E_API_BASE_URL", _DEFAULT_API_BASE).rstrip("/")
    tenant_id = f"e2e-github-lifecycle-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    document_id: str | None = None

    with httpx.Client(base_url=api_base, timeout=httpx.Timeout(240.0)) as client:
        client.get("/health").raise_for_status()
        api_key = _create_api_key(client, tenant_id)
        headers = _headers(api_key)

        try:
            check = client.post("/documents/url/check", headers=headers, json={"url": github_url})
            check.raise_for_status()
            check_payload = check.json()
            assert check_payload["ok"] is True
            assert check_payload["source_type"] == "github"
            assert check_payload["file_count"] >= 1

            document_id = _add_url_document(client, headers, github_url)
            _wait_document_done(client, headers=headers, document_id=document_id, timeout_seconds=300)
            assert expected in _chunk_text(client, headers, document_id)

            no_change = _reindex(client, headers, document_id)
            assert no_change["changed"] is False
            assert no_change["workflow_started"] is False

            delete_response = client.delete(f"/documents/{document_id}", headers=headers)
            assert delete_response.status_code == 204
            document_id = None
        finally:
            if document_id:
                client.delete(f"/documents/{document_id}", headers=headers)
            asyncio.run(_delete_tenant_api_keys(tenant_id))
