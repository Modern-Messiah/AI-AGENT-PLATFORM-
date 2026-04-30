"""HTTP fetch tool — lets the agent retrieve content from external URLs.

SSRF protection:
  • Strong mode (recommended for production): set HTTP_FETCH_ALLOWED_DOMAINS to an
    explicit comma-separated list of allowed hostnames.  Only those domains and their
    subdomains can be fetched; all others are rejected before any network I/O.
    This fully prevents SSRF including DNS-rebinding attacks.

  • Fallback mode (development): when no allowlist is configured the tool
    resolves the hostname and rejects RFC-1918 / loopback / link-local ranges.
    NOTE: this is vulnerable to DNS-rebinding — a malicious server can return a
    public IP during validation and a private IP for the actual httpx connection.
    Do not use in production without an allowlist.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from pydantic_ai import Agent, RunContext

from packages.agents.deps import AgentDeps
from packages.core import settings

_MAX_CHARS = 20_000
_TIMEOUT = 10.0


def _allowlist_check(url: str) -> str | None:
    """Return an error if the host is not in HTTP_FETCH_ALLOWED_DOMAINS, else None."""
    host = urlparse(url).hostname or ""
    for domain in settings.http_fetch_allowed_domains:
        if host == domain or host.endswith(f".{domain}"):
            return None
    return f"Error: domain '{host}' is not in the allowed list (set HTTP_FETCH_ALLOWED_DOMAINS)"


async def _ip_blocklist_check(url: str) -> str | None:
    """Return an error if the URL resolves to a private/internal IP, else None.

    ⚠️  This check is bypassed by DNS-rebinding attacks (see module docstring).
    Use the domain allowlist instead in production.
    """
    try:
        host = urlparse(url).hostname
        if not host:
            return "Error: could not parse hostname from URL"
        loop = asyncio.get_event_loop()
        infos = await loop.run_in_executor(None, socket.getaddrinfo, host, None)
        for _, _, _, _, sockaddr in infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_unspecified
                or ip.is_multicast
            ):
                return "Error: requests to private or internal network addresses are not allowed"
    except OSError as e:
        return f"Error: DNS resolution failed: {e}"
    return None


def register_http_tool(agent: Agent[AgentDeps, object]) -> None:
    @agent.tool
    async def http_fetch(ctx: RunContext[AgentDeps], url: str) -> str:
        """Fetch the text content of a URL.

        Use this to retrieve external documentation, web pages, or API responses.
        Returns up to 20 000 characters. Only http/https is supported.
        Internal and private network addresses are blocked.

        Args:
            url: The full URL to fetch.
        """
        if not url.startswith(("http://", "https://")):
            return "Error: only http/https URLs are supported"

        if settings.http_fetch_allowed_domains:
            # Strong protection: domain allowlist fully prevents SSRF + DNS rebinding.
            err = _allowlist_check(url)
        else:
            # Fallback: IP blocklist (vulnerable to DNS rebinding — configure allowlist for prod).
            err = await _ip_blocklist_check(url)

        if err:
            return err

        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=False,  # don't follow redirects — target could redirect to internal host
        ) as client:
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
