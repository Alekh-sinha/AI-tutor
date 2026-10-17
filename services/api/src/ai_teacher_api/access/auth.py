"""Sign-in with Google, a signed session cookie, and the FastAPI dependencies that decide who may call what.
AUTH_MODE=off (default for local development): everyone is the admin user `dev@local`, nothing changes from before.
AUTH_MODE=on: the browser sends the Google ID token once (POST /auth/google); we check it with Google's keys, and answer with an HttpOnly cookie that
carries our own signed session (7 days). A cookie works for fetch, SSE and WebSocket alike because the web app and the API share one address.
AUTH_DEV_LOGIN=1 additionally allows GET /auth/dev?email=... for automated tests (never set it on the deployed service)."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import HTTPException, Request, WebSocket

from ai_teacher_api.access import credits, usage

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
SECRET = (os.environ.get("SESSION_SECRET") or secrets.token_hex(32)).encode()  # unset = a new secret per start (sign-ins end on restart)
COOKIE = "ss_session"
DAYS = 7
DEV = "dev@local"


def mode() -> str:
    """"off" (local development: everyone is the admin) or "on" (sign-in required). Read on every call so tests can switch it."""
    return os.environ.get("AUTH_MODE", "off")


def make_session(email: str, days: int = DAYS) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"e": email, "x": int(time.time()) + days * 86400}).encode()).decode()
    sig = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_session(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()):
        return None
    try:
        p = json.loads(base64.urlsafe_b64decode(body.encode()))
    except Exception:  # noqa: BLE001
        return None
    return p["e"] if p.get("x", 0) > time.time() else None


def verify_google(credential: str) -> dict:
    """Check a Google ID token (signature, audience = our client id, expiry). Returns the claims."""
    from google.auth.transport import requests as greq
    from google.oauth2 import id_token

    if not GOOGLE_CLIENT_ID:
        raise HTTPException(503, "sign-in is not configured (GOOGLE_CLIENT_ID)")
    try:
        claims = id_token.verify_oauth2_token(credential, greq.Request(), GOOGLE_CLIENT_ID)
    except ValueError as e:
        raise HTTPException(401, "Google sign-in could not be verified") from e
    if not claims.get("email_verified"):
        raise HTTPException(401, "the Google email is not verified")
    return claims


def _user_for(email: str | None) -> dict | None:
    if mode() == "off":
        credits.ADMIN_EMAILS.add(DEV)
        return credits.get(DEV) or credits.login(DEV, "Local admin")
    return credits.get(email) if email else None


async def optional_user(request: Request) -> dict | None:
    """The signed-in user's document or None (anonymous). Also binds the user to this request for cost metering."""
    u = _user_for(read_session(request.cookies.get(COOKIE)))
    usage.set_user(u["email"] if u else None)
    return u


async def active_user(request: Request) -> dict:
    """A signed-in user the admin has approved (or the admin). Pending / blocked users get a clear reason, anonymous visitors a 401."""
    u = await optional_user(request)
    if u is None:
        raise HTTPException(401, {"code": "sign_in", "message": "Please sign in to continue."})
    if u["status"] == "blocked":
        raise credits.Blocked()
    if u["status"] != "active":
        raise credits.NotApproved()
    return u


async def admin_user(request: Request) -> dict:
    u = await active_user(request)
    if u["role"] != "admin":
        raise HTTPException(403, "admin only")
    return u


def ws_user(ws: WebSocket) -> dict | None:
    """The approved user of a WebSocket (same cookie), bound for metering; None when not allowed."""
    u = _user_for(read_session(ws.cookies.get(COOKIE)))
    if u is None or u["status"] != "active":
        return None
    usage.set_user(u["email"])
    return u


def set_cookie(response, request: Request, email: str) -> None:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, make_session(email), max_age=DAYS * 86400, httponly=True, samesite="lax", secure=secure, path="/")


def user_for_scope(scope) -> dict | None:
    """The user behind a raw ASGI scope (static file mounts have no dependencies)."""
    from starlette.requests import Request as R

    return _user_for(read_session(R(scope).cookies.get(COOKIE)))
