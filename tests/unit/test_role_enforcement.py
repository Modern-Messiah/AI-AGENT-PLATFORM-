from __future__ import annotations

import pytest
from fastapi import HTTPException
from packages.auth.api_keys import Actor, require_destroy_permission


def _actor(role: str | None) -> Actor:
    return Actor(tenant_id="tenant-a", role=role)


def test_unbound_key_can_destroy() -> None:
    # tenant-level keys (no user binding) keep full access — backward compat
    require_destroy_permission(_actor(None))  # must not raise


def test_admin_key_can_destroy() -> None:
    require_destroy_permission(_actor("admin"))  # must not raise


def test_member_key_cannot_destroy() -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_destroy_permission(_actor("member"))
    assert exc_info.value.status_code == 403
    assert "member keys cannot delete" in str(exc_info.value.detail)


def test_can_destroy_property_matches_policy() -> None:
    assert _actor(None).can_destroy is True
    assert _actor("admin").can_destroy is True
    assert _actor("member").can_destroy is False


def test_unknown_role_is_conservative() -> None:
    # anything that is not admin/unbound is treated as restricted
    assert _actor("guest").can_destroy is False


def test_actor_is_frozen() -> None:
    import dataclasses

    actor = _actor("member")
    with pytest.raises(dataclasses.FrozenInstanceError):
        actor.role = "admin"  # type: ignore[misc]
