from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from typing import Any

import httpx
import pytest
from PIL import Image, ImageDraw, ImageFont

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
        reason="set RUN_E2E_SMOKE=1 to run live API/Temporal/OCR smoke tests",
    ),
    pytest.mark.skipif(
        os.getenv("E2E_ALLOW_LOCAL_URL_SOURCES", "").strip().lower()
        not in {"1", "true", "yes"},
        reason="set E2E_ALLOW_LOCAL_URL_SOURCES=true and recreate api/worker containers",
    ),
]


def _fixture_png() -> bytes:
    image = Image.new("RGB", (1200, 520), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=58)
    lines = [
        "URL IMAGE SENTINEL ALPHA",
        "Diagram step: payment approved",
        "Router action: restart device",
    ]
    y = 90
    for line in lines:
        draw.text((80, y), line, fill="black", font=font)
        y += 95
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class _UrlImageFixtureHandler(BaseHTTPRequestHandler):
    png_bytes = _fixture_png()

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path == "/page.html":
            body = (
                "<!doctype html><html><head><title>URL image e2e fixture</title></head>"
                "<body>"
                "<h1>URL source fixture</h1>"
                "<p>URL_PAGE_TEXT_SENTINEL_BRAVO belongs to the live e2e fixture.</p>"
                '<img src="/diagram.png" width="1200" height="520" alt="Payment diagram">'
                "</body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/diagram.png":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(self.png_bytes)))
            self.end_headers()
            self.wfile.write(self.png_bytes)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, _format: str, *_args: Any) -> None:
        return


class _FixtureServer:
    def __init__(self) -> None:
        self.server = ThreadingHTTPServer(("0.0.0.0", 0), _UrlImageFixtureHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def container_url(self) -> str:
        return f"http://host.docker.internal:{self.server.server_port}/page.html"

    def __enter__(self) -> "_FixtureServer":
        self.thread.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _add_url_document(
    client: httpx.Client,
    *,
    headers: dict[str, str],
    url: str,
) -> str:
    response = client.post("/documents/url", headers=headers, json={"url": url})
    response.raise_for_status()
    return response.json()["id"]


def _combined_chunk_text(
    client: httpx.Client,
    *,
    headers: dict[str, str],
    document_id: str,
) -> str:
    response = client.get(
        f"/documents/{document_id}/chunks",
        headers=headers,
        params={"limit": 100},
    )
    response.raise_for_status()
    chunks = response.json()
    assert chunks, "URL document should have indexed chunks"
    return "\n".join(chunk["excerpt"] for chunk in chunks)


def test_url_source_ingests_hidden_image_text_from_local_fixture() -> None:
    api_base = os.getenv("E2E_API_BASE_URL", _DEFAULT_API_BASE).rstrip("/")
    tenant_id = f"e2e-url-image-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    document_id: str | None = None

    with _FixtureServer() as fixture, httpx.Client(
        base_url=api_base,
        timeout=httpx.Timeout(180.0),
    ) as client:
        client.get("/health").raise_for_status()
        api_key = _create_api_key(client, tenant_id)
        headers = {"X-API-Key": api_key}

        try:
            check = client.post(
                "/documents/url/check",
                headers=headers,
                json={"url": fixture.container_url},
            )
            check.raise_for_status()
            assert check.json()["ok"] is True

            document_id = _add_url_document(
                client,
                headers=headers,
                url=fixture.container_url,
            )
            _wait_document_done(
                client,
                headers=headers,
                document_id=document_id,
                timeout_seconds=240,
            )

            chunk_text = _combined_chunk_text(
                client,
                headers=headers,
                document_id=document_id,
            )
            assert "URL_PAGE_TEXT_SENTINEL_BRAVO" in chunk_text
            assert "URL IMAGE SENTINEL ALPHA" in " ".join(chunk_text.upper().split())

            assets_response = client.get(f"/documents/{document_id}/assets", headers=headers)
            assets_response.raise_for_status()
            assets = assets_response.json()
            assert len(assets) == 1
            assert assets[0]["status"] == "done"
            assert assets[0]["preview_available"] is False
            assert "URL IMAGE SENTINEL ALPHA" in " ".join(
                f"{assets[0]['ocr_text']} {assets[0]['vision_description']}".upper().split()
            )
            preview = client.get(
                f"/documents/{document_id}/assets/{assets[0]['id']}/content",
                headers=headers,
            )
            assert preview.status_code == 404
        finally:
            if document_id:
                client.delete(f"/documents/{document_id}", headers=headers)
            asyncio.run(_delete_tenant_api_keys(tenant_id))
