"""Single-run agent workflow with optional human-in-the-loop approval.

Signals:
  approve — mark the pending answer as approved
  reject  — mark the pending answer as rejected

When require_approval=False (default) the workflow completes immediately
after the agent activity. When True it pauses up to 24 h waiting for a
signal via POST /workflows/{id}/approve or /reject.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from apps.worker.activities.agent_step import run_agent_step
    from apps.worker.activities.human_approval import request_human_approval
    from packages.agents import AgentRunInput, AgentRunOutput

_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=2,
    non_retryable_error_types=["ValueError", "ApplicationError"],
)


@workflow.defn
class AgentRunWorkflow:
    def __init__(self) -> None:
        self._decision: str | None = None  # "approve" | "reject"

    @workflow.signal
    def approve(self) -> None:
        self._decision = "approve"

    @workflow.signal
    def reject(self) -> None:
        self._decision = "reject"

    @workflow.run
    async def run(self, payload: AgentRunInput) -> AgentRunOutput:
        result: AgentRunOutput = await workflow.execute_activity(
            run_agent_step,
            payload,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=_RETRY,
        )

        if not payload.require_approval:
            return result

        await workflow.execute_activity(
            request_human_approval,
            {
                "workflow_id": workflow.info().workflow_id,
                "answer": result.answer,
                "confidence": result.confidence,
            },
            start_to_close_timeout=timedelta(seconds=30),
        )

        try:
            await workflow.wait_condition(
                lambda: self._decision is not None,
                timeout=timedelta(hours=24),
            )
        except asyncio.TimeoutError:
            result.answer = f"[APPROVAL TIMED OUT]\n\n{result.answer}"
            return result

        if self._decision == "reject":
            result.answer = f"[REJECTED by reviewer]\n\n{result.answer}"
        return result
