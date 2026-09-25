"""users table and api_keys.user_id attribution

Revision ID: 0017_users_and_key_attribution
Revises: 0016_chunks_fts_tsv
Create Date: 2026-09-24

Adds a per-tenant user registry (name unique within a tenant, role
member|admin) and an optional FK from api_keys to users, so every key can
be attributed to a person for audit. Deleting a user keeps their keys
(user_id becomes NULL) — key revocation stays an explicit admin action.
"""

from alembic import op

revision: str = "0017_users_and_key_attribution"
down_revision: str | None = "0016_chunks_fts_tsv"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            name VARCHAR(256) NOT NULL,
            role VARCHAR(32) NOT NULL DEFAULT 'member',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_users_tenant_name UNIQUE (tenant_id, name)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_tenant_id ON users (tenant_id)")
    op.execute(
        "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS user_id UUID "
        "REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_keys_user_id ON api_keys (user_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_api_keys_user_id")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS user_id")
    op.execute("DROP TABLE IF EXISTS users")
