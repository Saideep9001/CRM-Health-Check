"""Admin Panel (admins only) and access requests (anyone signed in can ask; admins approve or reject)."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, auth
from ..auth import Principal, require_admin, require_platform_admin, require_user
from ..db import get_db
from ..models import AccessRequestRow, AssessmentRow, AuditEventRow, CompanyRow, SessionRow, UserRow
from ..salesforce import service
from ..schemas import ApiModel

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
requests_router = APIRouter(prefix="/access-requests", tags=["access requests"])

REQUESTABLE_ROLES = ("consultant", "viewer")  # admin is only ever given by another admin, never requested


def _utc(dt):
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AdminOverview(ApiModel):
    users: int
    admins: int
    consultants: int
    viewers: int
    deactivated: int
    locked: int
    never_signed_in: int
    must_change_password: int
    pending_requests: int
    orgs_connected: int
    active_sessions: int


class AccessRequest(ApiModel):
    id: str
    user_id: str
    user_name: str
    user_email: str
    user_role: str
    kind: str
    requested_role: str | None = None
    org_note: str | None = None
    message: str | None = None
    status: str
    decided_by: str | None = None
    decision_note: str | None = None
    created_at: datetime | None = None
    decided_at: datetime | None = None


class AccessRequestCreate(ApiModel):
    kind: str = Field(pattern="^(org|role)$")
    requested_role: str | None = None
    org_note: str | None = Field(None, max_length=200)
    message: str | None = Field(None, max_length=500)


class ApproveBody(ApiModel):
    org_ids: list[str] = Field(default_factory=list, max_length=500)
    all_orgs: bool = False
    role: str | None = None
    note: str | None = Field(None, max_length=500)


class RejectBody(ApiModel):
    note: str | None = Field(None, max_length=500)


class AuditEvent(ApiModel):
    id: str
    at: datetime | None = None
    actor: str
    action: str
    target: str | None = None
    detail: str | None = None


def _request(r: AccessRequestRow, u: UserRow | None) -> AccessRequest:
    return AccessRequest(
        id=r.id, user_id=r.user_id, user_name=u.name if u else "(removed)", user_email=u.email if u else "", user_role=u.role if u else "",
        kind=r.kind, requested_role=r.requested_role, org_note=r.org_note, message=r.message, status=r.status, decided_by=r.decided_by,
        decision_note=r.decision_note, created_at=_utc(r.created_at), decided_at=_utc(r.decided_at),
    )


def _company_users(db: Session, me_: Principal) -> list[UserRow]:
    q = select(UserRow)
    if not me_.platform_admin:
        q = q.where(UserRow.company_id == me_.company_id)
    return list(db.scalars(q))


def _pending(db: Session, me_: Principal) -> int:
    ids = {u.id for u in _company_users(db, me_)}
    rows = db.scalars(select(AccessRequestRow.user_id).where(AccessRequestRow.status == "pending"))
    return sum(1 for uid in rows if uid in ids)


# ---------------------------------------------------------------- admin panel

@router.get("/overview", response_model=AdminOverview)
def overview(me_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    users = _company_users(db, me_)
    now = _now()
    active = [u for u in users if u.is_active]
    return AdminOverview(
        users=len(users),
        admins=sum(u.role == "admin" for u in active),
        consultants=sum(u.role == "consultant" for u in active),
        viewers=sum(u.role == "viewer" for u in active),
        deactivated=len(users) - len(active),
        locked=sum(bool(_utc(u.locked_until) and _utc(u.locked_until) > now) for u in users),
        never_signed_in=sum(u.last_login_at is None for u in active),
        must_change_password=sum(bool(u.must_change_password) for u in active),
        pending_requests=_pending(db, me_),
        orgs_connected=sum(1 for r in service.all_rows(db) if r.org_id and me_.sees(r.org_id)),
        active_sessions=int(db.scalar(select(func.count()).select_from(SessionRow).where(
            SessionRow.expires_at > now, SessionRow.user_id.in_({u.id for u in users} or {""}))) or 0),
    )


@router.get("/requests", response_model=list[AccessRequest])
def list_requests(status: str | None = Query(None, pattern="^(pending|approved|rejected|cancelled)$"),
                  me_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(AccessRequestRow).order_by(AccessRequestRow.created_at.desc()).limit(200)
    if status:
        q = q.where(AccessRequestRow.status == status)
    if not me_.platform_admin:
        q = q.where(AccessRequestRow.user_id.in_(select(UserRow.id).where(UserRow.company_id == me_.company_id)))
    rows = list(db.scalars(q))
    users = {u.id: u for u in db.scalars(select(UserRow).where(UserRow.id.in_({r.user_id for r in rows})))} if rows else {}
    return [_request(r, users.get(r.user_id)) for r in rows]


def _open_request(db: Session, request_id: str, me_: Principal) -> tuple[AccessRequestRow, UserRow]:
    r = db.get(AccessRequestRow, request_id)
    owner = db.get(UserRow, r.user_id) if r else None
    if r is None or (owner is not None and not me_.sees_company(owner.company_id)):
        raise HTTPException(404, "Request not found.")
    if r.status != "pending":
        raise HTTPException(409, f"This request was already {r.status}.")
    u = db.get(UserRow, r.user_id)
    if u is None:
        raise HTTPException(409, "That person no longer has an account.")
    return r, u


@router.post("/requests/{request_id}/approve", response_model=AccessRequest)
def approve(request_id: str, body: ApproveBody, me_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    r, u = _open_request(db, request_id, me_)
    if r.kind == "org":
        known = {c.org_id for c in service.all_rows(db) if c.org_id and auth.company_of(c.org_id) == (u.company_id or auth.DEFAULT_COMPANY)}
        wanted = set(body.org_ids)
        if not body.all_orgs and not wanted:
            raise HTTPException(422, "Choose which client orgs to give them.")
        if wanted - known:
            raise HTTPException(422, "One of those orgs isn’t connected.")
        if body.all_orgs:
            u.all_orgs = True
        u.org_ids = sorted(set(u.org_ids or []) | wanted)
        detail = "Access to every org" if body.all_orgs else f"Access to {len(wanted)} more org(s)"
    else:
        role = body.role or r.requested_role
        if role not in auth.ROLES:
            raise HTTPException(422, "Choose a role.")
        before, u.role = u.role, role
        if role == "admin":
            u.all_orgs = True
        detail = f"Role {before} → {role}"
    r.status, r.decided_by, r.decided_at, r.decision_note = "approved", audit.who(me_), _now(), (body.note or "").strip() or None
    audit.record(db, audit.who(me_), "request.approved", audit.who(u), detail)
    db.commit()
    return _request(r, u)


@router.post("/requests/{request_id}/reject", response_model=AccessRequest)
def reject(request_id: str, body: RejectBody, me_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    r, u = _open_request(db, request_id, me_)
    r.status, r.decided_by, r.decided_at, r.decision_note = "rejected", audit.who(me_), _now(), (body.note or "").strip() or None
    audit.record(db, audit.who(me_), "request.rejected", audit.who(u), "Org access" if r.kind == "org" else f"Role {r.requested_role}")
    db.commit()
    return _request(r, u)


@router.get("/activity", response_model=list[AuditEvent])
def activity(limit: int = Query(100, ge=1, le=500), me_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(AuditEventRow).order_by(AuditEventRow.at.desc()).limit(limit)
    if not me_.platform_admin:
        q = q.where(AuditEventRow.company_id == me_.company_id)
    rows = db.scalars(q)
    return [AuditEvent(id=e.id, at=_utc(e.at), actor=e.actor, action=e.action, target=e.target, detail=e.detail) for e in rows]


# ---------------------------------------------------------------- companies (platform admins)

class Company(ApiModel):
    id: str
    name: str
    users: int
    admins: int
    orgs: int
    created_at: datetime | None = None


class CompanyCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    admin_name: str = Field(min_length=1, max_length=120)
    admin_email: str = Field(max_length=254)
    admin_password: str = Field(max_length=200)  # temporary: they choose their own at first sign-in


def _company(c: CompanyRow, db: Session) -> Company:
    people = [u for u in db.scalars(select(UserRow).where(UserRow.company_id == c.id)) if u.is_active]
    orgs = {r.org_id for r in service.all_rows(db) if r.org_id and auth.company_of(r.org_id) == c.id}
    orgs |= {o for o in db.scalars(select(AssessmentRow.org_id).distinct()) if o and auth.company_of(o) == c.id}
    created = c.created_at if c.created_at is None or c.created_at.tzinfo else c.created_at.replace(tzinfo=timezone.utc)
    return Company(id=c.id, name=c.name, users=len(people), admins=sum(u.role == "admin" for u in people), orgs=len(orgs), created_at=created)


@router.get("/companies", response_model=list[Company])
def companies(_: Principal = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return [_company(c, db) for c in db.scalars(select(CompanyRow).order_by(CompanyRow.name))]


@router.post("/companies", response_model=Company, status_code=201)
def create_company(body: CompanyCreate, me_: Principal = Depends(require_platform_admin), db: Session = Depends(get_db)):
    """A new company and its first admin, who then adds their own people and connects their own orgs."""
    import re

    email = (body.admin_email or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(422, "Enter a valid email address for the company admin.")
    if db.scalars(select(UserRow).where(UserRow.email == email)).first():
        raise HTTPException(409, "Someone with that email already has an account.")
    if db.scalars(select(CompanyRow).where(func.lower(CompanyRow.name) == body.name.strip().lower())).first():
        raise HTTPException(409, "A company with that name already exists.")
    auth.check_password_rules(body.admin_password, email)
    company = CompanyRow(id=uuid.uuid4().hex[:8], name=body.name.strip())
    admin = UserRow(id=str(uuid.uuid4()), email=email, name=body.admin_name.strip(), password_hash=auth.hash_password(body.admin_password),
                    role="admin", all_orgs=True, is_active=True, must_change_password=True, company_id=company.id)
    db.add_all([company, admin])
    audit.record(db, audit.who(me_), "company.created", company.name, f"Admin: {admin.name} <{email}>", company=company.id)
    db.commit()
    return _company(company, db)


# ---------------------------------------------------------------- asking for access (anyone signed in)

@requests_router.get("/mine", response_model=list[AccessRequest])
def my_requests(user: Principal = Depends(require_user), db: Session = Depends(get_db)):
    row = db.get(UserRow, user.id)
    q = select(AccessRequestRow).where(AccessRequestRow.user_id == user.id).order_by(AccessRequestRow.created_at.desc()).limit(20)
    return [_request(r, row) for r in db.scalars(q)]


@requests_router.post("", response_model=AccessRequest, status_code=201)
def create_request(body: AccessRequestCreate, user: Principal = Depends(require_user), db: Session = Depends(get_db)):
    row = db.get(UserRow, user.id)
    if row is None or user.is_admin:
        raise HTTPException(409, "Admins already have full access.")
    if body.kind == "role":
        if body.requested_role not in REQUESTABLE_ROLES:
            raise HTTPException(422, "You can ask to be a consultant or a viewer. Admin access is only given by an admin.")
        if body.requested_role == row.role:
            raise HTTPException(422, "You already have that role.")
    elif not (body.org_note or "").strip():
        raise HTTPException(422, "Tell the admins which client org you need.")
    open_one = db.scalars(select(AccessRequestRow).where(AccessRequestRow.user_id == user.id, AccessRequestRow.kind == body.kind,
                                                         AccessRequestRow.status == "pending")).first()
    if open_one:
        raise HTTPException(409, "You already have a request waiting for an admin.")
    r = AccessRequestRow(id=str(uuid.uuid4()), user_id=user.id, kind=body.kind, status="pending",
                         requested_role=body.requested_role if body.kind == "role" else None,
                         org_note=(body.org_note or "").strip() or None, message=(body.message or "").strip() or None)
    db.add(r)
    audit.record(db, audit.who(user), "request.created", None, "Org access: " + (r.org_note or "") if r.kind == "org" else f"Role {r.requested_role}")
    db.commit()
    return _request(r, row)


@requests_router.delete("/{request_id}", status_code=204)
def cancel_request(request_id: str, user: Principal = Depends(require_user), db: Session = Depends(get_db)):
    r = db.get(AccessRequestRow, request_id)
    if r is None or r.user_id != user.id:
        raise HTTPException(404, "Request not found.")
    if r.status == "pending":
        r.status, r.decided_at = "cancelled", _now()
        db.commit()
    return Response(status_code=204)
