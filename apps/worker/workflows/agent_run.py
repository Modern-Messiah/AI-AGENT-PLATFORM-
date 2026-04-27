"""Top-level workflow for a single agent run.

Workflows must be deterministic — no I/O, no time.time(), no uuid4(). All
non-deterministic work goes into activities (see apps/worker/activities/).
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from apps.worker.activities.agent_step import run_agent_step
    from packages.agents import AgentRunInput, AgentRunOutput


@workflow.defn
class AgentRunWorkflow:
    @workflow.run
    async def run(self, payload: AgentRunInput) -> AgentRunOutput:
        return await workflow.execute_activity(
            run_agent_step,
            payload,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=30),
                maximum_attempts=3,
                # LLM responses are non-deterministic. The activity itself
                # is responsible for caching results by attempt id if we
                # want true idempotency on retry.
                non_retryable_error_types=["ValueError"],
            ),
        )
