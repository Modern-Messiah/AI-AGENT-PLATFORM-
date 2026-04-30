"""SQL SELECT tool — lets the agent query the tenant's documents/chunks tables."""

from __future__ import annotations

import re

import sqlalchemy as sa
from pydantic_ai import Agent, RunContext

from packages.agents.deps import AgentDeps
from packages.storage.db import tenant_session

_BLOCKED = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|EXECUTE|CALL|COPY)\b",
    re.IGNORECASE,
)
_SAFE_TENANT = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# Tables with sensitive data that the agent must never read
_FORBIDDEN_TABLES = re.compile(
    r"\b(api_keys|alembic_version|pg_catalog|information_schema)\b",
    re.IGNORECASE,
)

# Tables the agent is allowed to read
_ALLOWED_TABLES = frozenset({"documents", "chunks", "chat_sessions", "chat_messages"})

# Extracts table names from FROM/JOIN clauses only (not comments or string literals)
_FROM_JOIN_RE = re.compile(r"\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)

# Detects old-style comma joins after paren-collapsing:
#   FROM t1 [alias],   or   FROM () [alias],  (the () form catches collapsed subqueries)
_COMMA_JOIN_RE = re.compile(
    r"\bFROM\s+(?:[a-z_][a-z0-9_]*|\(\))"   # FROM identifier  or  FROM ()
    r"(?:\s+(?:AS\s+)?[a-z_][a-z0-9_]*)?"   # optional alias
    r"\s*,",                                  # trailing comma
    re.IGNORECASE,
)

_MAX_ROWS = 500


def _strip_literals(sql: str) -> str:
    """Remove comments and quoted strings so table-name checks can't be fooled."""
    sql = re.sub(r"--[^\n]*", " ", sql)                      # -- line comments
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)     # /* block comments */
    sql = re.sub(r"'(?:[^'\\]|\\.)*'", "''", sql)             # 'string literals'
    sql = re.sub(r'"(?:[^"\\]|\\.)*"', '""', sql)             # "quoted identifiers"
    return sql


def _collapse_parens(sql: str) -> str:
    """Replace parenthesised groups with () from inside out.

    Makes outer FROM-list commas visible even when subqueries are present.
    E.g. FROM (SELECT * FROM docs) sub, bad_table  →  FROM () sub, bad_table
    """
    prev = None
    while prev != sql:
        prev = sql
        sql = re.sub(r"\([^()]*\)", "()", sql)
    return sql


def register_sql_tool(agent: Agent[AgentDeps, object]) -> None:
    @agent.tool
    async def sql_query(ctx: RunContext[AgentDeps], query: str) -> list[dict]:
        """Run a read-only SELECT against the platform database.

        Use this to look up document metadata or chunk statistics for the
        current tenant. Only SELECT statements are allowed.

        Write {tenant_id} as a literal placeholder — it is replaced safely
        with the current tenant's id. Example:
          SELECT id, filename, status FROM documents WHERE tenant_id = '{tenant_id}'

        Allowed tables: documents, chunks, chat_sessions, chat_messages.
        Results are capped at 500 rows.

        Args:
            query: A SQL SELECT statement using {tenant_id} where needed.
        """
        if _BLOCKED.search(query):
            return [{"error": "Only SELECT statements are allowed"}]

        if not _SAFE_TENANT.match(ctx.deps.tenant_id):
            return [{"error": "invalid tenant_id"}]

        if "{tenant_id}" not in query:
            return [{"error": "Query must include {tenant_id} filter for tenant isolation"}]

        # Strip comments and string literals before all structural checks so a table
        # name in a comment or string can't trick the allowlist/blocklist.
        stripped = _strip_literals(query)

        if _FORBIDDEN_TABLES.search(stripped):
            return [{"error": "Query references a restricted table"}]

        # Block old-style comma joins (FROM t1, t2) which bypass the FROM/JOIN regex.
        # _collapse_parens hides subquery internals so FROM () alias, bad_table is also caught.
        if _COMMA_JOIN_RE.search(_collapse_parens(stripped)):
            return [{"error": "Comma-separated table lists are not allowed; use explicit JOIN syntax"}]

        # Only accept table names that appear after FROM/JOIN — not in comments or strings.
        from_tables = {t.lower() for t in _FROM_JOIN_RE.findall(stripped)}
        if not from_tables:
            return [{"error": f"Query must SELECT from one of: {', '.join(sorted(_ALLOWED_TABLES))}"}]
        disallowed = from_tables - _ALLOWED_TABLES
        if disallowed:
            return [{"error": f"Query references disallowed table(s): {', '.join(sorted(disallowed))}. Allowed: {', '.join(sorted(_ALLOWED_TABLES))}"}]

        safe_query = query.replace("{tenant_id}", ctx.deps.tenant_id)

        # Enforce a row cap if the query has no LIMIT clause.
        if not re.search(r"\bLIMIT\b", stripped, re.IGNORECASE):
            safe_query = safe_query.rstrip().rstrip(";") + f" LIMIT {_MAX_ROWS}"

        async with tenant_session(ctx.deps.tenant_id) as session:
            await session.execute(sa.text("SET LOCAL statement_timeout = '5000'"))
            rows = (await session.execute(sa.text(safe_query))).mappings().all()
            return [dict(r) for r in rows]
