"""Activities are where I/O happens — LLM calls, DB queries, HTTP, etc."""

from __future__ import annotations

from temporalio import activity

from packages.agents import AgentRunInput, AgentRunOutput, build_research_agent


@activity.defn
async def run_agent_step(payload: AgentRunInput) -> AgentRunOutput:
    agent = build_research_agent(model_name=payload.model)
    result = await agent.run(payload.user_query)
    return result.output
