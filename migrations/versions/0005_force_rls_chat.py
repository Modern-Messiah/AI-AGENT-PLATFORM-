"""Force RLS on chat tables so table owner cannot bypass policies.

Without FORCE ROW LEVEL SECURITY the table owner (the app DB user) silently
bypasses all policies even after ENABLE ROW LEVEL SECURITY is set.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-30
"""

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.execute("ALTER TABLE chat_sessions FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chat_messages FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE chat_sessions NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chat_messages NO FORCE ROW LEVEL SECURITY")
