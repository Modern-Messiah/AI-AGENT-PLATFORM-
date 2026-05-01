"""Tenant-scoped validation utilities shared by the API and tests."""

from __future__ import annotations

import re

from fastapi import HTTPException

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def check_workflow_tenant(workflow_id: str, tenant_id: str) -> None:
    """Raise HTTP 403 if workflow_id was not created by this tenant.

    Guards against tenant-id prefix collision, e.g. tenant 'foo' matching
    workflow 'agent-run-foo-bar-<uuid>' created by tenant 'foo-bar'.
    The UUID suffix check ensures only exact-prefix matches pass.
    """
    prefix = f"agent-run-{tenant_id}-"
    if not workflow_id.startswith(prefix):
        raise HTTPException(status_code=403, detail="workflow does not belong to this tenant")
    suffix = workflow_id[len(prefix):]
    if not _UUID_RE.match(suffix):
        raise HTTPException(status_code=403, detail="invalid workflow_id format")
