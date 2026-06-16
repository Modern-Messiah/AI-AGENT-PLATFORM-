"""Security tests for the sql_query tool validation layer.

These tests cover the regex/structural checks without touching the database.
They verify that the multi-layer defence (blocklist → locking → forbidden tables
→ comma-join → allowlist → literal-stripping) each catch their respective attack
vectors and that benign queries pass through cleanly.
"""

from __future__ import annotations

import pytest

from packages.agents.tools.sql_query import (
    _BLOCKED,
    _COMMA_JOIN_RE,
    _FORBIDDEN_TABLES,
    _FROM_JOIN_RE,
    _LOCKING,
    _collapse_parens,
    _strip_literals,
)

# ── _strip_literals ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("sql,expected_absent", [
    # line comment
    ("SELECT 1 -- DROP TABLE documents", "DROP"),
    # block comment
    ("SELECT 1 /* INSERT INTO api_keys */ FROM documents", "INSERT"),
    # string literal containing a keyword
    ("SELECT 'DROP TABLE' FROM documents", "DROP TABLE"),
    # quoted identifier
    ('SELECT "DELETE" FROM documents', "DELETE"),
])
def test_strip_literals_removes_embedded_keywords(sql: str, expected_absent: str) -> None:
    assert expected_absent.lower() not in _strip_literals(sql).lower()


def test_strip_literals_preserves_from_keyword() -> None:
    stripped = _strip_literals("SELECT * FROM documents WHERE tenant_id = '{tenant_id}'")
    assert "FROM" in stripped.upper()
    assert "documents" in stripped


# ── _collapse_parens ──────────────────────────────────────────────────────────

def test_collapse_parens_single_level() -> None:
    assert _collapse_parens("FROM (SELECT 1)") == "FROM ()"


def test_collapse_parens_nested() -> None:
    result = _collapse_parens("FROM ((SELECT 1 FROM t)) AS sub")
    assert result == "FROM () AS sub"


def test_collapse_parens_subquery_with_bad_table() -> None:
    # After collapsing, the subquery contents are hidden as ()
    collapsed = _collapse_parens("FROM (SELECT * FROM api_keys) sub, documents")
    assert "api_keys" not in collapsed


# ── _BLOCKED ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "INSERT INTO documents VALUES (1)",
    "UPDATE documents SET status='done'",
    "DELETE FROM documents",
    "DROP TABLE documents",
    "ALTER TABLE documents ADD COLUMN x INT",
    "CREATE TABLE evil (id INT)",
    "TRUNCATE documents",
    "GRANT ALL ON documents TO evil",
    "REVOKE SELECT ON documents FROM user",
    "EXECUTE proc()",
    "CALL proc()",
    "COPY documents TO '/tmp/out'",
    # SELECT INTO creates a table in PostgreSQL
    "SELECT * INTO new_table FROM documents WHERE tenant_id = '{tenant_id}'",
])
def test_blocked_keywords_match(sql: str) -> None:
    stripped = _strip_literals(sql)
    assert _BLOCKED.search(stripped), f"Expected BLOCKED to match: {sql!r}"


def test_blocked_does_not_match_plain_select(plain: str = "SELECT id FROM documents WHERE tenant_id = '{tenant_id}'") -> None:
    assert not _BLOCKED.search(_strip_literals(plain))


# ── _LOCKING ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("clause", [
    "FOR UPDATE",
    "FOR SHARE",
    "FOR NO KEY UPDATE",
    "FOR KEY SHARE",
    "for update",  # case-insensitive
])
def test_locking_clauses_match(clause: str) -> None:
    sql = f"SELECT * FROM documents WHERE tenant_id = '{{tenant_id}}' {clause}"
    assert _LOCKING.search(_strip_literals(sql))


def test_locking_does_not_match_for_in_column_name() -> None:
    sql = "SELECT format FROM documents WHERE tenant_id = '{tenant_id}'"
    assert not _LOCKING.search(_strip_literals(sql))


