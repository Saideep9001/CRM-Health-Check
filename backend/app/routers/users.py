"""Sign-in, first-run setup, your profile and password, and team management (admins)."""
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth
from ..auth import Principal, require_admin, require_user
from ..config import Settings
from ..db import get_db
from ..deps import settings_dep
from ..models import UserRow
from ..schemas import ApiModel, UserProfile

router = APIRouter(tags=["users"])
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginRequest(ApiModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    remember_me: bool = False


class SetupRequest(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class SetupStatus(ApiModel):
    needs_setup: bool
    auth_required: bool


class PasswordChange(ApiModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class ProfileUpdate(ApiModel):
    name: str | None = Field(None, max_length=120)
    title: str | None = Field(None, max_length=120)


class TeamMember(ApiModel):
    id: str
    name: str
    email: str
    title: str | None = None
    role: str
    all_orgs: bool
    org_ids: list[str] = []
    is_active: bool
    created_at: datetime | None = None
    last_login_at: datetime | None = None


class TeamMemberCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=254)
    role: str = "consultant"
    all_orgs: bool = False
    org_ids: list[str] = Field(default_factory=list, max_length=500)
    password: str = Field(max_length=200)


class TeamMemberUpdate(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    role: str | None = None
    all_orgs: bool | None = None
    org_ids: list[str] | None = Field(None, max_length=500)
    is_active: bool | None = None


class PasswordReset(ApiModel):
    password: str = Field(max_length=200)


def _utc(dt):
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def _email(value: str) -> str:
    e = (value or "").strip().lower()
    if not EMAIL.match(e):
        raise HTTPException(422, "Enter a valid email address.")
    return e


def profile(p: Principal) -> UserProfile:
    with_title = None
    if p.id != "local-user":
        from ..db import SessionLocal

        with SessionLocal() as db:
            row = db.get(UserRow, p.id)
            with_title = row.title if row else None
    return UserProfile(id=p.id, name=p.name, email=p.email, title=with_title, role=p.role)


def _member(u: UserRow) -> TeamMember:
    return TeamMember(id=u.id, name=u.name, email=u.email, title=u.title, role=u.role, all_orgs=u.role == "admin" or bool(u.all_orgs),
                      org_ids=list(u.org_ids or []), is_active=u.is_active, created_at=_utc(u.created_at), last_login_at=_utc(u.last_login_at))


def _start_session(db: Session, user: UserRow, remember: bool, request: Request, response: Response, settings: Settings) -> None:
    token, expires = auth.create_session(db, user, remember, request.headers.get("user-agent"))
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="lax", secure=auth.secure_cookie(settings), path="/",
                        max_age=int((expires - datetime.now(timezone.utc)).total_seconds()) if remember else None)


# ---------------------------------------------------------------- sign-in

@router.get("/auth/setup-status", response_model=SetupStatus)
def setup_status(db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    return SetupStatus(needs_setup=settings.auth_required and auth.user_count(db) == 0, auth_required=settings.auth_required)


@router.post("/auth/setup", response_model=UserProfile, status_code=201)
def setup(body: SetupRequest, request: Request, response: Response, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    """Create the first admin. Only works while there are no users at all."""
    if auth.user_count(db) > 0:
        raise HTTPException(409, "Setup is already done. Sign in instead.")
    email = _email(body.email)
    auth.check_password_rules(body.password, email)
    user = UserRow(id=str(uuid.uuid4()), email=email, name=body.name.strip(), password_hash=auth.hash_password(body.password),
                   role="admin", all_orgs=True, is_active=True, last_login_at=datetime.now(timezone.utc))
    db.add(user)
    db.commit()
    _start_session(db, user, False, request, response, settings)
    return profile(auth.principal(user))


@router.post("/auth/login", response_model=UserProfile)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    wrong = HTTPException(401, "That email and password don’t match.")
    user = db.scalars(select(UserRow).where(UserRow.email == (body.email or "").strip().lower())).first()
    now = datetime.now(timezone.utc)
    if user is None:
        auth.verify_password(body.password, auth._DUMMY_HASH)  # same timing as a real check
        raise wrong
    if _utc(user.locked_until) and _utc(user.locked_until) > now:
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes or ask an admin to reset your password.")
    if not auth.verify_password(body.password, user.password_hash):
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= auth.MAX_FAILED:
            user.locked_until, user.failed_logins = now + timedelta(minutes=auth.LOCK_MINUTES), 0
        db.commit()
        raise wrong
    if not user.is_active:
        raise HTTPException(403, "This account has been deactivated. Ask an admin.")
    user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
    db.commit()
    _start_session(db, user, body.remember_me, request, response, settings)
    return profile(auth.principal(user))


@router.post("/auth/logout", status_code=204)
def logout(response: Response, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    user = auth.current()
    if user and user.session_id:
        from ..models import SessionRow

        s = db.get(SessionRow, user.session_id)
        if s:
            db.delete(s)
            db.commit()
    response.delete_cookie(auth.COOKIE, path="/", secure=auth.secure_cookie(settings), httponly=True, samesite="lax")
    response.status_code = 204
    return response


@router.post("/auth/password/forgot", status_code=501)
@router.post("/auth/sso/start", status_code=501)
def not_available():
    raise HTTPException(501, "Ask your administrator to reset your password. Single sign-on isn’t set up yet.")


# ---------------------------------------------------------------- you

@router.get("/me", response_model=UserProfile)
def me(user: Principal = Depends(require_user)):
    return profile(user)


@router.patch("/me", response_model=UserProfile)
def update_me(body: ProfileUpdate, user: Principal = Depends(require_user), db: Session = Depends(get_db)):
    row = db.get(UserRow, user.id)
    if row is None:
        raise HTTPException(409, "The local user can’t be edited while sign-in is turned off.")
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(422, "Name is required.")
        row.name = body.name.strip()
    if body.title is not None:
        row.title = body.title.strip() or None
    db.commit()
    return profile(auth.principal(row))


@router.post("/me/password", status_code=204)
def change_password(body: PasswordChange, user: Principal = Depends(require_user), db: Session = Depends(get_db)):
    row = db.get(UserRow, user.id)
    if row is None or not auth.verify_password(body.current_password, row.password_hash):
        raise HTTPException(422, "Your current password isn’t right.")
    auth.check_password_rules(body.new_password, row.email)
    row.password_hash = auth.hash_password(body.new_password)
    db.commit()
    auth.end_sessions(db, row.id, keep=user.session_id)  # sign out everywhere else
    return Response(status_code=204)


# ---------------------------------------------------------------- team (admins)

def _check_role(role: str) -> str:
    if role not in auth.ROLES:
        raise HTTPException(422, "Role must be admin, consultant or viewer.")
    return role


def _active_admins(db: Session, excluding: str | None = None) -> int:
    q = select(func.count()).select_from(UserRow).where(UserRow.role == "admin", UserRow.is_active.is_(True))
    if excluding:
        q = q.where(UserRow.id != excluding)
    return int(db.scalar(q) or 0)


@router.get("/users", response_model=list[TeamMember])
def list_users(_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return [_member(u) for u in db.scalars(select(UserRow).order_by(UserRow.name))]


@router.post("/users", response_model=TeamMember, status_code=201)
def create_user(body: TeamMemberCreate, _: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    email = _email(body.email)
    if db.scalars(select(UserRow).where(UserRow.email == email)).first():
        raise HTTPException(409, "Someone with that email already has an account.")
    auth.check_password_rules(body.password, email)
    role = _check_role(body.role)
    user = UserRow(id=str(uuid.uuid4()), email=email, name=body.name.strip(), password_hash=auth.hash_password(body.password), role=role,
                   all_orgs=role == "admin" or body.all_orgs, org_ids=sorted(set(body.org_ids)), is_active=True)
    db.add(user)
    db.commit()
    return _member(user)


@router.patch("/users/{user_id}", response_model=TeamMember)
def update_user(user_id: str, body: TeamMemberUpdate, me_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(UserRow, user_id)
    if user is None:
        raise HTTPException(404, "User not found.")
    losing_admin = (body.role is not None and body.role != "admin") or body.is_active is False
    if user.role == "admin" and losing_admin and _active_admins(db, excluding=user.id) == 0:
        raise HTTPException(409, "Keep at least one active admin.")
    if body.name is not None:
        user.name = body.name.strip()
    if body.role is not None:
        user.role = _check_role(body.role)
    if body.all_orgs is not None:
        user.all_orgs = body.all_orgs
    if body.org_ids is not None:
        user.org_ids = sorted(set(body.org_ids))
    if user.role == "admin":
        user.all_orgs = True
    if body.is_active is not None:
        user.is_active = body.is_active
    db.commit()
    if body.is_active is False or body.role is not None or body.org_ids is not None or body.all_orgs is not None:
        if user.id != me_.id:
            auth.end_sessions(db, user.id)  # new access applies at their next sign-in
    return _member(user)


@router.post("/users/{user_id}/password", status_code=204)
def reset_password(user_id: str, body: PasswordReset, _: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(UserRow, user_id)
    if user is None:
        raise HTTPException(404, "User not found.")
    auth.check_password_rules(body.password, user.email)
    user.password_hash, user.failed_logins, user.locked_until = auth.hash_password(body.password), 0, None
    db.commit()
    auth.end_sessions(db, user.id)
    return Response(status_code=204)
