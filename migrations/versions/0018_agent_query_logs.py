"""agent_query_logs table — admin monitoring trail for agent requests

Revision ID: 0018_agent_query_logs
Revises: 0017_users_and_key_attribution
Create Date: 2026-09-28

One row per /agent/stream, /agent/run and /agent/research request: who asked
(key owner snapshot), the prompt, the answer, scope, model, latency, tokens
and cost. Written best-effort by the API after each request completes.

RLS design: same tenant_isolation pattern as the other tables (session-local
app.tenant_id), plus an admin_read SELECT policy gated on the session-local
app.admin_read flag — the admin router sets it behind X-Admin-Secret. The
runtime app role can already set app.tenant_id to any tenant, so this gate
follows the existing trust model: RLS protects against missing WHERE
clauses, the admin secret protects the admin surface.
"""

from alembic import op

revision: str = "0018_agent_query_logs"
down_revision: str | None = "0017_users_and_key_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agent_query_logs (
            id UUID PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            user_id UUID,
            user_name VARCHAR(256),
            mode VARCHAR(16) NOT NULL,
            model VARCHAR(128) NOT NULL,
            session_id UUID,
            workflow_id VARCHAR(128),
            scope_type VARCHAR(16),
            scope_ref UUID,
            query TEXT NOT NULL,
            retrieval_query TEXT,
            answer TEXT NOT NULL DEFAULT '',
            status VARCHAR(16) NOT NULL DEFAULT 'ok',
            error TEXT,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            cached BOOLEAN NOT NULL DEFAULT false,
            confidence REAL,
            sources_count INTEGER NOT NULL DEFAULT 0,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_agent_query_logs_tenant_created "
        "ON agent_query_logs (tenant_id, created_at)"
    )
    op.execute(
        "CREATE INDEX ix_agent_query_logs_user_created ON agent_query_logs (user_id, created_at)"
    )
    op.execute("CREATE INDEX ix_agent_query_logs_mode ON agent_query_logs (mode)")

    op.execute("ALTER TABLE agent_query_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_query_logs FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON agent_query_logs "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )
    op.execute(
        "CREATE POLICY admin_read ON agent_query_logs FOR SELECT "
        "USING (current_setting('app.admin_read', true) = 'on')"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS admin_read ON agent_query_logs")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON agent_query_logs")
    op.execute("ALTER TABLE agent_query_logs DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE agent_query_logs")
