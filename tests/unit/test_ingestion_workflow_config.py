from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_SOURCE = ROOT / "apps/worker/workflows/ingestion.py"


def test_text_ingestion_uses_single_activity_to_keep_temporal_payloads_small() -> None:
    source = WORKFLOW_SOURCE.read_text(encoding="utf-8")
    start = source.index('if workflow.patched("text-ingestion-inline-store-v1"):')
    end = source.index("parsed = await workflow.execute_activity(", start)
    block = source[start:end]

    assert "ingest_text_document" in block
    assert "parse_document" not in block
    assert "chunk_and_embed" not in block
    assert "store_chunks" not in block
    assert "start_to_close_timeout=timedelta(minutes=30)" in block


def test_legacy_parse_document_path_stays_for_existing_workflow_histories() -> None:
    source = WORKFLOW_SOURCE.read_text(encoding="utf-8")

    assert 'workflow.patched("text-ingestion-inline-store-v1")' in source
    assert "parsed = await workflow.execute_activity(" in source
    assert "chunk_and_embed" in source
    assert "store_chunks" in source
