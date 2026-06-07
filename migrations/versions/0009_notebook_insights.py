"""add notebook insights

Revision ID: 0009_notebook_insights
Revises: 0008_notebooks
Create Date: 2026-06-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_notebook_insights"
down_revision: str | None = "0008_notebooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notebooks", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column(
        "notebooks",
        sa.Column(
            "suggested_questions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "notebooks",
        sa.Column(
            "key_topics",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "notebooks",
        sa.Column("insights_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notebooks", "insights_updated_at")
    op.drop_column("notebooks", "key_topics")
    op.drop_column("notebooks", "suggested_questions")
    op.drop_column("notebooks", "summary")
