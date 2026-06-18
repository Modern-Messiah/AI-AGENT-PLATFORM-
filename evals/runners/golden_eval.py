"""Golden RAG/OCR/Vision eval runner.

Default usage runs both prepare and retrieval eval:

    PYTHONPATH=$PWD python -m evals.runners.golden_eval

URL-image cases require API/worker containers recreated with:

    E2E_ALLOW_LOCAL_URL_SOURCES=true docker compose up -d api worker
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
from packages.rag import retrieve_chunks
from packages.storage import ApiKey, async_session
from sqlalchemy import delete

from evals.golden.suite import (
    CaseResult,
    EvalChunk,
    FixtureArtifact,
    evaluate_case,
    generate_fixture_files,
    load_golden_cases,
    summarize_results,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_API_BASE = "http://127.0.0.1:8000"
DEFAULT_OUTPUT_DIR = ROOT / ".tmp" / "evals" / "golden"


class _QuietDirectoryHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: Any) -> None:
        return


class FixtureServer:
    def __init__(self, directory: Path) -> None:
        handler = partial(_QuietDirectoryHandler, directory=str(directory))
        self.server = ThreadingHTTPServer(("0.0.0.0", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def url_for(self, path: Path) -> str:
        return f"http://host.docker.internal:{self.server.server_port}/{path.name}"

    def __enter__(self) -> "FixtureServer":
        self.thread.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _read_env_value(name: str, env_file: Path = ROOT / ".env") -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _create_api_key(client: httpx.Client, tenant_id: str) -> str:
    admin_secret = _read_env_value("ADMIN_SECRET")
    if not admin_secret:
        raise RuntimeError("ADMIN_SECRET is required to create a disposable eval API key")
    response = client.post(
        "/auth/keys",
        headers={"X-Admin-Secret": admin_secret},
        json={"tenant_id": tenant_id, "name": "golden eval"},
    )
    response.raise_for_status()
    return str(response.json()["raw_key"])


async def _delete_tenant_api_keys(tenant_id: str) -> None:
    async with async_session() as session, session.begin():
        await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))


def _upload_file_artifact(
    client: httpx.Client,
    *,
    headers: dict[str, str],
    artifact: FixtureArtifact,
) -> dict[str, Any]:
    with artifact.path.open("rb") as handle:
        response = client.post(
            "/documents",
            headers=headers,
            files={
                "file": (
                    artifact.path.name,
                    handle,
                    artifact.content_type,
                )
            },
        )
    response.raise_for_status()
    return response.json()


def _upload_url_artifact(
    client: httpx.Client,
    *,
    headers: dict[str, str],
    url: str,
) -> dict[str, Any]:
    response = client.post("/documents/url", headers=headers, json={"url": url})
    if response.status_code >= 400:
        raise RuntimeError(
            "URL source upload failed. For local golden URL-image evals, recreate "
            "api and worker with E2E_ALLOW_LOCAL_URL_SOURCES=true. "
            f"Response: {response.status_code} {response.text}"
        )
    return response.json()


def _wait_document_done(
    client: httpx.Client,
    *,
    headers: dict[str, str],
    document_id: str,
    timeout_seconds: int,
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
            raise RuntimeError(f"document {document_id} failed ingestion: {payload.get('error')}")
        time.sleep(2)
    raise TimeoutError(f"document {document_id} did not finish ingestion: {last_payload}")


def prepare_golden_corpus(
    *,
    api_base: str,
    tenant_id: str,
    output_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    fixtures_dir = output_dir / "fixtures"
    artifacts = generate_fixture_files(fixtures_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"

    with httpx.Client(base_url=api_base, timeout=httpx.Timeout(180.0)) as client:
        client.get("/health").raise_for_status()
        api_key = _create_api_key(client, tenant_id)
        headers = {"X-API-Key": api_key}
        sources: dict[str, dict[str, Any]] = {}

        with FixtureServer(fixtures_dir) as fixture_server:
            for source_id, artifact in artifacts.items():
                print(f"Preparing {source_id} ...", flush=True)
                if artifact.upload_kind == "url":
                    payload = _upload_url_artifact(
                        client,
                        headers=headers,
                        url=fixture_server.url_for(artifact.path),
                    )
                else:
                    payload = _upload_file_artifact(client, headers=headers, artifact=artifact)
                done_payload = _wait_document_done(
                    client,
                    headers=headers,
                    document_id=payload["id"],
                    timeout_seconds=timeout_seconds,
                )
                sources[source_id] = {
                    "document_id": payload["id"],
                    "filename": done_payload["filename"],
                    "source_type": done_payload.get("source_type", "file"),
                }

    manifest = {
        "tenant_id": tenant_id,
        "api_base": api_base,
        "created_at": datetime.now(UTC).isoformat(),
        "sources": sources,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest written to {manifest_path}")
    return manifest


def _load_manifest(output_dir: Path) -> dict[str, Any]:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"{manifest_path} not found. Run with --prepare first or use the default prepare+run mode."
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _eval_chunks_from_retrieved(
    chunks: list[Any],
    *,
    source_by_document_id: dict[str, str],
) -> list[EvalChunk]:
    eval_chunks: list[EvalChunk] = []
    for chunk in chunks:
        metadata = chunk.metadata or {}
        raw_page = metadata.get("page")
        page = raw_page if isinstance(raw_page, int) and raw_page > 0 else None
        raw_asset_kind = metadata.get("asset_kind")
        asset_kind = raw_asset_kind if isinstance(raw_asset_kind, str) else None
        eval_chunks.append(
            EvalChunk(
                source_id=source_by_document_id.get(chunk.document_id),
                document_id=chunk.document_id,
                filename=chunk.filename,
                content=chunk.content,
                score=chunk.score,
                page=page,
                asset_kind=asset_kind,
            )
        )
    return eval_chunks


async def run_golden_retrieval_eval(
    *,
    tenant_id: str,
    output_dir: Path,
    top_k: int,
) -> tuple[dict[str, object], list[CaseResult]]:
    manifest = _load_manifest(output_dir)
    source_by_document_id = {
        str(payload["document_id"]): source_id
        for source_id, payload in manifest["sources"].items()
    }
    results: list[CaseResult] = []

    for case in load_golden_cases():
        chunks = await retrieve_chunks(str(case["query"]), tenant_id, k=top_k)
        eval_chunks = _eval_chunks_from_retrieved(
            chunks,
            source_by_document_id=source_by_document_id,
        )
        result = evaluate_case(case, eval_chunks)
        results.append(result)
        status = "PASS" if result.passed else "FAIL"
        print(f"{status} {result.case_id}: {', '.join(result.failures) or 'ok'}")

    summary = summarize_results(results)
    report = {
        "tenant_id": tenant_id,
        "created_at": datetime.now(UTC).isoformat(),
        "summary": summary,
        "cases": [result.to_dict() for result in results],
    }
    report_path = output_dir / "golden-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSummary: {summary['passed']}/{summary['total']} passed")
    print(f"Report written to {report_path}")
    return summary, results


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the golden RAG/OCR/Vision eval suite.")
    parser.add_argument("--api", default=DEFAULT_API_BASE, help="API base URL")
    parser.add_argument("--tenant", default="", help="Tenant id to use; generated when omitted")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--prepare", action="store_true", help="Generate/upload golden sources")
    parser.add_argument("--run", action="store_true", help="Run retrieval eval against prepared corpus")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--cleanup-keys", action="store_true", help="Delete eval tenant API keys after run")
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    do_prepare = args.prepare or not args.run
    do_run = args.run or not args.prepare
    tenant_id = args.tenant or f"golden-eval-{int(time.time())}-{uuid.uuid4().hex[:8]}"

    if do_prepare:
        prepare_golden_corpus(
            api_base=str(args.api).rstrip("/"),
            tenant_id=tenant_id,
            output_dir=args.output_dir,
            timeout_seconds=args.timeout_seconds,
        )
    elif not args.tenant:
        manifest = _load_manifest(args.output_dir)
        tenant_id = str(manifest["tenant_id"])

    exit_code = 0
    if do_run:
        summary, _results = await run_golden_retrieval_eval(
            tenant_id=tenant_id,
            output_dir=args.output_dir,
            top_k=args.top_k,
        )
        exit_code = 0 if summary["failed"] == 0 else 1

    if args.cleanup_keys:
        await _delete_tenant_api_keys(tenant_id)

    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
