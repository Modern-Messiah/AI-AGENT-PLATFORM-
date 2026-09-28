"""llm_api_keys — admin-managed provider keys (rotation + activity)

Revision ID: 0024_llm_api_keys
Revises: 0023_users_password
Create Date: 2026-09-28

Provider API keys (Moonshot/DeepSeek) move from .env-only to admin-panel
managed: one ACTIVE key per provider (adding a new key rotates the old one
out), with a request counter and last_used_at for activity monitoring.
The key value is needed verbatim to call the provider, so it is stored as
received — but never returned by any endpoint (masked preview only) and
readable/writable only through the X-Admin-Secret / admin-session surface.
"""

from __future__ import annotations

import os
import re

from alembic import op

revision: str = "0024_llm_api_keys"
down_revision: str | None = "0023_users_password"
branch_labels = None
depends_on = None

_ROLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _role_ident() -> str:
    role = os.getenv("APP_DB_USER", "aap_app")
    if not _ROLE_RE.match(role):
        raise RuntimeError("APP_DB_USER must be a safe PostgreSQL role name")
    return '"' + role.replace('"', '""') + '"'


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE llm_api_keys (
            id UUID PRIMARY KEY,
            provider VARCHAR(32) NOT NULL,
            name VARCHAR(256) NOT NULL,
            key_value TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            requests_count BIGINT NOT NULL DEFAULT 0,
            last_used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_llm_api_keys_provider_active ON llm_api_keys (provider, is_active)"
    )
    # Runtime role grant — every new table must repeat this (see 0020).
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON llm_api_keys TO {_role_ident()}")


def downgrade() -> None:
    op.execute("DROP TABLE llm_api_keys")
