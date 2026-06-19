"""persist scoped chat sessions

Revision ID: 0013_chat_session_scope
Revises: 0012_document_url_sources
Create Date: 2026-06-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_chat_session_scope"
down_revision: str | None = "0012_document_url_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_sessions", sa.Column("scope_type", sa.String(16), nullable=True))
    op.add_column(
        "chat_sessions",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("notebook_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_chat_sessions_document_id_documents",
        "chat_sessions",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_chat_sessions_notebook_id_notebooks",
        "chat_sessions",
        "notebooks",
        ["notebook_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_chat_sessions_scope_consistent",
        "chat_sessions",
        """
        (scope_type IS NULL OR scope_type IN ('document', 'notebook'))
        AND NOT (document_id IS NOT NULL AND notebook_id IS NOT NULL)
        """,
    )
    op.create_index(
        "ix_chat_sessions_tenant_document",
        "chat_sessions",
        ["tenant_id", "document_id"],
    )
    op.create_index(
        "ix_chat_sessions_tenant_notebook",
        "chat_sessions",
        ["tenant_id", "notebook_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_tenant_notebook", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_tenant_document", table_name="chat_sessions")
    op.drop_constraint("ck_chat_sessions_scope_consistent", "chat_sessions", type_="check")
    op.drop_constraint(
        "fk_chat_sessions_notebook_id_notebooks",
        "chat_sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_chat_sessions_document_id_documents",
        "chat_sessions",
        type_="foreignkey",
    )
    op.drop_column("chat_sessions", "notebook_id")
    op.drop_column("chat_sessions", "document_id")
    op.drop_column("chat_sessions", "scope_type")
