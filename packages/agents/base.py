from pydantic_ai import Agent

from packages.agents.deps import AgentDeps
from packages.agents.prompts import get_streaming_system_prompt, get_system_prompt
from packages.agents.schemas import AgentRunOutput
from packages.agents.tools import (
    register_code_exec_tool,
    register_http_tool,
    register_retrieval_tool,
    register_sql_tool,
)
from packages.core import settings
from packages.llm import build_model


def _register_tools(agent: Agent) -> None:  # type: ignore[type-arg]
    register_retrieval_tool(agent)  # type: ignore[arg-type]
    register_sql_tool(agent)  # type: ignore[arg-type]
    register_http_tool(agent)  # type: ignore[arg-type]
    if settings.enable_code_exec:
        register_code_exec_tool(agent)  # type: ignore[arg-type]


def build_research_agent(model_name: str | None = None) -> Agent[AgentDeps, AgentRunOutput]:
    agent = Agent[AgentDeps, AgentRunOutput](
        model=build_model(model_name),
        deps_type=AgentDeps,
        result_type=AgentRunOutput,
        system_prompt=get_system_prompt(),
    )
    _register_tools(agent)
    return agent


def build_streaming_agent(model_name: str | None = None) -> Agent[AgentDeps, str]:
    """Text-streaming agent: result_type=str enables stream_text(delta=True)."""
    agent: Agent[AgentDeps, str] = Agent(
        model=build_model(model_name),
        deps_type=AgentDeps,
        result_type=str,
        system_prompt=get_streaming_system_prompt(),
    )
    _register_tools(agent)
    return agent


def build_strong_agent() -> Agent[AgentDeps, AgentRunOutput]:
    """Kimi K2 — сложные шаги: reasoning, tool-calling, основные ответы."""
    return build_research_agent(settings.strong_model)
