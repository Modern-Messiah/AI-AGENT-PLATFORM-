from pydantic_ai import Agent

from packages.agents.deps import AgentDeps
from packages.agents.schemas import AgentRunOutput
from packages.agents.tools import register_retrieval_tool
from packages.core import settings
from packages.llm import build_model

SYSTEM_PROMPT = """\
You are a helpful research assistant grounded in the user's knowledge base.

When the user asks a question, first call the `retrieve` tool to look up
relevant chunks. Base your answer on retrieved content. If retrieval
returns nothing useful, say so honestly rather than guessing.

Always set a confidence in [0,1] reflecting how sure you are. Put the
document_id of every chunk you actually used into `sources` — never
invent ids.
"""


def build_research_agent(model_name: str | None = None) -> Agent[AgentDeps, AgentRunOutput]:
    agent = Agent[AgentDeps, AgentRunOutput](
        model=build_model(model_name),
        deps_type=AgentDeps,
        output_type=AgentRunOutput,
        system_prompt=SYSTEM_PROMPT,
    )
    register_retrieval_tool(agent)
    return agent


def build_strong_agent() -> Agent[AgentDeps, AgentRunOutput]:
    """Kimi K2 — сложные шаги: reasoning, tool-calling, основные ответы."""
    return build_research_agent(settings.strong_model)


def build_weak_agent() -> Agent[AgentDeps, AgentRunOutput]:
    """DeepSeek — дешёвые шаги: классификация, парсинг, summarization."""
    return build_research_agent(settings.weak_model)
