"""SQL SELECT tool — lets the agent query the tenant's documents/chunks tables."""

from __future__ import annotations

import re

import sqlalchemy as sa
from pydantic_ai import Agent, RunContext

from packages.agents.deps import AgentDeps
from packages.storage.db import async_session

_BLOCKED = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|EXECUTE|CALL|COPY)\b",
    re.IGNORECASE,
)
_SAFE_TENANT = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def register_sql_tool(agent: Agent[AgentDeps, object]) -> None:
    @agent.tool
    async def sql_query(ctx: RunContext[AgentDeps], query: str) -> list[dict]:
        """Run a read-only SELECT against the platform database.

        Use this to look up document metadata or chunk statistics for the
        current tenant. Only SELECT statements are allowed.

        Write {tenant_id} as a literal placeholder — it is replaced safely
        with the current tenant's id. Example:
          SELECT id, filename, status FROM documents WHERE tenant_id = '{tenant_id}'

        Args:
            query: A SQL SELECT statement using {tenant_id} where needed.
        """
        if _BLOCKED.search(query):
            return [{"error": "Only SELECT statements are allowed"}]

        if not _SAFE_TENANT.match(ctx.deps.tenant_id):
            return [{"error": "invalid tenant_id"}]

        safe_query = query.replace("{tenant_id}", ctx.deps.tenant_id)

        async with async_session() as session:
            rows = (await session.execute(sa.text(safe_query))).mappings().all()
            return [dict(r) for r in rows]
