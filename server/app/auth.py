"""Authentication & authorization.

- argon2id password hashing
- server-side sessions (httponly, SameSite=Lax cookies; Secure behind TLS proxy)
- CSRF: per-session token, required as X-CSRF-Token header on unsafe methods
- login rate limiting with exponential backoff per (ip, username)
- roles: admin > operator > viewer
- optional Home Assistant ingress mode: requests from the trusted ingress
  proxy are mapped to a configured role (never enabled by default)
"""

from __future__ import annotations

import hashlib
import ipaddress
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response

from .db import User, WebSession, audit, db
from .settings import settings

_ph = PasswordHasher()  # argon2id defaults (current RFC 9106 parameters)

ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2}
COOKIE = "pool_session"

# (ip, username) -> [fail_count, locked_until]
_login_fails: dict[tuple[str, str], list[float]] = {}
_MAX_BEFORE_BACKOFF = 5


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw_hash: str, pw: str) -> bool:
    try:
        return _ph.verify(pw_hash, pw)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    xff = request.headers.get("x-forwarded-for")
    if xff and _is_trusted_proxy(peer):
        return xff.split(",")[0].strip()
    return peer


def _is_trusted_proxy(peer: str) -> bool:
    for spec in settings.trusted_proxies:
        try:
            if "/" in spec:
                if ipaddress.ip_address(peer) in ipaddress.ip_network(spec, strict=False):
                    return True
            elif peer == spec:
                return True
        except ValueError:
            continue
    return False


def check_rate_limit(ip: str, username: str) -> None:
    rec = _login_fails.get((ip, username))
    if rec and time.time() < rec[1]:
        raise HTTPException(429, "too_many_attempts")


def record_login_result(ip: str, username: str, ok: bool) -> None:
    key = (ip, username)
    if ok:
        _login_fails.pop(key, None)
        return
    rec = _login_fails.setdefault(key, [0, 0.0])
    rec[0] += 1
    if rec[0] >= _MAX_BEFORE_BACKOFF:
        backoff = min(2 ** (rec[0] - _MAX_BEFORE_BACKOFF) * 30, 3600)
        rec[1] = time.time() + backoff


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user: User, request: Request, response: Response) -> dict:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    s = db()
    try:
        s.add(WebSession(
            token_hash=_token_hash(token), user_id=user.id, csrf=csrf,
            expires=time.time() + settings.session_ttl_s,
            ip=client_ip(request)))
        s.commit()
    finally:
        s.close()
    secure = settings.secure_cookies == "always" or (
        settings.secure_cookies == "auto"
        and request.headers.get("x-forwarded-proto", request.url.scheme) == "https")
    response.set_cookie(
        COOKIE, token, max_age=settings.session_ttl_s, httponly=True,
        samesite="lax", secure=secure, path="/")
    return {"csrf": csrf}


def destroy_session(request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        s = db()
        try:
            row = s.get(WebSession, _token_hash(token))
            if row:
                s.delete(row)
                s.commit()
        finally:
            s.close()
    response.delete_cookie(COOKIE, path="/")


class Identity:
    def __init__(self, username: str, role: str, user_id: int | None,
                 csrf: str | None, via_ingress: bool = False):
        self.username = username
        self.role = role
        self.user_id = user_id
        self.csrf = csrf
        self.via_ingress = via_ingress


def _ingress_identity(request: Request) -> Identity | None:
    if settings.auth_mode != "ingress":
        return None
    peer = request.client.host if request.client else ""
    if _is_trusted_proxy(peer) or peer.startswith("172.30.32."):
        user = request.headers.get("x-remote-user-name") \
            or request.headers.get("x-remote-user-id") or "ingress"
        return Identity(user, settings.ingress_role, None, None, True)
    return None


def current_identity(request: Request) -> Identity | None:
    ing = _ingress_identity(request)
    if ing:
        return ing
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    s = db()
    try:
        row = s.get(WebSession, _token_hash(token))
        if row is None or row.expires < time.time():
            if row is not None:
                s.delete(row)
                s.commit()
            return None
        user = s.get(User, row.user_id)
        if user is None or user.disabled:
            return None
        return Identity(user.username, user.role, user.id, row.csrf)
    finally:
        s.close()


def require_auth(request: Request) -> Identity:
    ident = current_identity(request)
    if ident is None:
        raise HTTPException(401, "not_authenticated")
    if request.method not in ("GET", "HEAD", "OPTIONS") and not ident.via_ingress:
        header = request.headers.get("x-csrf-token", "")
        if not ident.csrf or not secrets.compare_digest(header, ident.csrf):
            raise HTTPException(403, "csrf_failed")
    return ident


def require_role(min_role: str):
    def dep(request: Request, ident: Identity = Depends(require_auth)) -> Identity:
        if ROLE_RANK.get(ident.role, -1) < ROLE_RANK[min_role]:
            raise HTTPException(403, "insufficient_role")
        return ident
    return dep


def any_users_exist() -> bool:
    s = db()
    try:
        return s.query(User.id).first() is not None
    finally:
        s.close()


def cleanup_sessions() -> None:
    s = db()
    try:
        s.query(WebSession).filter(WebSession.expires < time.time()).delete()
        s.commit()
    finally:
        s.close()


def log_audit(user: str, action: str, detail: dict | str = "") -> None:
    s = db()
    try:
        audit(s, user, action, detail)
    finally:
        s.close()
