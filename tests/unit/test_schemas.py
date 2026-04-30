import pytest
from pydantic import ValidationError

from packages.agents import AgentRunInput, AgentRunOutput


def test_agent_input_requires_query() -> None:
    with pytest.raises(ValidationError):
        AgentRunInput()  # user_query has no default


def test_agent_output_clamps_confidence() -> None:
    with pytest.raises(ValidationError):
        AgentRunOutput(answer="x", confidence=1.5)
