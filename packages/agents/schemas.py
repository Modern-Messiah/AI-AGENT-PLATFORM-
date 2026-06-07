from pydantic import BaseModel, Field

from packages.rag.citations import CitationSource


class AgentRunInput(BaseModel):
    tenant_id: str = Field(default="", description="Overridden from API key — do not set manually")
    user_query: str
    model: str | None = None
    require_approval: bool = Field(
        default=False,
        description="Pause after generating an answer and wait for human approve/reject signal",
    )


class AgentRunOutput(BaseModel):
    answer: str = Field(..., description="Final answer to the user")
    confidence: float = Field(..., ge=0.0, le=1.0)
    sources: list[str | CitationSource] = Field(default_factory=list)
    cached: bool = Field(default=False, description="True when answer came from semantic cache")


class MultiStepResearchInput(BaseModel):
    tenant_id: str = ""
    main_query: str
    sub_queries: list[str] = Field(..., min_length=1, max_length=10)
    model: str | None = None
