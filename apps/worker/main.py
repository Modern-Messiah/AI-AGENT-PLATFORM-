"""Temporal worker entrypoint.

Runs in its own process. Restarting it does not lose in-flight work — the
workflow is durable, and activities will be re-dispatched.
"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from apps.worker.activities import (
    chunk_and_embed,
    mark_done,
    mark_failed,
    mark_processing,
    parse_document,
    request_human_approval,
    run_agent_step,
    store_chunks,
)
from apps.worker.workflows import AgentRunWorkflow, IngestionWorkflow, MultiStepResearchWorkflow
from packages.core import settings
from packages.observability import setup_tracing
from packages.rag.embedder import embed_texts

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
            chunk_and_embed,
            store_chunks,
            mark_done,
            mark_failed,
        ],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
