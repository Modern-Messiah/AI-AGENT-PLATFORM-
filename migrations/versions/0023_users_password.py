"""users.password_hash — email+password authentication

Revision ID: 0023_users_password
Revises: 0022_users_email
Create Date: 2026-09-28

Email/password logins share the users.email identity column with Google
OAuth (one account per email). password_hash is NULL for Google-only and
manually created users — they cannot sign in by password until one is set.
Format: scrypt$<salt-hex>$<hash-hex> (hashlib.scrypt, stdlib only).
"""

from alembic import op

revision: str = "0023_users_password"
down_revision: str | None = "0022_users_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(512)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS password_hash")
