"""Temporal worker entrypoint.

Runs in its own process. Restarting it does not lose in-flight work — the
workflow is durable, and activities will be re-dispatched.
"""

from __future__ import annotations

import asyncio
import logging

from packages.core import settings
from packages.observability import setup_tracing
from packages.rag.embedder import embed_texts
from temporalio.client import Client
from temporalio.worker import Worker

from apps.worker.activities import (
    chunk_and_embed,
    finalize_visual_document,
    ingest_text_document,
    mark_done,
    mark_failed,
    mark_processing,
    parse_document,
    prepare_visual_document,
    process_visual_batch,
    request_human_approval,
    run_agent_step,
    store_chunks,
)
from apps.worker.workflows import AgentRunWorkflow, IngestionWorkflow, MultiStepResearchWorkflow

logging.basicConfig(level=settings.log_level)
log = logging.getLogger(__name__)


async def main() -> None:
    setup_tracing("aap-worker")
    log.info("warming up embedding model...")
    try:
        await embed_texts(["warmup"])
        log.info("embedding model ready")
    except Exception as exc:
        log.warning("embedding model warmup failed (%s) — will retry on first use", exc)
    client = await Client.connect(
        settings.temporal_address, namespace=settings.temporal_namespace
    )
    log.info(
        "worker connected to %s (queue=%s)",
        settings.temporal_address,
        settings.temporal_task_queue,
    )
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[AgentRunWorkflow, IngestionWorkflow, MultiStepResearchWorkflow],
        activities=[
            run_agent_step,
            request_human_approval,
            mark_processing,
            parse_document,
            prepare_visual_document,
            process_visual_batch,
            chunk_and_embed,
            ingest_text_document,
            store_chunks,
            finalize_visual_document,
            mark_done,
            mark_failed,
        ],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
