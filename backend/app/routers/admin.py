"""Admin Panel (admins only) and access requests (anyone signed in can ask; admins approve or reject)."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, auth
from ..auth import Principal, require_admin, require_user
from ..db import get_db
from ..models import AccessRequestRow, AuditEventRow, SessionRow, UserRow
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


def _pending(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(AccessRequestRow).where(AccessRequestRow.status == "pending")) or 0)


# ---------------------------------------------------------------- admin panel

@router.get("/overview", response_model=AdminOverview)
def overview(db: Session = Depends(get_db)):
    users = list(db.scalars(select(UserRow)))
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
        pending_requests=_pending(db),
        orgs_connected=sum(1 for r in service.all_rows(db) if r.org_id),
        active_sessions=int(db.scalar(select(func.count()).select_from(SessionRow).where(SessionRow.expires_at > now)) or 0),
    )


@router.get("/requests", response_model=list[AccessRequest])
def list_requests(status: str | None = Query(None, pattern="^(pending|approved|rejected|cancelled)$"), db: Session = Depends(get_db)):
    q = select(AccessRequestRow).order_by(AccessRequestRow.created_at.desc()).limit(200)
    if status:
        q = q.where(AccessRequestRow.status == status)
    rows = list(db.scalars(q))
    users = {u.id: u for u in db.scalars(select(UserRow).where(UserRow.id.in_({r.user_id for r in rows})))} if rows else {}
    return [_request(r, users.get(r.user_id)) for r in rows]


def _open_request(db: Session, request_id: str) -> tuple[AccessRequestRow, UserRow]:
    r = db.get(AccessRequestRow, request_id)
    if r is None:
        raise HTTPException(404, "Request not found.")
    if r.status != "pending":
        raise HTTPException(409, f"This request was already {r.status}.")
    u = db.get(UserRow, r.user_id)
    if u is None:
        raise HTTPException(409, "That person no longer has an account.")
    return r, u


@router.post("/requests/{request_id}/approve", response_model=AccessRequest)
def approve(request_id: str, body: ApproveBody, me_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    r, u = _open_request(db, request_id)
    if r.kind == "org":
        known = {c.org_id for c in service.all_rows(db) if c.org_id}
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
    r, u = _open_request(db, request_id)
    r.status, r.decided_by, r.decided_at, r.decision_note = "rejected", audit.who(me_), _now(), (body.note or "").strip() or None
    audit.record(db, audit.who(me_), "request.rejected", audit.who(u), "Org access" if r.kind == "org" else f"Role {r.requested_role}")
    db.commit()
    return _request(r, u)


@router.get("/activity", response_model=list[AuditEvent])
def activity(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditEventRow).order_by(AuditEventRow.at.desc()).limit(limit))
    return [AuditEvent(id=e.id, at=_utc(e.at), actor=e.actor, action=e.action, target=e.target, detail=e.detail) for e in rows]


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
