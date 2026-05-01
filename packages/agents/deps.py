from dataclasses import dataclass, field


@dataclass
class AgentDeps:
    tenant_id: str
    sources: list[str] = field(default_factory=list)
