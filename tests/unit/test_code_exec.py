from __future__ import annotations

import pytest
from packages.agents.tools import code_exec as code_exec_module
from packages.agents.tools.code_exec import (
    _docker_args,
    _subprocess_args,
    _truncate,
    run_snippet,
)
from packages.core import settings


def test_docker_args_isolate_the_snippet() -> None:
    argv, stdin_data = _docker_args("print('hi')", "python:3.12-slim")

    joined = " ".join(argv)
    assert "--network=none" in joined
    assert "--memory=256m" in joined
    assert "--cpus=0.5" in joined
    assert "--pids-limit=64" in joined
    assert "--read-only" in joined
    assert "--tmpfs=/tmp:rw,size=16m" in joined
    assert "--user=65534:65534" in joined
    # the snippet itself travels via stdin — never argv / docker inspect
    assert "print('hi')" not in joined
    assert stdin_data == "print('hi')"
    assert argv[-4:] == ("python", "-S", "-E", "-")


def test_subprocess_args_keep_legacy_hardening() -> None:
    argv, stdin_data = _subprocess_args("print('hi')")

    assert argv[1:4] == ("-S", "-E", "-c")
    assert argv[4] == "print('hi')"
    assert stdin_data is None


def test_truncate_caps_output() -> None:
    huge = "x" * 20_000
    truncated = _truncate(huge)
    assert len(truncated) < 9_000
    assert "truncated" in truncated
    assert _truncate("short") == "short"


async def test_run_snippet_reports_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "code_exec_sandbox_image", "")

    class _FakeProc:
        returncode = 1

        async def communicate(self, input=None):
            return b"", b"boom"

    async def fake_exec(*argv, **kwargs):
        return _FakeProc()

    monkeypatch.setattr(code_exec_module.asyncio, "create_subprocess_exec", fake_exec)

    result = await run_snippet("raise SystemExit(1)")
    assert result.startswith("Error: exit code 1")
    assert "boom" in result


async def test_run_snippet_docker_mode_passes_code_via_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "code_exec_sandbox_image", "python:3.12-slim")
    captured: dict = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self, input=None):
            captured["stdin"] = input
            return b"42\n", b""

    async def fake_exec(*argv, **kwargs):
        captured["argv"] = argv
        return _FakeProc()

    monkeypatch.setattr(code_exec_module.asyncio, "create_subprocess_exec", fake_exec)

    result = await run_snippet("print(6 * 7)")

    assert result == "42"
    assert captured["argv"][0] == "docker"
    assert captured["stdin"] == b"print(6 * 7)"
