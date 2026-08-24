from pathlib import Path

ROOT = Path(__file__).parents[2]
WORKFLOW = (ROOT / "apps/worker/workflows/ingestion.py").read_text()
WORKER = (ROOT / "apps/worker/main.py").read_text()


def _get_worker_activities_block() -> str:
    start = WORKER.index("activities=[")
    end = WORKER.index("]", start)
    return WORKER[start:end]


def test_visual_ingestion_runs_at_most_two_batches_with_heartbeats() -> None:
    assert '_VISUAL_CONCURRENCY = 2' in WORKFLOW
    assert "range(0, len(batches), _VISUAL_CONCURRENCY)" in WORKFLOW
    assert "asyncio.gather" in WORKFLOW
    assert "heartbeat_timeout=timedelta(minutes=2)" in WORKFLOW


def test_visual_workflow_is_versioned_for_existing_histories() -> None:
    assert 'workflow.patched("visual-ingestion-v1")' in WORKFLOW


def test_worker_registers_visual_ingestion_activities() -> None:
    activities_block = _get_worker_activities_block()
    for activity_name in (
        "prepare_visual_document",
        "process_visual_batch",
        "finalize_visual_document",
    ):
        assert activity_name in activities_block


def test_worker_registers_inline_text_ingestion_activity() -> None:
    activities_block = _get_worker_activities_block()
    assert "ingest_text_document" in activities_block
