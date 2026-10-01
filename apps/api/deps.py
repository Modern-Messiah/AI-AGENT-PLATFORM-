from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, UploadFile
from packages.auth import (
    Actor,
    AdminPrincipal,
    require_actor,
    require_admin_principal,
    require_tenant,
)

TenantID = Annotated[str, Depends(require_tenant)]
ActorDep = Annotated[Actor, Depends(require_actor)]
AdminDep = Annotated[AdminPrincipal, Depends(require_admin_principal)]

_READ_CHUNK = 64 * 1024  # 64 KB


def content_length_exceeds(request: Request, limit: int) -> bool:
    """Early-rejection check on Content-Length. Malformed or absent values
    are ignored: the header is client-controlled and the authoritative byte
    limit is enforced while reading the body (read_with_limit) — a weird
    header must not turn into a 500."""
    cl = request.headers.get("content-length")
    if not cl or not cl.isdigit():
        return False
    return int(cl) > limit


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
