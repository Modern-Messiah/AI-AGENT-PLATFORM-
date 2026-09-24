"""Code execution tool — runs Python snippets isolated from the platform.

Disabled by default. Set ENABLE_CODE_EXEC=true in the environment to opt in.

Two execution modes:

1. Subprocess (default, CODE_EXEC_SANDBOX_IMAGE empty):
   - empty environment (no credentials, no DB/MinIO/LLM keys visible)
   - -S (no site-packages — stdlib only), -E (ignore PYTHON* env vars)
   - 10-second wall-clock timeout, output capped

2. Docker sandbox (CODE_EXEC_SANDBOX_IMAGE set, e.g. "python:3.12-slim"):
   the snippet runs in a throwaway container with no network, a memory/cpu
   cap, a pid cap, a read-only root filesystem with a small tmpfs, as an
   unprivileged user, code delivered via stdin (never visible in argv /
   docker inspect). Still not a VM — but it removes the whole
   "hardened subprocess runs on the host" class of risk.

Neither mode is a substitute for a dedicated VM sandbox for genuinely
untrusted code; the docker mode is the recommended deployment posture.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import Sequence

from pydantic_ai import Agent, RunContext

from packages.agents.deps import AgentDeps
from packages.core import settings

_TIMEOUT = 10.0
_MINIMAL_ENV = {"PATH": "/usr/bin:/bin"}  # bare minimum; no credentials
_MAX_OUTPUT_CHARS = 8_000


def _truncate(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return text[:_MAX_OUTPUT_CHARS] + f"\n… (output truncated at {_MAX_OUTPUT_CHARS} chars)"


def _subprocess_args(code: str) -> tuple[Sequence[str], str | None]:
    """Host subprocess mode: python -S -E -c <code>, code as argv."""
    return (sys.executable, "-S", "-E", "-c", code), None


def _docker_args(code: str, image: str) -> tuple[Sequence[str], str | None]:
    """Docker mode: code goes to stdin so it never lands in argv/inspect."""
    return (
        "docker",
        "run",
        "--rm",
        "--network=none",
        "--memory=256m",
        "--cpus=0.5",
        "--pids-limit=64",
        "--read-only",
        "--tmpfs=/tmp:rw,size=16m",
        "--user=65534:65534",
        "--interactive",
        image,
        "python",
        "-S",
        "-E",
        "-",
    ), code


async def run_snippet(code: str) -> str:
    """Execute a snippet in the configured mode and return capped output."""
    image = settings.code_exec_sandbox_image.strip()
    if image:
        argv, stdin_data = _docker_args(code, image)
    else:
        argv, stdin_data = _subprocess_args(code)

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
            env=None if image else _MINIMAL_ENV,
        )
        stdin_bytes = stdin_data.encode() if stdin_data is not None else None
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin_bytes), timeout=_TIMEOUT
        )
    except TimeoutError:
        with contextlib.suppress(Exception):
            proc.kill()
        return f"Error: timed out after {_TIMEOUT:.0f}s"
    except Exception as e:
        return f"Error launching subprocess: {e}"

    out = _truncate(stdout.decode(errors="replace").strip())
    err = _truncate(stderr.decode(errors="replace").strip())
    if proc.returncode != 0:
        return f"Error: exit code {proc.returncode}\nstdout:\n{out}\nstderr:\n{err}"
    if err:
        return f"stdout:\n{out}\nstderr:\n{err}" if out else f"stderr:\n{err}"
    return out or "(no output)"


def register_code_exec_tool(agent: Agent[AgentDeps, object]) -> None:
    @agent.tool
    async def code_exec(ctx: RunContext[AgentDeps], code: str) -> str:
        """Execute a Python code snippet and return its output.

        Use this for calculations, data transformation, JSON parsing, or any
        computation that is easier to do in code than in prose.
        Use print() to produce output. Timeout: 10 seconds.
        Only the Python standard library is available (no third-party packages).

        Args:
            code: Python source code to execute.
        """
        return await run_snippet(code)
