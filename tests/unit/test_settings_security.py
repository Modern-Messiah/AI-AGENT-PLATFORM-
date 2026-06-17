from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.core.settings import Settings


def test_local_environment_allows_default_cors_origins() -> None:
    settings = Settings(app_env="local")

    assert settings.allowed_origins == []


def test_non_local_environment_requires_explicit_cors_origins() -> None:
    with pytest.raises(ValidationError, match="ALLOWED_ORIGINS must be set"):
        Settings(
            app_env="production",
            admin_secret="not-the-default-secret",
            allowed_origins=[],
        )


def test_non_local_environment_rejects_cors_wildcard() -> None:
    with pytest.raises(ValidationError, match="ALLOWED_ORIGINS must not contain"):
        Settings(
            app_env="production",
            admin_secret="not-the-default-secret",
            allowed_origins=["*"],
        )


def test_non_local_environment_accepts_explicit_cors_origin() -> None:
    settings = Settings(
        app_env="production",
        admin_secret="not-the-default-secret",
        allowed_origins=["https://app.example.com"],
    )

    assert settings.allowed_origins == ["https://app.example.com"]


def test_allowed_origins_accepts_comma_separated_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ADMIN_SECRET", "not-the-default-secret")
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "https://app.example.com,https://admin.example.com",
    )

    settings = Settings(_env_file=None)

    assert settings.allowed_origins == [
        "https://app.example.com",
        "https://admin.example.com",
    ]


def test_wildcard_allowed_origins_env_gets_clear_validation_error(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ADMIN_SECRET", "not-the-default-secret")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")

    with pytest.raises(ValidationError, match="ALLOWED_ORIGINS must not contain"):
        Settings(_env_file=None)
