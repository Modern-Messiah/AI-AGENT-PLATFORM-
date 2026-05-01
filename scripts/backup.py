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
from datetime import datetime, timezone

# Ensure project root is importable.
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.core import settings  # noqa: E402
from packages.storage.object_store import object_store  # noqa: E402


def main() -> None:
    # pg_dump needs a standard postgresql:// URL (not asyncpg).
    pg_url = settings.database_url.replace("+asyncpg", "")
    parsed = urlparse(pg_url)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
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
