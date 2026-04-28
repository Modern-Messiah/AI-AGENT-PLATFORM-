"""HTTP fetch tool — lets the agent retrieve content from external URLs."""

from __future__ import annotations

import httpx
from pydantic_ai import Agent, RunContext

from packages.agents.deps import AgentDeps

_MAX_CHARS = 20_000
_TIMEOUT = 10.0


def register_http_tool(agent: Agent[AgentDeps, object]) -> None:
    @agent.tool
    async def http_fetch(ctx: RunContext[AgentDeps], url: str) -> str:
        """Fetch the text content of a URL.

        Use this to retrieve external documentation, web pages, or API responses.
        Returns up to 20 000 characters. Only http/https is supported.

        Args:
            url: The full URL to fetch.
        """
        if not url.startswith(("http://", "https://")):
            return "Error: only http/https URLs are supported"

        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                text = resp.text
                if len(text) > _MAX_CHARS:
                    text = text[:_MAX_CHARS] + f"\n… [truncated {len(text) - _MAX_CHARS} chars]"
                return text
            except httpx.HTTPStatusError as e:
                return f"HTTP {e.response.status_code}: {e.response.text[:500]}"
            except httpx.RequestError as e:
                return f"Request error: {e}"
