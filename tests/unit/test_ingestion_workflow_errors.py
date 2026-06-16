from __future__ import annotations

from temporalio.exceptions import ActivityError

from apps.worker.workflows.ingestion import _activity_root_cause_message


def _activity_error(message: str = "Activity task failed") -> ActivityError:
    return ActivityError(
        message,
        scheduled_event_id=1,
        started_event_id=2,
        identity="worker",
        activity_type="parse_document",
        activity_id="parse-document-1",
        retry_state=None,
    )


def test_activity_root_cause_message_uses_deepest_real_error() -> None:
    activity_error = _activity_error()
    wrapper = RuntimeError("Activity task failed")
    root = ValueError("PDF parser failed: encrypted file requires a password")
    activity_error.__cause__ = wrapper
    wrapper.__cause__ = root

    assert (
        _activity_root_cause_message(activity_error)
        == "PDF parser failed: encrypted file requires a password"
    )


def test_activity_root_cause_message_falls_back_to_exception_type() -> None:
    activity_error = _activity_error()
    root = RuntimeError()
    activity_error.__cause__ = root

    assert _activity_root_cause_message(activity_error) == "RuntimeError"


def test_activity_root_cause_message_truncates_long_errors() -> None:
    activity_error = _activity_error()
    activity_error.__cause__ = ValueError("x" * 2500)

    message = _activity_root_cause_message(activity_error)

    assert len(message) == 2000
    assert message == "x" * 2000
