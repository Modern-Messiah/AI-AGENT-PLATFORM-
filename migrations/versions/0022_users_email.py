"""users.email — identity column for Google OAuth logins

Revision ID: 0022_users_email
Revises: 0021_query_log_key_attribution
Create Date: 2026-09-28

Google-authenticated users are matched by email within the default tenant;
name stays the human-readable display name. Unique index keeps one account
per email (Postgres treats NULLs as distinct, so manually created users
without email are unaffected).
"""

from alembic import op

revision: str = "0022_users_email"
down_revision: str | None = "0021_query_log_key_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(320)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users (email)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_email")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email")
