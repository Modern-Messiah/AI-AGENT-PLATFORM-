from pydantic_ai import Agent

from packages.agents.deps import AgentDeps
from packages.agents.prompts import get_system_prompt
from packages.agents.schemas import AgentRunOutput
from packages.agents.tools import (
    register_code_exec_tool,
    register_http_tool,
    register_retrieval_tool,
    register_sql_tool,
)
from packages.core import settings
from packages.llm import build_model


def _register_tools(agent: Agent[AgentDeps, AgentRunOutput]) -> None:
    register_retrieval_tool(agent)
    register_sql_tool(agent)
    register_http_tool(agent)
    if settings.enable_code_exec:
        register_code_exec_tool(agent)


def build_research_agent(model_name: str | None = None) -> Agent[AgentDeps, AgentRunOutput]:
    agent = Agent[AgentDeps, AgentRunOutput](
        model=build_model(model_name),
        deps_type=AgentDeps,
        output_type=AgentRunOutput,
        system_prompt=get_system_prompt(),
    )
    _register_tools(agent)
    return agent


def build_strong_agent() -> Agent[AgentDeps, AgentRunOutput]:
    """Kimi K2 — сложные шаги: reasoning, tool-calling, основные ответы."""
    return build_research_agent(settings.strong_model)
