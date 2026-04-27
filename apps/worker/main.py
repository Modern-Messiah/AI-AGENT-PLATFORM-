"""Temporal worker entrypoint.

Runs in its own process. Restarting it does not lose in-flight work — the
workflow is durable, and activities will be re-dispatched.
"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from apps.worker.activities import run_agent_step
from apps.worker.workflows import AgentRunWorkflow
from packages.core import settings
from packages.observability import setup_tracing

logging.basicConfig(level=settings.log_level)
log = logging.getLogger(__name__)


async def main() -> None:
    setup_tracing("aap-worker")
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
        workflows=[AgentRunWorkflow],
        activities=[run_agent_step],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
