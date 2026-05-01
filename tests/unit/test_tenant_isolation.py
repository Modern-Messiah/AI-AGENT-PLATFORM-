"""Unit tests for multi-tenant isolation helpers.

These tests verify the pure-logic guards without a live Temporal/Postgres connection.
"""

from __future__ import annotations

import re
import uuid

import pytest

# ── _check_workflow_tenant (main.py) — inline the logic for unit testing ─────
# We duplicate the function here rather than importing from main.py to avoid
# pulling in the full FastAPI app and its startup dependencies.

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


class _FakeForbidden(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail


def _check_workflow_tenant(workflow_id: str, tenant_id: str) -> None:
    prefix = f"agent-run-{tenant_id}-"
    if not workflow_id.startswith(prefix):
        raise _FakeForbidden("workflow does not belong to this tenant")
    suffix = workflow_id[len(prefix):]
    if not _UUID_RE.match(suffix):
        raise _FakeForbidden("invalid workflow_id format")


# ── correct tenant ────────────────────────────────────────────────────────────

def test_correct_tenant_passes() -> None:
    uid = str(uuid.uuid4())
    _check_workflow_tenant(f"agent-run-tenant-a-{uid}", "tenant-a")  # no raise


# ── wrong tenant ──────────────────────────────────────────────────────────────

def test_wrong_tenant_raises() -> None:
    uid = str(uuid.uuid4())
    with pytest.raises(_FakeForbidden, match="does not belong"):
        _check_workflow_tenant(f"agent-run-tenant-b-{uid}", "tenant-a")


def test_prefix_collision_rejected() -> None:
    """tenant 'foo' must not access a workflow created by 'foo-bar'."""
    uid = str(uuid.uuid4())
    with pytest.raises(_FakeForbidden, match="does not belong"):
        _check_workflow_tenant(f"agent-run-foo-bar-{uid}", "foo")


def test_no_uuid_suffix_rejected() -> None:
    with pytest.raises(_FakeForbidden, match="invalid workflow_id format"):
        _check_workflow_tenant("agent-run-tenant-a-not-a-uuid", "tenant-a")


def test_injected_extra_prefix_rejected() -> None:
    """Ensure workflow IDs with unexpected structure are rejected."""
    uid = str(uuid.uuid4())
    with pytest.raises(_FakeForbidden):
        _check_workflow_tenant(f"agent-run-tenant-a-{uid}-extra", "tenant-a")


# ── safe tenant_id regex (from sql_query.py) ─────────────────────────────────

_SAFE_TENANT = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


@pytest.mark.parametrize("tenant_id", [
    "tenant-a",
    "Tenant_123",
    "a" * 64,
    "abc",
])
def test_safe_tenant_ids_pass(tenant_id: str) -> None:
    assert _SAFE_TENANT.match(tenant_id)


@pytest.mark.parametrize("tenant_id", [
    "",
    "a" * 65,
    "tenant; DROP TABLE documents--",
    "tenant'a",
    "tenant a",
    "../etc/passwd",
])
def test_unsafe_tenant_ids_rejected(tenant_id: str) -> None:
    assert not _SAFE_TENANT.match(tenant_id)
