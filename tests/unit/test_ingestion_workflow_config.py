from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_SOURCE = ROOT / "apps/worker/workflows/ingestion.py"


def test_text_ingestion_uses_single_activity_to_keep_temporal_payloads_small() -> None:
    source = WORKFLOW_SOURCE.read_text(encoding="utf-8")
    patch_marker = 'if workflow.patched("text-ingestion-inline-store-v1"):'
    legacy_marker = "parsed = await workflow.execute_activity("

    assert patch_marker in source, "Inline text ingestion patch missing in workflow"
    assert legacy_marker in source, "Legacy workflow fallback block missing in workflow"

    start = source.index(patch_marker)
    end = source.index(legacy_marker, start)
    block = source[start:end]

    assert "ingest_text_document" in block
    assert "parse_document" not in block
    assert "chunk_and_embed" not in block
    assert "store_chunks" not in block
    assert "start_to_close_timeout=timedelta(minutes=42)" in block
    assert "heartbeat_timeout=timedelta(minutes=2)" in block


def test_legacy_parse_document_path_stays_for_existing_workflow_histories() -> None:
    source = WORKFLOW_SOURCE.read_text(encoding="utf-8")
    patch_marker = 'if workflow.patched("text-ingestion-inline-store-v1"):'
    legacy_marker = "parsed = await workflow.execute_activity("

    assert patch_marker in source, "Inline text ingestion patch missing"
    assert legacy_marker in source, "Legacy workflow fallback block missing"

    start = source.index(patch_marker)
    legacy_start = source.index(legacy_marker, start)
    legacy_block = source[legacy_start:]

    assert "parse_document" in legacy_block
    assert "chunk_and_embed" in legacy_block
    assert "store_chunks" in legacy_block
    assert "start_to_close_timeout=timedelta(minutes=30)" in legacy_block
    assert "start_to_close_timeout=timedelta(minutes=10)" in legacy_block
    assert "start_to_close_timeout=timedelta(minutes=2)" in legacy_block
