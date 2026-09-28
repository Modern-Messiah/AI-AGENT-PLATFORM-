"""Google OAuth login — issues JWT sessions for the user/admin cabinets.

Flow (Authorization Code):
  1. UI calls GET /auth/google/url?redirect=<frontend login URL>
     → {url}: Google consent screen; the redirect target is validated and
     carried inside a signed state token together with the API callback URL.
  2. Google redirects the browser to GET /auth/google/callback?code&state.
     The code is exchanged server-side, the Google ID token is verified
     (audience, issuer, email_verified), the user is matched/created by
     email in the default tenant, and a session JWT is issued.
  3. The browser lands on <redirect>#token=<session jwt> — the fragment
     never reaches any server log.

Admins are Google accounts listed in ADMIN_EMAILS; everyone else logs into
the user cabinet as a member. Requires GOOGLE_CLIENT_ID/SECRET and
AUTH_JWT_SECRET; otherwise these endpoints answer 503 and the UI keeps the
raw API-key path.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated
from urllib.parse import quote, urlencode, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from packages.auth import Actor, require_actor
from packages.auth.jwt_sessions import (
    AuthConfigError,
    create_oauth_state,
    create_session_token,
    google_login_configured,
    verify_oauth_state,
)
from packages.core import settings
from packages.storage import User
from packages.storage.db import async_session
from sqlalchemy import select

from apps.api.schemas import GoogleLoginUrlResponse, SessionInfo

log = logging.getLogger(__name__)
router = APIRouter()

_GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_GOOGLE_TOKENINFO_ENDPOINT = "https://oauth2.googleapis.com/tokeninfo"


def _redirect_allowed(url: str) -> bool:
    """Only let the browser be sent to trusted frontend origins.

    allowed_origins is authoritative when set; in local dev (empty list)
    only loopback origins pass, so a signed state can never be used to
    bounce a freshly issued session token to an attacker's page.
    """
    try:
        origin = "{0.scheme}://{0.netloc}".format(urlparse(url))
    except ValueError:
        return False
    if settings.allowed_origins:
        return origin in [o.strip().rstrip("/") for o in settings.allowed_origins]
    host = urlparse(url).hostname or ""
    return host in ("localhost", "127.0.0.1", "::1")


def _callback_url(request: Request) -> str:
    base = settings.oauth_api_base_url.strip().rstrip("/")
    if base:
        return f"{base}/auth/google/callback"
    return str(request.base_url).rstrip("/") + "/auth/google/callback"


@router.get("/auth/google/url", response_model=GoogleLoginUrlResponse)
async def google_login_url(
    request: Request,
    redirect: str = Query(..., description="Frontend URL to return to after login"),
) -> GoogleLoginUrlResponse:
    """Build the Google consent URL; the UI simply navigates to it."""
    if not google_login_configured():
        raise AuthConfigError()
    redirect = redirect.strip()
    if not redirect.startswith(("http://", "https://")) or not _redirect_allowed(redirect):
        raise HTTPException(status_code=400, detail="redirect URL is not allowed")

    state = create_oauth_state(redirect_uri=redirect, callback=_callback_url(request))
    params = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": _callback_url(request),
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "online",
            "prompt": "select_account",
            "state": state,
        }
    )
    return GoogleLoginUrlResponse(url=f"{_GOOGLE_AUTH_ENDPOINT}?{params}")


async def _exchange_code(code: str, callback: str) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            _GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": callback,
                "grant_type": "authorization_code",
            },
        )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Google token exchange failed")
    return dict(response.json())


async def _verify_google_id_token(id_token: str) -> dict[str, str]:
    """Verify via Google's tokeninfo endpoint: aud/iss/email_verified checks."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(_GOOGLE_TOKENINFO_ENDPOINT, params={"id_token": id_token})
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Google id_token verification failed")
    info = response.json()
    if info.get("aud") != settings.google_client_id:
        raise HTTPException(status_code=401, detail="Google id_token audience mismatch")
    if info.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise HTTPException(status_code=401, detail="Google id_token issuer mismatch")
    if str(info.get("email_verified", "")).lower() != "true":
        raise HTTPException(status_code=401, detail="Google email is not verified")
    email = str(info.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(status_code=401, detail="Google id_token has no email")
    return {
        "email": email,
        "name": str(info.get("name") or email),
    }


async def _upsert_google_user(email: str, name: str, role: str) -> User:
    tenant_id = settings.default_tenant_id
    async with async_session() as s, s.begin():
        user = (
            await s.execute(select(User).where(User.email == email, User.tenant_id == tenant_id))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                name=name or email,
                email=email,
                role=role,
            )
            s.add(user)
        else:
            # Keep display name fresh; role follows ADMIN_EMAILS on every login.
            user.name = name or user.name
            user.role = role
            await s.flush()
    return user


@router.get("/auth/google/callback")
async def google_login_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
) -> RedirectResponse:
    """Finish the OAuth flow: verify, upsert the user, redirect with the token."""
    if not google_login_configured():
        raise AuthConfigError()
    frontend_redirect, callback = verify_oauth_state(state)  # 400 on tampered state

    if error or not code:
        return RedirectResponse(
            url=f"{frontend_redirect}#error={quote(error or 'missing code')}",
            status_code=302,
        )

    tokens = await _exchange_code(code, callback)
    id_token = str(tokens.get("id_token") or "")
    if not id_token:
        raise HTTPException(status_code=502, detail="Google response has no id_token")
    identity = await _verify_google_id_token(id_token)

    role = "admin" if identity["email"] in settings.admin_emails else "member"
    user = await _upsert_google_user(identity["email"], identity["name"], role)
    session_token = create_session_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=identity["email"],
        name=user.name,
        role=role,
    )
    log.info("google login | tenant=%s email=%s role=%s", user.tenant_id, identity["email"], role)
    return RedirectResponse(url=f"{frontend_redirect}#token={session_token}", status_code=302)


@router.get("/auth/me", response_model=SessionInfo)
async def whoami(actor: Annotated[Actor, Depends(require_actor)]) -> SessionInfo:
    """Current principal for either credential path (session or API key)."""
    return SessionInfo(
        tenant_id=actor.tenant_id,
        user_id=str(actor.user_id) if actor.user_id else None,
        user_name=actor.user_name,
        email=actor.email,
        role=actor.role,
        is_admin=actor.is_admin,
    )
