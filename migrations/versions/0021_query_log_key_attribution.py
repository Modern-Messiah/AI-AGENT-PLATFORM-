"""api key attribution on agent_query_logs

Revision ID: 0021_query_log_key_attribution
Revises: 0020_runtime_role_grants
Create Date: 2026-09-28

The admin panel manages API keys, so the query log now records which key
made each request (api_key_id + a name snapshot for display after the key
is renamed/deleted). Rows written before this migration keep NULL — they
predates per-key attribution.
"""

from alembic import op

revision: str = "0021_query_log_key_attribution"
down_revision: str | None = "0020_runtime_role_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_query_logs ADD COLUMN IF NOT EXISTS api_key_id UUID")
    op.execute("ALTER TABLE agent_query_logs ADD COLUMN IF NOT EXISTS api_key_name VARCHAR(256)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_query_logs_key_created "
        "ON agent_query_logs (api_key_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_agent_query_logs_key_created")
    op.execute("ALTER TABLE agent_query_logs DROP COLUMN IF EXISTS api_key_name")
    op.execute("ALTER TABLE agent_query_logs DROP COLUMN IF EXISTS api_key_id")
