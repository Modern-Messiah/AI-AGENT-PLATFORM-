import uuid
from dataclasses import dataclass, field


@dataclass
class AgentDeps:
    tenant_id: str
    sources: list[str] = field(default_factory=list)
    # Personal knowledge-base scope: documents the acting user may access.
    # None = no restriction (unbound tenant API key).
    document_ids: list[uuid.UUID] | None = None
