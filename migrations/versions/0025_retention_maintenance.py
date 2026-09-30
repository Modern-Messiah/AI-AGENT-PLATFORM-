"""maintenance DELETE policy for chat session retention

Revision ID: 0025_retention_maintenance
Revises: 0024_llm_api_keys
Create Date: 2026-09-30

The retention loop deletes idle chat sessions across ALL tenants in one
statement, but chat_sessions has FORCE ROW LEVEL SECURITY and the runtime
role is NOBYPASSRLS, so a plain session-scoped DELETE silently matches 0
rows (the tenant_isolation policy sees no app.tenant_id). Adds a permissive
FOR DELETE policy gated on the session-local app.maintenance flag, set only
by delete_stale_sessions() — same trust model as the admin_read policies
(migration 0019): the flag exists to scope cross-tenant maintenance in
process code, not to defend against a hostile DB client. chat_messages rows
follow via the existing ON DELETE CASCADE (referential actions bypass RLS
on the referencing table).
"""

from alembic import op

revision: str = "0025_retention_maintenance"
down_revision: str | None = "0024_llm_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE POLICY retention_maintenance ON chat_sessions FOR DELETE "
        "USING (current_setting('app.maintenance', true) = 'on')"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS retention_maintenance ON chat_sessions")
