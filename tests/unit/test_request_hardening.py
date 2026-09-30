from __future__ import annotations

from types import SimpleNamespace

from apps.api.deps import content_length_exceeds
from apps.api.schemas import AddMessageRequest


def _request(content_length: str | None) -> SimpleNamespace:
    headers = {"content-length": content_length} if content_length is not None else {}
    return SimpleNamespace(headers=headers)


def test_content_length_over_limit_is_flagged() -> None:
    assert content_length_exceeds(_request("104857600"), 1000) is True


def test_content_length_under_limit_is_not_flagged() -> None:
    assert content_length_exceeds(_request("10"), 1000) is False


def test_malformed_content_length_is_ignored_not_500() -> None:
    # A garbage header used to raise ValueError -> HTTP 500 at the router.
    assert content_length_exceeds(_request("not-a-number"), 1000) is False
    assert content_length_exceeds(_request("-5"), 1000) is False
    assert content_length_exceeds(_request(None), 1000) is False


def test_add_message_role_is_limited_to_user_and_agent() -> None:
    assert AddMessageRequest(role="user", content="hi").role == "user"
    assert AddMessageRequest(role="agent", content="hi").role == "agent"

    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AddMessageRequest(role="system", content="injected")
