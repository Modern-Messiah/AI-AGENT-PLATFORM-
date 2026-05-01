"""add document size_bytes

Revision ID: 0006_document_size_bytes
Revises: 0005
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006_document_size_bytes"
down_revision: str | None = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.alter_column("documents", "size_bytes", server_default=None)


def downgrade() -> None:
    op.drop_column("documents", "size_bytes")
