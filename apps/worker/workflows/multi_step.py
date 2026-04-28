"""Multi-step research workflow using child workflows.

Runs each sub_query as an independent child AgentRunWorkflow in parallel,
then synthesises all answers in a final agent activity.

This demonstrates the Temporal child-workflow pattern: the parent maintains
durability while each sub-task is independently retried and tracked.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from apps.worker.activities.agent_step import run_agent_step
    from apps.worker.workflows.agent_run import AgentRunWorkflow
    from packages.agents import AgentRunInput, AgentRunOutput, MultiStepResearchInput

_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
    non_retryable_error_types=["ValueError"],
)


def _synthesis_prompt(main_query: str, sub_results: list[AgentRunOutput]) -> str:
    parts = [f"Original question: {main_query}\n\nSub-research results:"]
    for i, r in enumerate(sub_results, 1):
        parts.append(f"\n[{i}] {r.answer}")
    parts.append("\n\nSynthesize the above into a single comprehensive answer.")
    return "\n".join(parts)


@workflow.defn
class MultiStepResearchWorkflow:
    @workflow.run
    async def run(self, payload: MultiStepResearchInput) -> AgentRunOutput:
        # Fan-out: each sub-query runs as an independent child workflow.
        child_handles = []
        for i, sub_query in enumerate(payload.sub_queries):
            handle = await workflow.start_child_workflow(
                AgentRunWorkflow.run,
                AgentRunInput(
                    tenant_id=payload.tenant_id,
                    user_query=sub_query,
                    model=payload.model,
                ),
                id=f"{workflow.info().workflow_id}-step-{i}",
                task_queue=workflow.info().task_queue,
            )
            child_handles.append(handle)

        # Fan-in: wait for all children.
        import asyncio  # noqa: PLC0415 — inside workflow, import is fine here
        sub_results: list[AgentRunOutput] = list(
            await asyncio.gather(*[h.result() for h in child_handles])
        )

        # Collect all source ids from sub-results for the final answer.
        all_sources = list({s for r in sub_results for s in r.sources})

        synthesis_input = AgentRunInput(
            tenant_id=payload.tenant_id,
            user_query=_synthesis_prompt(payload.main_query, sub_results),
            model=payload.model,
        )
        final: AgentRunOutput = await workflow.execute_activity(
            run_agent_step,
            synthesis_input,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=_RETRY,
        )
        final.sources = list({*final.sources, *all_sources})
        return final
