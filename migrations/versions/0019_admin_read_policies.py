"""admin_read SELECT policies — cross-tenant reads for the admin panel

Revision ID: 0019_admin_read_policies
Revises: 0018_agent_query_logs
Create Date: 2026-09-28

Adds a permissive FOR SELECT policy gated on the session-local app.admin_read
flag to every RLS-protected table, so /admin/* endpoints can aggregate across
tenants. Permissive policies OR with the existing tenant_isolation policy, so
normal tenant sessions are unaffected; the flag is only set by admin_session()
behind the X-Admin-Secret guard. Writes stay tenant-scoped — the policies are
read-only, and the runtime app role could already read any tenant by setting
app.tenant_id, so this follows the existing trust model.
"""

from alembic import op

revision: str = "0019_admin_read_policies"
down_revision: str | None = "0018_agent_query_logs"
branch_labels = None
depends_on = None

_TABLES = (
    "documents",
    "chunks",
    "chat_sessions",
    "chat_messages",
    "notebooks",
    "notebook_documents",
    "document_assets",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"CREATE POLICY admin_read ON {table} FOR SELECT "
            f"USING (current_setting('app.admin_read', true) = 'on')"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS admin_read ON {table}")
