"""add notebooks for document collections

Revision ID: 0008_notebooks
Revises: 0007_document_insights
Create Date: 2026-06-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_notebooks"
down_revision: str | None = "0007_document_insights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notebooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_notebooks_tenant_id", "notebooks", ["tenant_id"])

    op.create_table(
        "notebook_documents",
        sa.Column(
            "notebook_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notebooks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_notebook_documents_tenant_notebook",
        "notebook_documents",
        ["tenant_id", "notebook_id"],
    )
    op.create_index(
        "ix_notebook_documents_tenant_document",
        "notebook_documents",
        ["tenant_id", "document_id"],
    )

    op.execute("ALTER TABLE notebooks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notebook_documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notebooks FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notebook_documents FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON notebooks
        USING (tenant_id = current_setting('app.tenant_id', TRUE))
    """)
    op.execute("""
        CREATE POLICY tenant_isolation ON notebook_documents
        USING (tenant_id = current_setting('app.tenant_id', TRUE))
    """)


def downgrade() -> None:
    op.drop_index("ix_notebook_documents_tenant_document", table_name="notebook_documents")
    op.drop_index("ix_notebook_documents_tenant_notebook", table_name="notebook_documents")
    op.drop_table("notebook_documents")
    op.drop_index("ix_notebooks_tenant_id", table_name="notebooks")
    op.drop_table("notebooks")
