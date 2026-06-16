"""add non-superuser runtime database role

Revision ID: 0011_app_runtime_role
Revises: 0010_document_assets
Create Date: 2026-06-16
"""

from __future__ import annotations

import os
import re

from alembic import op

revision: str = "0011_app_runtime_role"
down_revision: str | None = "0010_document_assets"
branch_labels = None
depends_on = None

_ROLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _role_name() -> str:
    role = os.getenv("APP_DB_USER", "aap_app")
    if not _ROLE_RE.match(role):
        raise RuntimeError("APP_DB_USER must be a safe PostgreSQL role name")
    return role


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def upgrade() -> None:
    role = _role_name()
    password = os.getenv("APP_DB_PASSWORD")
    if not password:
        raise RuntimeError("APP_DB_PASSWORD must be set before creating the runtime database role")

    role_lit = _quote_literal(role)
    role_ident = _quote_ident(role)
    password_lit = _quote_literal(password)

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {role_lit}) THEN
                EXECUTE
                    'CREATE ROLE ' || quote_ident({role_lit}) ||
                    ' LOGIN PASSWORD ' || quote_literal({password_lit}) ||
                    ' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION';
            ELSE
                EXECUTE
                    'ALTER ROLE ' || quote_ident({role_lit}) ||
                    ' WITH LOGIN PASSWORD ' || quote_literal({password_lit}) ||
                    ' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION';
            END IF;
        END $$;
        """
    )
    op.execute(f"GRANT CONNECT ON DATABASE app TO {role_ident}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {role_ident}")
    op.execute(
        f"""
        GRANT SELECT, INSERT, UPDATE, DELETE ON
            api_keys,
            documents,
            chunks,
            chat_sessions,
            chat_messages,
            notebooks,
            notebook_documents,
            document_assets
        TO {role_ident}
        """
    )


def downgrade() -> None:
    role = _role_name()
    role_ident = _quote_ident(role)
    op.execute(
        f"""
        REVOKE SELECT, INSERT, UPDATE, DELETE ON
            api_keys,
            documents,
            chunks,
            chat_sessions,
            chat_messages,
            notebooks,
            notebook_documents,
            document_assets
        FROM {role_ident}
        """
    )
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {role_ident}")
    op.execute(f"REVOKE CONNECT ON DATABASE app FROM {role_ident}")
