"""users.is_active — admin block/unblock without deleting the account

Revision ID: 0026_users_is_active
Revises: 0024_llm_api_keys
Create Date: 2026-09-29

Blocked users fail password login immediately and their live JWT sessions
are revoked (Redis denylist); unblocking restores access. Default true.
"""

from __future__ import annotations

from alembic import op

revision: str = "0026_users_is_active"
down_revision: str | None = "0024_llm_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_active")