# ── _FORBIDDEN_TABLES ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("tbl", [
    "api_keys",
    "alembic_version",
    "pg_catalog",
    "information_schema",
])
def test_forbidden_tables_match(tbl: str) -> None:
    sql = f"SELECT * FROM {tbl} WHERE tenant_id = '{{tenant_id}}'"
    assert _FORBIDDEN_TABLES.search(_strip_literals(sql))


def test_forbidden_table_hidden_in_comment_is_not_present_after_strip() -> None:
    sql = "SELECT * FROM documents -- api_keys WHERE tenant_id = '{tenant_id}'"
    stripped = _strip_literals(sql)
    assert "api_keys" not in stripped


# ── _FROM_JOIN_RE (allowlist extraction) ──────────────────────────────────────

@pytest.mark.parametrize("sql,expected_tables", [
    ("SELECT * FROM documents WHERE 1=1", {"documents"}),
    ("SELECT * FROM documents d JOIN chunks c ON c.document_id = d.id", {"documents", "chunks"}),
    ("SELECT * FROM chat_sessions s JOIN chat_messages m ON m.session_id = s.id", {"chat_sessions", "chat_messages"}),
])
def test_from_join_extracts_correct_tables(sql: str, expected_tables: set[str]) -> None:
    found = {t.lower() for t in _FROM_JOIN_RE.findall(_strip_literals(sql))}
    assert found == expected_tables


def test_from_join_ignores_subquery_table_after_collapse() -> None:
    sql = "SELECT * FROM (SELECT * FROM api_keys) sub WHERE 1=1"
    stripped = _strip_literals(sql)
    collapsed = _collapse_parens(stripped)
    tables = {t.lower() for t in _FROM_JOIN_RE.findall(collapsed)}
    # After collapse the subquery is () — api_keys should not appear as a top-level table
    assert "api_keys" not in tables


# ── _COMMA_JOIN_RE (comma-join bypass) ───────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "SELECT * FROM documents, api_keys WHERE tenant_id = '{tenant_id}'",
    "SELECT * FROM documents d, chunks c WHERE d.id = c.document_id",
    # Subquery alias then comma — after paren collapse
    "SELECT * FROM (SELECT 1) sub, api_keys WHERE 1=1",
    # Nested subquery alias then comma — the collapsed form must still expose the comma.
    "SELECT * FROM ((SELECT 1 FROM documents WHERE tenant_id = '{tenant_id}')) sub, chat_messages m",
])
def test_comma_join_detected(sql: str) -> None:
    stripped = _strip_literals(sql)
    collapsed = _collapse_parens(stripped)
    assert _COMMA_JOIN_RE.search(collapsed), f"Expected COMMA_JOIN to match: {sql!r}"


@pytest.mark.parametrize("sql", [
    "SELECT id, status FROM documents WHERE tenant_id = '{tenant_id}'",
    "SELECT * FROM documents d JOIN chunks c ON c.document_id = d.id",
])
def test_comma_join_not_triggered_for_clean_queries(sql: str) -> None:
    stripped = _strip_literals(sql)
    collapsed = _collapse_parens(stripped)
    assert not _COMMA_JOIN_RE.search(collapsed)


# ── Combined CTE bypass attempt ───────────────────────────────────────────────

def test_cte_does_not_bypass_forbidden_table_check() -> None:
    sql = """
    WITH leak AS (SELECT key_hash FROM api_keys)
    SELECT * FROM leak JOIN documents d ON 1=1
    WHERE d.tenant_id = '{tenant_id}'
    """
    stripped = _strip_literals(sql)
    # api_keys appears in the CTE body — _FORBIDDEN_TABLES must still catch it
    assert _FORBIDDEN_TABLES.search(stripped)


def test_union_injection_blocked() -> None:
    sql = "SELECT id FROM documents WHERE tenant_id = '{tenant_id}' UNION SELECT key_hash FROM api_keys"
    stripped = _strip_literals(sql)
    # _FORBIDDEN_TABLES catches api_keys in the UNION branch
    assert _FORBIDDEN_TABLES.search(stripped)
