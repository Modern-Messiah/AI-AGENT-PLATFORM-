"""runtime role grants for tables created after 0011 (users, agent_query_logs)

Revision ID: 0020_runtime_role_users_logs_grants
Revises: 0019_admin_read_policies
Create Date: 2026-09-28

Migration 0011 granted the runtime app role DML on every table that existed
at the time, but later migrations created new tables without repeating the
grants: 0017 added `users` and 0018 added `agent_query_logs`. The result was
a hard "permission denied for table users" on every authenticated request
(require_actor joins api_keys -> users) — invisible to unit tests because
they fake the DB session, and caught by the live stack check.

 Grants:
  users            SELECT, INSERT, UPDATE, DELETE  (auth router CRUD)
  agent_query_logs SELECT, INSERT                  (append-only audit trail;
                                                    no UPDATE/DELETE on purpose)

New tables must grant the runtime role in their own migration — the grant
list in 0011 is a snapshot, not a living policy.
"""

from __future__ import annotations

import os
import re

from alembic import op

revision: str = "0020_runtime_role_users_logs_grants"
down_revision: str | None = "0019_admin_read_policies"
branch_labels = None
depends_on = None

_ROLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _role_ident() -> str:
    role = os.getenv("APP_DB_USER", "aap_app")
    if not _ROLE_RE.match(role):
        raise RuntimeError("APP_DB_USER must be a safe PostgreSQL role name")
    return '"' + role.replace('"', '""') + '"'


def upgrade() -> None:
    role = _role_ident()
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON users TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON agent_query_logs TO {role}")


def downgrade() -> None:
    role = _role_ident()
    op.execute(f"REVOKE SELECT, INSERT ON agent_query_logs FROM {role}")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON users FROM {role}")
