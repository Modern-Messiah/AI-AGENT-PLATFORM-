from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apps.api.services.session_retention import retention_cutoff


def test_retention_cutoff_disabled_returns_none() -> None:
    assert retention_cutoff(0) is None
    assert retention_cutoff(-5) is None


def test_retention_cutoff_is_days_before_now() -> None:
    now = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
    cutoff = retention_cutoff(30, now=now)
    assert cutoff == now - timedelta(days=30)


def test_retention_cutoff_uses_utc_now_by_default() -> None:
    cutoff = retention_cutoff(7)
    assert cutoff is not None
    assert cutoff.tzinfo is UTC
