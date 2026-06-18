from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest

_RUN_E2E = os.getenv("RUN_E2E_SMOKE", "").strip().lower() in {"1", "true", "yes"}
_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_API_BASE = "http://127.0.0.1:8000"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not _RUN_E2E,
        reason="set RUN_E2E_SMOKE=1 to run live API/Temporal/LLM smoke tests",
    ),
]


def _admin_secret() -> str:
    value = os.getenv("ADMIN_SECRET", "").strip()
    if value:
        return value

    env_file = _ROOT / ".env"
    if not env_file.exists():
        pytest.fail("ADMIN_SECRET is not set and .env was not found")

    for line in env_file.read_text().splitlines():
        if line.startswith("ADMIN_SECRET="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value:
                return value

    pytest.fail("ADMIN_SECRET is not set and was not found in .env")


def _create_api_key(client: httpx.Client, tenant_id: str) -> str:
    response = client.post(
        "/auth/keys",
        headers={"X-Admin-Secret": _admin_secret()},
        json={"tenant_id": tenant_id, "name": "e2e smoke"},
    )
    response.raise_for_status()
    return response.json()["raw_key"]


def _upload_text_document(
    client: httpx.Client,
    *,
    headers: dict[str, str],
    filename: str,
    content: str,
) -> str:
    response = client.post(
        "/documents",
        headers=headers,
        files={"file": (filename, content.encode("utf-8"), "text/plain")},
    )
    response.raise_for_status()
    return response.json()["id"]


def _wait_document_done(
    client: httpx.Client,
    *,
    headers: dict[str, str],
    document_id: str,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] | None = None

    while time.monotonic() < deadline:
        response = client.get(f"/documents/{document_id}", headers=headers)
        response.raise_for_status()
        payload = response.json()
        last_payload = payload
        if payload["status"] == "done":
            return payload
        if payload["status"] == "failed":
            pytest.fail(f"document {document_id} failed ingestion: {payload.get('error')}")
        time.sleep(2)

    pytest.fail(f"document {document_id} did not finish ingestion: {last_payload}")


def _read_sse_done(response: httpx.Response) -> dict[str, Any]:
    buffer = ""
    for chunk in response.iter_text():
        buffer += chunk
        while "\n\n" in buffer:
            raw_event, buffer = buffer.split("\n\n", 1)
            for line in raw_event.splitlines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if event.get("type") == "error":
                    pytest.fail(f"agent stream returned error: {event.get('message')}")
                if event.get("type") == "done":
                    return event

    pytest.fail("agent stream ended without a done event")


async def _delete_tenant_api_keys(tenant_id: str) -> None:
    from sqlalchemy import delete

    from packages.storage import ApiKey, async_session

    async with async_session() as session, session.begin():
        await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))


def test_document_upload_ingestion_scoped_stream_and_citations_smoke() -> None:
    api_base = os.getenv("E2E_API_BASE_URL", _DEFAULT_API_BASE).rstrip("/")
    tenant_id = f"e2e-smoke-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    target_document_id: str | None = None
    distractor_document_id: str | None = None

    with httpx.Client(base_url=api_base, timeout=httpx.Timeout(120.0)) as client:
        client.get("/health").raise_for_status()
        api_key = _create_api_key(client, tenant_id)
        headers = {"X-API-Key": api_key}

        try:
            target_document_id = _upload_text_document(
                client,
                headers=headers,
                filename="e2e-smoke-target.txt",
                content=(
                    "E2E smoke target document.\n"
                    "SMOKE_SENTINEL_ALPHA is owned by the Crimson Reliability Team.\n"
                    "The escalation channel is alpha-maintenance.\n"
                ),
            )
            distractor_document_id = _upload_text_document(
                client,
                headers=headers,
                filename="e2e-smoke-distractor.txt",
                content=(
                    "E2E smoke distractor document.\n"
                    "SMOKE_SENTINEL_BETA is owned by the Azure Support Team.\n"
                    "This document must not be cited for the alpha sentinel question.\n"
                ),
            )

            _wait_document_done(client, headers=headers, document_id=target_document_id)
            _wait_document_done(client, headers=headers, document_id=distractor_document_id)

            chunks_response = client.get(
                f"/documents/{target_document_id}/chunks",
                headers=headers,
            )
            chunks_response.raise_for_status()
            chunks = chunks_response.json()
            assert chunks, "target document should have indexed chunks"
            assert "SMOKE_SENTINEL_ALPHA" in chunks[0]["excerpt"]

            with client.stream(
                "POST",
                "/agent/stream",
                headers=headers,
                json={
                    "user_query": (
                        "Who owns SMOKE_SENTINEL_ALPHA? "
                        "Answer with the exact team name and include a citation marker."
                    ),
                    "document_id": target_document_id,
                },
            ) as response:
                response.raise_for_status()
                done = _read_sse_done(response)

            answer = done["answer"]
            sources = done["sources"]
            assert "Crimson" in answer
            assert sources, f"expected grounded citations, got answer={answer!r}"
            assert {source["document_id"] for source in sources} == {target_document_id}
            assert all(source["filename"] == "e2e-smoke-target.txt" for source in sources)
            assert done["cached"] is False

        finally:
            for document_id in (target_document_id, distractor_document_id):
                if document_id:
                    client.delete(f"/documents/{document_id}", headers=headers)
            asyncio.run(_delete_tenant_api_keys(tenant_id))
