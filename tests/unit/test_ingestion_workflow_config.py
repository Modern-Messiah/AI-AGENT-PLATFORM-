from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_SOURCE = ROOT / "apps/worker/workflows/ingestion.py"


def test_parse_document_allows_slow_url_and_github_visual_sources() -> None:
    source = WORKFLOW_SOURCE.read_text(encoding="utf-8")
    start = source.index("parsed = await workflow.execute_activity(")
    end = source.index("batch = await workflow.execute_activity(", start)
    block = source[start:end]

    assert "parse_document" in block
    assert "start_to_close_timeout=timedelta(minutes=30)" in block
    assert "start_to_close_timeout=timedelta(minutes=5)" not in block
