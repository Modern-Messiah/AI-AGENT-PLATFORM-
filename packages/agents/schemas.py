from pydantic import BaseModel, Field

from packages.rag.citations import CitationSource


class AgentRunInput(BaseModel):
    tenant_id: str = Field(default="", description="Overridden from API key — do not set manually")
    user_id: str = Field(default="", description="Owner attribution for analytics")
    user_query: str
    model: str | None = None
    document_ids: list[str] = Field(
        default_factory=list,
        description="Server-injected retrieval scope: documents the acting user may "
        "access (personal + shared). Empty = unbound tenant key = whole tenant.",
    )
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
    user_id: str = ""
    main_query: str
    sub_queries: list[str] = Field(..., min_length=1, max_length=10)
    model: str | None = None
    document_ids: list[str] = Field(
        default_factory=list,
        description="Server-injected retrieval scope, same meaning as in AgentRunInput",
    )
