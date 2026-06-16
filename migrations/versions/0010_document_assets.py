"""add visual document assets and ingestion progress

Revision ID: 0010_document_assets
Revises: 0009_notebook_insights
Create Date: 2026-06-15
"""

from __future__ import annotations

from alembic import op

revision: str = "0010_document_assets"
down_revision: str | None = "0009_notebook_insights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE documents
            ADD COLUMN processing_stage VARCHAR(32) NOT NULL DEFAULT 'queued',
            ADD COLUMN processed_pages INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN total_pages INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN warnings JSONB NOT NULL DEFAULT '[]'::jsonb
        """
    )
    op.execute(
        """
        CREATE TYPE document_asset_status AS ENUM (
            'pending', 'processing', 'done', 'failed'
        )
        """
    )
    op.execute(
        """
        CREATE TABLE document_assets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id VARCHAR(64) NOT NULL,
            document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_number INTEGER,
            asset_kind VARCHAR(32) NOT NULL,
            preview_object_key VARCHAR(512) NOT NULL,
            ocr_text TEXT NOT NULL DEFAULT '',
            ocr_confidence DOUBLE PRECISION,
            vision_description TEXT NOT NULL DEFAULT '',
            width INTEGER NOT NULL DEFAULT 0,
            height INTEGER NOT NULL DEFAULT 0,
            status document_asset_status NOT NULL DEFAULT 'pending',
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_assets_tenant_document
        ON document_assets (tenant_id, document_id)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_document_assets_document_page_kind
        ON document_assets (document_id, page_number, asset_kind)
        """
    )
    op.execute("ALTER TABLE document_assets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_assets FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON document_assets
        USING (tenant_id = current_setting('app.tenant_id', TRUE))
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_assets CASCADE")
    op.execute("DROP TYPE IF EXISTS document_asset_status")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS warnings")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS total_pages")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS processed_pages")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS processing_stage")
