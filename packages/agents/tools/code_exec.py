"""Code execution tool — runs Python snippets in an isolated subprocess."""

from __future__ import annotations

import asyncio
import sys

from pydantic_ai import Agent, RunContext

from packages.agents.deps import AgentDeps

_TIMEOUT = 10.0


def register_code_exec_tool(agent: Agent[AgentDeps, object]) -> None:
    @agent.tool
    async def code_exec(ctx: RunContext[AgentDeps], code: str) -> str:
        """Execute a Python code snippet and return its output.

        Use this for calculations, data transformation, JSON parsing, or any
        computation that is easier to do in code than in prose.
        Use print() to produce output. Timeout: 10 seconds.

        Args:
            code: Python source code to execute.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
        except asyncio.TimeoutError:
            return f"Error: timed out after {_TIMEOUT:.0f}s"
        except Exception as e:  # noqa: BLE001
            return f"Error launching subprocess: {e}"

        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()
        if err:
            return f"stdout:\n{out}\nstderr:\n{err}" if out else f"stderr:\n{err}"
        return out or "(no output)"
