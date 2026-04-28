from pydantic_ai import Agent

from packages.agents.deps import AgentDeps
from packages.agents.schemas import AgentRunOutput
from packages.agents.tools import (
    register_code_exec_tool,
    register_http_tool,
    register_retrieval_tool,
    register_sql_tool,
)
from packages.core import settings
from packages.llm import build_model

SYSTEM_PROMPT = """\
You are a helpful research assistant grounded in the user's knowledge base.

Available tools:
- retrieve      : search the vector knowledge base for relevant chunks
- sql_query     : run a SELECT against the documents/chunks tables
- http_fetch    : fetch content from an external URL
- code_exec     : run a Python snippet for computation or data transformation

When answering:
1. Call retrieve first for knowledge-base questions.
2. Use sql_query to look up document metadata or counts.
3. Use http_fetch only when you need fresh external content.
4. Use code_exec for calculations or non-trivial data wrangling.

Always set confidence in [0,1]. Put the document_id of every retrieved chunk
you actually used into sources — never invent ids.
"""


def _register_tools(agent: Agent[AgentDeps, AgentRunOutput]) -> None:
    register_retrieval_tool(agent)
    register_sql_tool(agent)
    register_http_tool(agent)
    register_code_exec_tool(agent)


def build_research_agent(model_name: str | None = None) -> Agent[AgentDeps, AgentRunOutput]:
    agent = Agent[AgentDeps, AgentRunOutput](
        model=build_model(model_name),
        deps_type=AgentDeps,
        output_type=AgentRunOutput,
        system_prompt=SYSTEM_PROMPT,
    )
    _register_tools(agent)
    return agent


def build_strong_agent() -> Agent[AgentDeps, AgentRunOutput]:
    """Kimi K2 — сложные шаги: reasoning, tool-calling, основные ответы."""
    return build_research_agent(settings.strong_model)


def build_weak_agent() -> Agent[AgentDeps, AgentRunOutput]:
    """DeepSeek — дешёвые шаги: классификация, парсинг, summarization."""
    return build_research_agent(settings.weak_model)
