"""add document summary and suggested questions

Revision ID: 0007_document_insights
Revises: 0006_document_size_bytes
Create Date: 2026-06-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_document_insights"
down_revision: str | None = "0006_document_size_bytes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "suggested_questions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("documents", "suggested_questions")
    op.drop_column("documents", "summary")
