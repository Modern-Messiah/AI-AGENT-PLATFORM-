"""Regression test: every app table must be granted to the runtime role.

Migration 0011 granted the runtime role DML on the tables that existed at
the time; 0017 (users) and 0018 (agent_query_logs) created new tables
without repeating the grants, which broke every authenticated request on
the live stack ("permission denied for table users") while unit tests
stayed green — they fake the DB session. This test parses the migration
files so a table created without a matching GRANT fails CI, not production.
"""

from __future__ import annotations

import re
from pathlib import Path

_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"

_CREATE_TABLE_RE = re.compile(r"create_table\(\s*[\"'](\w+)[\"']", re.IGNORECASE)
_CREATE_SQL_RE = re.compile(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)", re.IGNORECASE)
_GRANT_RE = re.compile(r"GRANT\s+[^;]+?\s+ON\s+([A-Za-z_,\s]+?)\s+TO\s", re.IGNORECASE)


def _migration_sources() -> list[tuple[str, str]]:
    return [(p.name, p.read_text()) for p in sorted(_MIGRATIONS_DIR.glob("*.py"))]


def _created_tables() -> set[str]:
    tables: set[str] = set()
    for _, source in _migration_sources():
        tables.update(_CREATE_TABLE_RE.findall(source))
        tables.update(_CREATE_SQL_RE.findall(source))
    return tables


def _granted_tables() -> set[str]:
    tables: set[str] = set()
    for _, source in _migration_sources():
        for table_list in _GRANT_RE.findall(source):
            for name in table_list.split(","):
                name = name.strip()
                # GRANT ... ON DATABASE/SCHEMA targets are not table grants.
                if name and re.fullmatch(r"[a-z_]+", name):
                    tables.add(name)
    return tables


def test_every_created_table_has_a_grant_for_the_runtime_role() -> None:
    ungranted = _created_tables() - _granted_tables()
    assert not ungranted, (
        f"Tables created by migrations but never granted to the runtime role: "
        f"{sorted(ungranted)}. Every new table must include a GRANT for "
        f"APP_DB_USER — see migration 0020."
    )


def test_grant_targets_only_known_tables() -> None:
    # Guards the parser itself: grants should not invent table names.
    unknown = _granted_tables() - _created_tables()
    assert not unknown, f"GRANT mentions tables no migration creates: {sorted(unknown)}"
