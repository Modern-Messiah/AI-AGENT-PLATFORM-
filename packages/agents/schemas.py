from pydantic import BaseModel, Field


class AgentRunInput(BaseModel):
    tenant_id: str = Field(..., description="Tenant identifier for multi-tenancy")
    user_query: str
    model: str | None = None


class AgentRunOutput(BaseModel):
    answer: str = Field(..., description="Final answer to the user")
    confidence: float = Field(..., ge=0.0, le=1.0)
    sources: list[str] = Field(default_factory=list)
