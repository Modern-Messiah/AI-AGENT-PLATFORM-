"""api_keys table + Row Level Security on documents and chunks

Revision ID: 0002_rls_api_keys
Revises: 0001_initial
Create Date: 2026-04-28

RLS design:
  The app sets the session-local variable app.tenant_id via set_config()
  before any query. Policies use current_setting('app.tenant_id', true)
  to filter rows. The 'true' flag suppresses errors when the variable is
  not set (returns '' instead), so admin/migration sessions are unaffected
  when run as the superuser role (superusers bypass RLS by default).

  In production: connect the app as a non-superuser role and remove the
  superuser bypass. FORCE ROW LEVEL SECURITY is applied here so the table
  owner is also restricted.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0002_rls_api_keys"
down_revision: str | None = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Row Level Security — documents
    op.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE documents FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON documents "
        "USING (tenant_id = current_setting('app.tenant_id', true))"
    )

    # Row Level Security — chunks
    op.execute("ALTER TABLE chunks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chunks FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON chunks "
        "USING (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON chunks")
    op.execute("ALTER TABLE chunks DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON documents")
    op.execute("ALTER TABLE documents DISABLE ROW LEVEL SECURITY")
    op.drop_table("api_keys")
