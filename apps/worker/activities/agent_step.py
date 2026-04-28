"""Activities are where I/O happens — LLM calls, DB queries, HTTP, etc."""

from __future__ import annotations

import time

from temporalio import activity

from packages.agents import AgentDeps, AgentRunInput, AgentRunOutput, build_research_agent
from packages.analytics.events import UsageEvent, record_usage
from packages.core import settings


@activity.defn
async def run_agent_step(payload: AgentRunInput) -> AgentRunOutput:
    agent = build_research_agent(model_name=payload.model)
    deps = AgentDeps(tenant_id=payload.tenant_id)

    t0 = time.monotonic()
    result = await agent.run(payload.user_query, deps=deps)
    latency_ms = int((time.monotonic() - t0) * 1000)

    usage = result.usage()
    resolved_model = payload.model or settings.strong_model
    info = activity.info()

    event = UsageEvent(
        tenant_id=payload.tenant_id,
        workflow_id=info.workflow_id,
        run_id=info.workflow_run_id,
        model=resolved_model,
        prompt_tokens=usage.request_tokens or 0,
        completion_tokens=usage.response_tokens or 0,
        latency_ms=latency_ms,
    )
    await record_usage(event)

    return result.output
