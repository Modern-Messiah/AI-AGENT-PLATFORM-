from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, UploadFile

from packages.auth import require_tenant

TenantID = Annotated[str, Depends(require_tenant)]

_READ_CHUNK = 64 * 1024  # 64 KB


async def read_with_limit(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload in chunks; raise HTTP 413 as soon as limit is exceeded."""
    chunks: list[bytes] = []
    received = 0
    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        received += len(chunk)
        if received > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"file exceeds {max_bytes // (1024 * 1024)} MB limit",
            )
        chunks.append(chunk)
    return b"".join(chunks)
