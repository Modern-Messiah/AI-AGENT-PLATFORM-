#!/usr/bin/env python3
"""Postgres → MinIO backup.

Usage:
    uv run python scripts/backup.py

Requires pg_dump in PATH. Connects using DATABASE_URL from .env.
Stores compressed dump at backups/postgres_YYYYMMDD_HHMMSS.sql.gz in MinIO.
"""

from __future__ import annotations

import gzip
import os
import subprocess
import sys
from datetime import UTC, datetime

# Ensure project root is importable.
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.core import settings
from packages.storage.object_store import object_store


def check_rls_privileges(pg_url: str) -> bool:
    """Check if the DB user has SUPERUSER or BYPASSRLS privileges."""
    import asyncio

    import asyncpg  # type: ignore[import-untyped]

    async def _query() -> tuple[bool, bool] | None:
        try:
            conn = await asyncpg.connect(pg_url)
            row = await conn.fetchrow(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
            await conn.close()
            if row:
                return bool(row["rolsuper"]), bool(row["rolbypassrls"])
            return None
        except Exception:
            return None

    res = asyncio.run(_query())
    if res is not None:
        is_super, is_bypass = res
        return is_super or is_bypass
    return True


def main() -> None:
    # pg_dump needs a standard postgresql:// URL (not asyncpg).
    pg_url = settings.database_url.replace("+asyncpg", "")
    parsed = urlparse(pg_url)

    if not check_rls_privileges(pg_url):
        print(
            f"WARNING: Database user '{parsed.username}' does NOT have BYPASSRLS or SUPERUSER privileges.\n"
            f"Because PostgreSQL FORCE ROW LEVEL SECURITY is enabled on tables (documents, chunks, chat_sessions, notebooks),\n"
            f"pg_dump will silently export ZERO rows for these tables without BYPASSRLS!\n"
            f"To produce a full backup, configure DATABASE_URL with a role having BYPASSRLS or run as superuser.\n"
            f"Proceeding with backup, but RLS-protected tables may be empty.\n",
            file=sys.stderr,
        )

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_key = f"backups/postgres_{timestamp}.sql.gz"

    print(f"Dumping database → {backup_key} …")

    # Pass the password via PGPASSWORD env var — avoids it appearing in ps aux / /proc/pid/cmdline.
    env = {**os.environ, "PGPASSWORD": parsed.password or ""}
    result = subprocess.run(
        [
            "pg_dump",
            "--no-password",
            f"--host={parsed.hostname}",
            f"--port={parsed.port or 5432}",
            f"--username={parsed.username}",
            parsed.path.lstrip("/"),
        ],
        capture_output=True,
        check=True,
        env=env,
    )

    compressed = gzip.compress(result.stdout, compresslevel=6)
    object_store.put(backup_key, compressed, content_type="application/gzip")

    size_kb = len(compressed) / 1024
    print(f"Done: {backup_key} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
