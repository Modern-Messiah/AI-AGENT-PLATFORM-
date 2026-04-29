"""chat sessions and messages

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE chat_sessions (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   TEXT NOT NULL,
            title       TEXT NOT NULL DEFAULT 'New Chat',
            model       TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_chat_sessions_tenant ON chat_sessions (tenant_id)")

    op.execute("""
        CREATE TABLE chat_messages (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id  UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            tenant_id   TEXT NOT NULL,
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            sources     JSONB NOT NULL DEFAULT '[]',
            cached      BOOLEAN NOT NULL DEFAULT FALSE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_chat_messages_session ON chat_messages (session_id)")

    # RLS
    op.execute("ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON chat_sessions
        USING (tenant_id = current_setting('app.tenant_id', TRUE))
    """)
    op.execute("""
        CREATE POLICY tenant_isolation ON chat_messages
        USING (tenant_id = current_setting('app.tenant_id', TRUE))
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_messages CASCADE")
    op.execute("DROP TABLE IF EXISTS chat_sessions CASCADE")
