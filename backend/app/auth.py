"""Sign-in, sessions, roles and per-org access.

- Passwords are hashed with scrypt (salted, slow by design); only the hash is stored.
- A session is a random token in an HttpOnly cookie; only its SHA-256 is stored, so a database leak can't be replayed.
- Roles: admin (everything, incl. users and app keys), consultant (works on assigned orgs), viewer (read-only).
- Each user sees only their orgs (admins and "all orgs" users see every org) and has their own active org.

The middleware resolves the signed-in user once per request and keeps it in a context variable, so code deep
in the app (e.g. which Salesforce org is "active") can respect it without passing the user around.
"""
import base64
import hashlib
import hmac
import secrets
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import Settings, get_settings
from .db import SessionLocal
from .models import SessionRow, UserRow

COOKIE = "aq_session"
ROLES = ("admin", "consultant", "viewer")
MIN_PASSWORD = 10
MAX_FAILED = 5
LOCK_MINUTES = 15
SESSION_SHORT = timedelta(hours=12)
SESSION_LONG = timedelta(days=30)
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 2**14, 8, 1
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        algo, n, r, p, salt, digest = (stored or "").split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))  # so unknown emails take as long as wrong passwords


def check_password_rules(password: str, email: str | None = None) -> None:
    if len(password) < MIN_PASSWORD:
        raise HTTPException(422, f"Use at least {MIN_PASSWORD} characters.")
    if len(password) > 200:
        raise HTTPException(422, "That password is too long.")
    if email and password.lower() == email.lower():
        raise HTTPException(422, "Don’t use your email address as your password.")
    if password.isdigit() or len(set(password)) < 4:
        raise HTTPException(422, "Choose a less predictable password.")


# ---------------------------------------------------------------- current user

@dataclass(frozen=True)
class Principal:
    id: str
    name: str
    email: str
    role: str
    all_orgs: bool
    org_ids: frozenset[str] = field(default_factory=frozenset)
    active_org_id: str | None = None
    session_id: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def can_edit(self) -> bool:
        return self.role in ("admin", "consultant")

    def sees(self, org_id: str | None) -> bool:
        return self.is_admin or self.all_orgs or (org_id or "") in self.org_ids

    def allowed(self) -> frozenset[str] | None:
        """Org ids this user may see, or None for every org."""
        return None if (self.is_admin or self.all_orgs) else self.org_ids


_current: ContextVar[Principal | None] = ContextVar("aquarient_user", default=None)


def current() -> Principal | None:
    return _current.get()


def principal(user: UserRow, session_id: str | None = None) -> Principal:
    return Principal(id=user.id, name=user.name, email=user.email, role=user.role, all_orgs=bool(user.all_orgs),
                     org_ids=frozenset(user.org_ids or []), active_org_id=user.active_org_id, session_id=session_id)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: UserRow, remember: bool, user_agent: str | None) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = _now() + (SESSION_LONG if remember else SESSION_SHORT)
    db.add(SessionRow(id=token_hash(token), user_id=user.id, expires_at=expires, user_agent=(user_agent or "")[:255]))
    db.execute(delete(SessionRow).where(SessionRow.expires_at < _now()))  # tidy up old sessions
    db.commit()
    return token, expires


def end_sessions(db: Session, user_id: str, keep: str | None = None) -> None:
    q = delete(SessionRow).where(SessionRow.user_id == user_id)
    if keep:
        q = q.where(SessionRow.id != keep)
    db.execute(q)
    db.commit()


def _user_for_token(token: str | None) -> Principal | None:
    if not token or len(token) > 200:
        return None
    with SessionLocal() as db:
        s = db.get(SessionRow, token_hash(token))
        if s is None or (_utc(s.expires_at) or _now()) <= _now():
            return None
        user = db.get(UserRow, s.user_id)
        if user is None or not user.is_active:
            return None
        if s.last_seen_at is None or _now() - (_utc(s.last_seen_at) or _now()) > timedelta(minutes=5):
            s.last_seen_at = _now()
            db.commit()
        return principal(user, s.id)


def _cookie(scope: Scope) -> str | None:
    for k, v in scope.get("headers") or []:
        if k == b"cookie":
            for part in v.decode("latin-1").split(";"):
                name, _, value = part.strip().partition("=")
                if name == COOKIE:
                    return value
    return None


def _header(scope: Scope, name: bytes) -> str | None:
    return next((v.decode("latin-1") for k, v in scope.get("headers") or [] if k == name), None)


def _origin_ok(origin: str | None, settings: Settings, host: str | None) -> bool:
    """Block other websites from sending requests with the user's cookie (CSRF)."""
    if not origin:
        return True  # not sent by browsers for same-origin GETs, nor by non-browser clients (which can't use the cookie anyway)
    allowed = {settings.frontend_origin.rstrip("/")}
    if host:
        allowed |= {f"http://{host}", f"https://{host}"}
    return origin.rstrip("/") in allowed


class AuthMiddleware:
    """Resolve the signed-in user for each API request (or the local admin when sign-in is turned off)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        settings = get_settings()
        if scope.get("method") in UNSAFE and not _origin_ok(_header(scope, b"origin"), settings, _header(scope, b"host")):
            return await _json(send, 403, "This request came from another website, so it was blocked.")
        user = _user_for_token(_cookie(scope)) if settings.auth_required else _local_admin()
        token = _current.set(user)
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)


def _local_admin() -> Principal:
    s = get_settings()
    return Principal(id="local-user", name=s.local_user_name, email=s.local_user_email, role="admin", all_orgs=True)


async def _json(send: Send, status: int, detail: str) -> None:
    import json

    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


# ---------------------------------------------------------------- FastAPI dependencies

def require_user() -> Principal:
    user = current()
    if user is None:
        raise HTTPException(401, "Please sign in.")
    return user


def require_editor(user: Principal = Depends(require_user)) -> Principal:
    if not user.can_edit:
        raise HTTPException(403, "Your role is view-only. Ask an admin if you need to make changes.")
    return user


def require_admin(user: Principal = Depends(require_user)) -> Principal:
    if not user.is_admin:
        raise HTTPException(403, "Only admins can do this.")
    return user


def ensure_org(org_id: str | None, not_found: str = "Not found.") -> Principal:
    """The current user may see this org; otherwise behave as if it doesn't exist (404)."""
    user = require_user()
    if not user.sees(org_id):
        raise HTTPException(404, not_found)
    return user


def user_count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(UserRow)) or 0)


def secure_cookie(settings: Settings) -> bool:
    return urlparse(settings.frontend_origin).scheme == "https"
