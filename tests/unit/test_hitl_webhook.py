from __future__ import annotations

import pytest
from apps.worker.activities import human_approval as hitl_module
from apps.worker.activities.human_approval import request_human_approval, send_hitl_webhook


def _payload() -> dict:
    return {
        "workflow_id": "agent-run-tenant-abc-123",
        "confidence": 0.82,
        "user_query": "Какие ограничения у тарифа?",
        "answer": "Ответ с цитатами [1] на длинный вопрос про тарифные ограничения.",
    }


async def test_webhook_skipped_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hitl_module.settings, "hitl_webhook_url", "")

    async def fail_post(*args: object, **kwargs: object) -> None:
        raise AssertionError("no url configured — nothing must be sent")

    monkeypatch.setattr(hitl_module.httpx, "AsyncClient", fail_post)
    await send_hitl_webhook(_payload())


async def test_webhook_posts_slack_compatible_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hitl_module.settings, "hitl_webhook_url", "https://hooks.example/test")
    monkeypatch.setattr(hitl_module.settings, "hitl_webhook_base_url", "https://aap.example.com")

    captured: dict = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class _FakeClient:
        def __init__(self, timeout: float | None = None) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, json: dict) -> _FakeResponse:
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse()

    monkeypatch.setattr(hitl_module.httpx, "AsyncClient", _FakeClient)

    await send_hitl_webhook(_payload())

    assert captured["url"] == "https://hooks.example/test"
    body = captured["json"]
    assert "text" in body  # Slack renders this field
    assert "agent-run-tenant-abc-123" in body["text"]
    assert "https://aap.example.com/api/workflows/agent-run-tenant-abc-123/approve" in body["text"]
    assert len(body["answer_preview"]) <= 280


async def test_webhook_never_raises_on_delivery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hitl_module.settings, "hitl_webhook_url", "https://hooks.example/test")

    class _Boom:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self):
            raise RuntimeError("network down")

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(hitl_module.httpx, "AsyncClient", _Boom)

    # must not raise — the workflow waits for the signal either way
    await send_hitl_webhook(_payload())


async def test_activity_uses_injected_notifier() -> None:
    seen: list[dict] = []

    async def fake_notify(payload: dict) -> None:
        seen.append(payload)

    payload = _payload()
    # request_human_approval is wrapped by @activity.defn; the raw fn is callable
    # outside a worker context through the __wrapped__ attribute temporalio sets.
    raw = getattr(request_human_approval, "__wrapped__", request_human_approval)
    await raw(payload, notify=fake_notify)

    assert seen == [payload]
