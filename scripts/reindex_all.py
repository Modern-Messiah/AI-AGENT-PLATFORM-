#!/usr/bin/env python3
"""Reindex every document through the API — one ingestion at a time.

Usage:
    uv run python scripts/reindex_all.py --api-base http://localhost:8000 \
        --api-key <raw-tenant-key> [--timeout-minutes 15]

Intended for the embedding-model switch (see
docs/runbooks/reindex-after-embedding-change.md): sequentially calls
POST /documents/{id}/reindex and waits for `done`/`failed` before the next
document, because OCR/Vision ingestion is CPU-heavy.
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True, help="e.g. http://localhost:8000")
    parser.add_argument("--api-key", required=True, help="raw tenant API key (X-API-Key)")
    parser.add_argument(
        "--timeout-minutes",
        type=float,
        default=15.0,
        help="per-document wait for ingestion to finish (default: 15)",
    )
    parser.add_argument(
        "--poll-seconds", type=float, default=5.0, help="status poll interval (default: 5)"
    )
    args = parser.parse_args()

    client = httpx.Client(
        base_url=args.api_base.rstrip("/"),
        headers={"X-API-Key": args.api_key},
        timeout=30.0,
    )

    items: list[dict] = []
    offset = 0
    while True:
        page = client.get("/documents", params={"limit": 500, "offset": offset}).json()
        page = page if isinstance(page, list) else page.get("items", [])
        items.extend(page)
        if len(page) < 500:
            break
        offset += 500
    if not items:
        print("no documents found for this tenant")
        return 0

    print(f"reindexing {len(items)} document(s), one at a time…")
    failed: list[str] = []
    for i, doc in enumerate(items, start=1):
        doc_id = doc["id"]
        name = doc.get("filename") or doc_id
        try:
            resp = client.post(f"/documents/{doc_id}/reindex")
            resp.raise_for_status()
            body = resp.json()
            if not body.get("workflow_started"):
                print(f"[{i}/{len(items)}] {name}: no changes, skipped")
                continue
        except httpx.HTTPError as exc:
            print(f"[{i}/{len(items)}] {name}: reindex request failed: {exc}")
            failed.append(name)
            continue

        deadline = time.monotonic() + args.timeout_minutes * 60
        status = "processing"
        while time.monotonic() < deadline:
            time.sleep(args.poll_seconds)
            doc_state = client.get(f"/documents/{doc_id}").json()
            status = doc_state.get("status", status)
            if status in {"done", "failed"}:
                break
        if status == "done":
            print(f"[{i}/{len(items)}] {name}: done")
        elif status == "failed":
            print(
                f"[{i}/{len(items)}] {name}: FAILED — {doc_state.get('error') or 'unknown error'}"
            )
            failed.append(name)
        else:
            print(f"[{i}/{len(items)}] {name}: still processing after timeout, moving on")
            failed.append(name)

    if failed:
        print(f"\n{len(failed)} document(s) did not finish: {', '.join(failed)}")
        return 1
    print("\nall documents reindexed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
