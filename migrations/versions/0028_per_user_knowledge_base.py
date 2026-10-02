"""per-user knowledge base: document/notebook ownership and session users

Revision ID: 0028_per_user_knowledge_base
Revises: 0027_session_retention
Create Date: 2026-10-01

Each user gets a personal knowledge base. documents and notebooks gain an
optional owner (users.id) plus a shared flag; chat_sessions gain the user
that created them so history can be private.

Access model (enforced in application queries, on top of tenant RLS):
- owner_user_id IS NULL → legacy tenant-shared document, visible to everyone
  in the tenant (backfill-free: existing rows simply keep NULL).
- owner_user_id set + is_shared = false → private to the owner.
- owner_user_id set + is_shared = true → owner's upload explicitly shared
  with the tenant.
- Unbound tenant API keys (user_id NULL) keep full tenant access so
  operational scripts (reindex, evals) are unaffected.

ON DELETE SET NULL mirrors api_keys.user_id: deleting a person keeps their
documents, they just fall back to tenant-shared. Only column additions and
indexes — no new tables, so no runtime-role grants are needed.
"""

from alembic import op

revision: str = "0028_per_user_knowledge_base"
down_revision: str | None = "0027_session_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE documents "
        "ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES users(id) "
        "ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_tenant_owner "
        "ON documents (tenant_id, owner_user_id)"
    )

    op.execute(
        "ALTER TABLE notebooks "
        "ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES users(id) "
        "ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE notebooks ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notebooks_tenant_owner "
        "ON notebooks (tenant_id, owner_user_id)"
    )

    op.execute(
        "ALTER TABLE chat_sessions "
        "ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) "
        "ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chat_sessions_tenant_user "
        "ON chat_sessions (tenant_id, user_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_tenant_user")
    op.execute("ALTER TABLE chat_sessions DROP COLUMN IF EXISTS user_id")

    op.execute("DROP INDEX IF EXISTS ix_notebooks_tenant_owner")
    op.execute("ALTER TABLE notebooks DROP COLUMN IF EXISTS is_shared")
    op.execute("ALTER TABLE notebooks DROP COLUMN IF EXISTS owner_user_id")

    op.execute("DROP INDEX IF EXISTS ix_documents_tenant_owner")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS is_shared")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS owner_user_id")
