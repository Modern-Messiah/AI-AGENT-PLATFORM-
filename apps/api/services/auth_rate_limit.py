"""Per-IP rate limits for the auth and admin surfaces.

These endpoints answer 401/403 without any limiter today, which makes the
admin secret brute-forceable. The shared Redis sliding window
(services/rate_limit.py), keyed by the peer IP instead of the tenant. Fails open when Redis
is unavailable (RATE_LIMIT_FAIL_CLOSED=true makes it fail closed), matching
the platform-wide availability choice.
"""

from __future__ import annotations

import ipaddress
import logging

from fastapi import HTTPException, Request
from packages.cache.redis import get_redis
from packages.core import settings

from apps.api.services.rate_limit import check_sliding_window_limit

log = logging.getLogger(__name__)

# Management surfaces are used rarely; the admin panel makes a handful of
# calls per tab switch. Both limits sit far above normal use.
AUTH_LIMIT_PER_MINUTE = 15
ADMIN_LIMIT_PER_MINUTE = 60


def _is_trusted_proxy(peer_ip: str, trusted_list: list[str]) -> bool:
    try:
        peer = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    for item in trusted_list:
        item = item.strip()
        if not item:
            continue
        try:
            if "/" in item:
                if peer in ipaddress.ip_network(item, strict=False):
                    return True
            elif peer == ipaddress.ip_address(item):
                return True
        except ValueError:
            continue
    return False


def _client_ip(request: Request) -> str:
    # Direct peer IP
    client = request.client
    direct_ip = client.host if client else "unknown"
    if not settings.trusted_proxies:
        return direct_ip

    trusted = [p.strip() for p in settings.trusted_proxies.split(",") if p.strip()]
    if not _is_trusted_proxy(direct_ip, trusted):
        return direct_ip

    xff = request.headers.get("X-Forwarded-For")
    if not xff:
        return direct_ip

    # Walk from right to left through proxies until the first untrusted IP
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    for ip_str in reversed(parts):
        if not _is_trusted_proxy(ip_str, trusted):
            return ip_str

    return parts[0] if parts else direct_ip


async def _check(key: str, limit: int) -> None:
    await check_sliding_window_limit(
        get_redis(),
        key,
        limit=limit,
        window_ms=60_000,
        label="requests per minute",
    )


async def _enforce(request: Request, bucket: str, limit: int) -> None:
    key = f"rl:{_client_ip(request)}:{bucket}"
    try:
        await _check(key, limit)
    except HTTPException:
        raise  # 429 from _check is the limiter working — always propagate
    except Exception:
        if settings.rate_limit_fail_closed:
            raise HTTPException(status_code=503, detail="rate limiter unavailable") from None
        log.warning("auth rate limit check failed (fail-open) | bucket=%s", bucket)


async def enforce_auth_rate_limit(request: Request) -> None:
    """FastAPI dependency for /auth/* — key issuance and user management."""
    await _enforce(request, "auth", AUTH_LIMIT_PER_MINUTE)


async def enforce_admin_rate_limit(request: Request) -> None:
    """FastAPI dependency for /admin/* — the admin-secret surface."""
    await _enforce(request, "admin", ADMIN_LIMIT_PER_MINUTE)
