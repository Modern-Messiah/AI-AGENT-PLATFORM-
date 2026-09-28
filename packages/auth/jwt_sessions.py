"""HS256 session tokens and signed OAuth state.

Google login verifies the Google identity once (callback), then issues our
own short-lived session token. The UI sends it as Authorization: Bearer and
require_actor resolves it — same Actor path as API keys. Logout is client
side (drop the token); tokens are stateless and expire at exp.

The OAuth state parameter is itself a signed token (type=state) carrying the
frontend origin that started the flow, so the callback can redirect back
without server-side storage and rejects tampered/cross-site states.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import HTTPException

from packages.core import settings

log = logging.getLogger(__name__)

_SESSION_TTL = timedelta(hours=settings.auth_session_ttl_hours)
_STATE_TTL = timedelta(minutes=10)


class AuthConfigError(HTTPException):
    """Raised when Google login is not configured — surfaced as 503."""

    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            detail=(
                "Google login is not configured: set GOOGLE_CLIENT_ID, "
                "GOOGLE_CLIENT_SECRET, AUTH_JWT_SECRET (and optionally "
                "ADMIN_EMAILS) in .env"
            ),
        )


def google_login_configured() -> bool:
    return bool(
        settings.google_client_id and settings.google_client_secret and settings.auth_jwt_secret
    )


def _now() -> datetime:
    return datetime.now(UTC)


def create_session_token(
    *,
    user_id: uuid.UUID,
    tenant_id: str,
    email: str,
    name: str,
    role: str,
) -> str:
    if not settings.auth_jwt_secret:
        raise AuthConfigError()
    now = _now()
    claims: dict[str, Any] = {
        "type": "session",
        "sub": str(user_id),
        "tid": tenant_id,
        "email": email,
        "name": name,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + _SESSION_TTL).timestamp()),
    }
    return jwt.encode(claims, settings.auth_jwt_secret, algorithm="HS256")


def verify_session_token(token: str) -> dict[str, Any]:
    """Return the claims or raise 401. Only our own session tokens pass."""
    if not settings.auth_jwt_secret:
        raise AuthConfigError()
    try:
        claims = jwt.decode(token, settings.auth_jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status_code=401, detail="session expired") from e
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail="invalid session token") from e
    if claims.get("type") != "session":
        raise HTTPException(status_code=401, detail="invalid session token")
    return claims


def create_oauth_state(*, redirect_uri: str, callback: str) -> str:
    """Sign the login flow origin + API callback (CSRF protection)."""
    if not settings.auth_jwt_secret:
        raise AuthConfigError()
    now = _now()
    claims: dict[str, Any] = {
        "type": "state",
        "redirect_uri": redirect_uri,
        "callback": callback,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + _STATE_TTL).timestamp()),
    }
    return jwt.encode(claims, settings.auth_jwt_secret, algorithm="HS256")


def verify_oauth_state(state: str) -> tuple[str, str]:
    """Return (redirect_uri, callback) or raise 400."""
    if not settings.auth_jwt_secret:
        raise AuthConfigError()
    try:
        claims = jwt.decode(state, settings.auth_jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status_code=400, detail="login state expired — try again") from e
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=400, detail="invalid login state") from e
    if claims.get("type") != "state":
        raise HTTPException(status_code=400, detail="invalid login state")
    redirect_uri = str(claims.get("redirect_uri") or "")
    callback = str(claims.get("callback") or "")
    if not redirect_uri or not callback:
        raise HTTPException(status_code=400, detail="invalid login state")
    return redirect_uri, callback
