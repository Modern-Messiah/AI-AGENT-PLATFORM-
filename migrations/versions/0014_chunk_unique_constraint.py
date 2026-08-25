"""add unique constraint on chunks (tenant_id, document_id, chunk_idx)

Revision ID: 0014_chunk_unique_constraint
Revises: 0013_chat_session_scope
Create Date: 2026-08-25
"""

from __future__ import annotations

from alembic import op

revision: str = "0014_chunk_unique_constraint"
down_revision: str | None = "0013_chat_session_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Deduplicate existing dirty rows before adding the unique constraint
    op.execute(
        """
        DELETE FROM chunks c1 USING chunks c2
        WHERE c1.id > c2.id
          AND c1.tenant_id = c2.tenant_id
          AND c1.document_id = c2.document_id
          AND c1.chunk_idx = c2.chunk_idx
        """
    )
    op.create_unique_constraint(
        "uq_chunks_tenant_doc_chunk_idx",
        "chunks",
        ["tenant_id", "document_id", "chunk_idx"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_chunks_tenant_doc_chunk_idx",
        "chunks",
        type_="unique",
    )
