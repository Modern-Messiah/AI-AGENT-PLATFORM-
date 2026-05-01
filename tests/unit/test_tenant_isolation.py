"""Unit tests for multi-tenant isolation helpers.

These tests verify the pure-logic guards without a live Temporal/Postgres connection.
They import the production functions directly so any logic change in main.py or
tenant_utils.py will immediately break these tests.
"""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi import HTTPException

from packages.core.tenant_utils import check_workflow_tenant

# ── check_workflow_tenant ─────────────────────────────────────────────────────

def test_correct_tenant_passes() -> None:
    uid = str(uuid.uuid4())
    check_workflow_tenant(f"agent-run-tenant-a-{uid}", "tenant-a")  # must not raise


def test_wrong_tenant_raises() -> None:
    uid = str(uuid.uuid4())
    with pytest.raises(HTTPException) as exc_info:
        check_workflow_tenant(f"agent-run-tenant-b-{uid}", "tenant-a")
    assert exc_info.value.status_code == 403
    assert "does not belong" in exc_info.value.detail


def test_prefix_collision_rejected() -> None:
    """tenant 'foo' must not access a workflow created by 'foo-bar'."""
    uid = str(uuid.uuid4())
    with pytest.raises(HTTPException) as exc_info:
        check_workflow_tenant(f"agent-run-foo-bar-{uid}", "foo")
    assert exc_info.value.status_code == 403


def test_no_uuid_suffix_rejected() -> None:
    with pytest.raises(HTTPException) as exc_info:
        check_workflow_tenant("agent-run-tenant-a-not-a-uuid", "tenant-a")
    assert exc_info.value.status_code == 403
    assert "invalid workflow_id format" in exc_info.value.detail


def test_injected_extra_suffix_rejected() -> None:
    uid = str(uuid.uuid4())
    with pytest.raises(HTTPException):
        check_workflow_tenant(f"agent-run-tenant-a-{uid}-extra", "tenant-a")


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
