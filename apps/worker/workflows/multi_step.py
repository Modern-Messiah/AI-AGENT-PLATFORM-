"""Multi-step research workflow using child workflows.

Runs each sub_query as an independent child AgentRunWorkflow in parallel,
then synthesises all answers in a final agent activity.

This demonstrates the Temporal child-workflow pattern: the parent maintains
durability while each sub-task is independently retried and tracked.
"""

from __future__ import annotations

from collections.abc import Awaitable, Sequence
from datetime import timedelta
from typing import TypeVar

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.agents import AgentRunInput, AgentRunOutput, MultiStepResearchInput
    from packages.rag.citations import CitationSource

    from apps.worker.activities.agent_step import run_agent_step
    from apps.worker.workflows.agent_run import AgentRunWorkflow

_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
    non_retryable_error_types=["ValueError"],
)

_T = TypeVar("_T")


def _synthesis_prompt(main_query: str, sub_results: list[AgentRunOutput]) -> str:
    parts = [f"Original question: {main_query}\n\nSub-research results:"]
    for i, r in enumerate(sub_results, 1):
        parts.append(f"\n[{i}] {r.answer}")
    parts.append("\n\nSynthesize the above into a single comprehensive answer.")
    return "\n".join(parts)


def _merge_sources(
    *source_groups: list[str | CitationSource],
) -> list[CitationSource]:
    merged: list[CitationSource] = []
    seen: set[tuple[str, str]] = set()

    for source in (source for group in source_groups for source in group):
        if not isinstance(source, CitationSource):
            continue

        key = (source.document_id, source.chunk_id)
        if key in seen:
            continue
        seen.add(key)
        merged.append(source)

    return merged


async def _collect_child_results(child_handles: Sequence[Awaitable[_T]]) -> list[_T]:
    import asyncio

    return list(await asyncio.gather(*child_handles))


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

        # Fan-in: child handles are asyncio Task-like objects; await them.
        sub_results = await _collect_child_results(child_handles)

        # Collect all source ids from sub-results for the final answer.
        all_sources = _merge_sources(*(result.sources for result in sub_results))

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
        final.sources = _merge_sources(final.sources, all_sources)
        return final
