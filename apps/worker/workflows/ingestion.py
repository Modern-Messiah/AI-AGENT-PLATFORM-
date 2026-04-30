"""Document ingestion workflow.

Sequential for MVP. If embedding cost becomes the bottleneck, split
chunking + embedding by batches and run them as parallel activities.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from apps.worker.activities.ingestion import (
        IngestionInput,
        chunk_and_embed,
        mark_done,
        mark_failed,
        mark_processing,
        parse_document,
        store_chunks,
    )


@workflow.defn
class IngestionWorkflow:
    @workflow.run
    async def run(self, payload: IngestionInput) -> int:
        retry = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=30),
            maximum_attempts=3,
        )
        try:
            await workflow.execute_activity(
                mark_processing,
                payload,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
            parsed = await workflow.execute_activity(
                parse_document,
                payload,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry,
            )
            batch = await workflow.execute_activity(
                chunk_and_embed,
                parsed,
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry,
            )
            written = await workflow.execute_activity(
                store_chunks,
                args=[payload, batch],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry,
            )
            await workflow.execute_activity(
                mark_done,
                payload,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
            return written
        except ActivityError as e:
            await workflow.execute_activity(
                mark_failed,
                args=[payload, str(e)],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            raise
