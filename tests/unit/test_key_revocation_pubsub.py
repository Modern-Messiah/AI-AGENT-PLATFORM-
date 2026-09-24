from __future__ import annotations

import pytest
from packages.auth import api_keys, revocation
from packages.auth.revocation import (
    REVOCATION_CHANNEL,
    handle_revocation_message,
    publish_revocation,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


async def test_publish_revocation_posts_to_the_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(revocation, "get_redis", lambda: redis)

    await publish_revocation("deadbeef")

    assert redis.published == [(REVOCATION_CHANNEL, "deadbeef")]


async def test_publish_revocation_never_raises_when_redis_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken() -> object:
        raise RuntimeError("redis down")

    monkeypatch.setattr(revocation, "get_redis", broken)

    await publish_revocation("deadbeef")  # must not raise


def test_handle_message_drops_cached_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    cache: dict[str, tuple[str, float]] = {"abc": ("tenant-a", 1e12)}
    monkeypatch.setattr(api_keys, "_AUTH_CACHE", cache)

    dropped = handle_revocation_message({"type": "message", "data": b"abc"})

    assert dropped == "abc"
    assert "abc" not in cache


def test_handle_message_ignores_control_frames_and_junk() -> None:
    assert handle_revocation_message({"type": "subscribe", "data": 1}) is None
    assert handle_revocation_message({"type": "message", "data": None}) is None
    assert handle_revocation_message({"type": "message", "data": b""}) is None
