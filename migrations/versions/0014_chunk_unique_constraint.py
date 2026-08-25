"""add unique constraint on chunks (tenant_id, document_id, chunk_idx)

Revision ID: 0014_chunk_unique_constraint
Revises: 0013_chat_session_scope
Create Date: 2026-08-25

Requirement: This migration must be executed by a database role with BYPASSRLS
privileges (such as POSTGRES_USER / superuser postgres in docker-compose.yml:196).
Because the chunks table has FORCE ROW LEVEL SECURITY enabled with tenant_isolation
policy, running without BYPASSRLS would prevent cross-tenant deduplication from
seeing and removing duplicate rows across all tenants prior to constraint creation.
"""

from __future__ import annotations

from alembic import op

revision: str = "0014_chunk_unique_constraint"
down_revision: str | None = "0013_chat_session_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Deduplicate existing dirty rows deterministically keeping freshest row by (created_at, id)
    op.execute(
        """
        DELETE FROM chunks c
        USING chunks keep
        WHERE c.tenant_id = keep.tenant_id
          AND c.document_id = keep.document_id
          AND c.chunk_idx = keep.chunk_idx
          AND (c.created_at, c.id) < (keep.created_at, keep.id)
        """
    )
    op.create_unique_constraint(
        "uq_chunks_tenant_doc_chunk_idx",
        "chunks",
        ["tenant_id", "document_id", "chunk_idx"],
    )
    op.drop_index("ix_chunks_tenant_document", table_name="chunks")


def downgrade() -> None:
    op.create_index(
        "ix_chunks_tenant_document",
        "chunks",
        ["tenant_id", "document_id"],
    )
    op.drop_constraint(
        "uq_chunks_tenant_doc_chunk_idx",
        "chunks",
        type_="unique",
    )
