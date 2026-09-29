"""Unit tests for the optional Logfire integration."""

from __future__ import annotations

import pytest
from packages.core import settings
from packages.observability import (
    instrument_fastapi_app,
    logfire_enabled,
    setup_logfire,
)


@pytest.fixture(autouse=True)
def _no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "logfire_token", "")
    import packages.observability.logfire_setup as mod

    mod._initialized = False


def test_disabled_without_token() -> None:
    assert logfire_enabled() is False
    assert setup_logfire("aap-api") is False


def test_fastapi_instrumentation_noop_without_token() -> None:
    # не должно взорваться и не должно трогать приложение
    class App:
        touched = False

    instrument_fastapi_app(App())
    assert App.touched is False


def test_enabled_with_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "logfire_token", "pylf_test_token")

    calls: list[dict[str, object]] = []

    class FakeLogfire:
        def configure(self, **kwargs: object) -> None:
            calls.append({"op": "configure", **kwargs})

        def instrument_openai(self) -> None:
            calls.append({"op": "openai"})

        def instrument_fastapi(self, app: object, **kwargs: object) -> None:
            calls.append({"op": "fastapi", "app": app})

    import sys

    monkeypatch.setitem(sys.modules, "logfire", FakeLogfire())

    assert logfire_enabled() is True
    assert setup_logfire("aap-test") is True
    assert calls[0]["op"] == "configure"
    assert calls[0]["service_name"] == "aap-test"
    assert calls[1]["op"] == "openai"

    # повторный вызов — no-op (инициализация один раз на процесс)
    assert setup_logfire("again") is False

    # инструментация FastAPI подключается при токене
    class App2:
        pass

    instrument_fastapi_app(App2())
    assert calls[-1]["op"] == "fastapi"
