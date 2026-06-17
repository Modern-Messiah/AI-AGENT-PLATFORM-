"""add url source metadata to documents

Revision ID: 0012_document_url_sources
Revises: 0011_app_runtime_role
Create Date: 2026-06-17
"""

from __future__ import annotations

from alembic import op

revision: str = "0012_document_url_sources"
down_revision: str | None = "0011_app_runtime_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE documents
            ADD COLUMN source_type VARCHAR(32) NOT NULL DEFAULT 'file',
            ADD COLUMN source_url TEXT,
            ADD COLUMN source_title VARCHAR(512),
            ADD COLUMN source_checked_at TIMESTAMPTZ
        """
    )
    op.execute(
        """
        CREATE INDEX ix_documents_tenant_source_type
        ON documents (tenant_id, source_type)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_tenant_source_type")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS source_checked_at")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS source_title")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS source_url")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS source_type")
