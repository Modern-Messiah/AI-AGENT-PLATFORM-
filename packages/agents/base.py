from pydantic_ai import Agent

from packages.agents.schemas import AgentRunOutput
from packages.llm import build_model

SYSTEM_PROMPT = """\
You are a helpful research assistant. Answer the user's question concisely.
Always set a confidence in [0,1] reflecting how sure you are. If you list
sources, include only ones you were directly given — never invent URLs.
"""


def build_research_agent(model_name: str | None = None) -> Agent[None, AgentRunOutput]:
    return Agent(
        model=build_model(model_name),
        output_type=AgentRunOutput,
        system_prompt=SYSTEM_PROMPT,
    )
