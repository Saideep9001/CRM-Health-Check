"""Consultant features: client portfolio, scheduled scans and alerts, proposals (SOW), benchmarks, fix plans (built-in playbooks)."""
import math
import re
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import playbooks
from ..alerts import email_configured, send_email
from ..auth import Principal, ensure_org, require_admin, require_editor, require_user
from ..config import Settings
from ..db import get_db
from ..deps import http_dep, settings_dep
from ..engine.combine import combined_view
from ..engine.scheduler import FREQUENCIES, advance, all_areas
from ..models import AssessmentRow, FindingRow, NotificationRow, ScanScheduleRow
from ..salesforce import service
from ..schemas import (
    AppNotification, BenchmarkLine, Benchmarks, FixPlan, MarkReadRequest, PortfolioCategoryScore, PortfolioOrg, PortfolioProblem, Proposal,
    ProposalLine, ProposalPhase,
    ScanSchedule, ScanScheduleUpdate,
)

router = APIRouter(tags=["consultant"])
OPEN = ("open", "in-review")
MIN_PEERS = 3


def _utc(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def _latest(db: Session, org_id: str, n: int = 1) -> list[AssessmentRow]:
    return list(db.scalars(
        select(AssessmentRow).where(AssessmentRow.org_id == org_id, AssessmentRow.status == "completed")
        .order_by(AssessmentRow.completed_at.desc()).limit(n)
    ))


# ---------------------------------------------------------------- portfolio

@router.get("/portfolio", response_model=list[PortfolioOrg])
def portfolio(db: Session = Depends(get_db)):
    """Every client org: saved connections plus orgs that only appear in past checks."""
    user = require_user()
    conns = {r.org_id: r for r in service.all_rows(db) if r.org_id and user.sees(r.org_id)}
    names = {r.org_id: r.organization_name for r in db.scalars(select(AssessmentRow).where(AssessmentRow.org_id != "")) if r.org_id and user.sees(r.org_id)}
    active = service.get_row(db)
    schedules = {s.org_id: s for s in db.scalars(select(ScanScheduleRow))}
    out = []
    for org_id in sorted(set(conns) | set(names), key=lambda o: ((conns[o].organization_name if o in conns else names.get(o)) or "").lower()):
        conn = conns.get(org_id)
        recent = _latest(db, org_id, 6)
        latest = recent[0] if recent else None
        critical, high, value, open_n, cats, top = 0, 0, 0.0, 0, [], []
        if latest:
            summary, found = combined_view(db, latest)
            live = [f for f in found if f.status in OPEN]
            open_n = len(live)
            critical = sum(1 for f in live if f.severity == "critical")
            high = sum(1 for f in live if f.severity == "high")
            cats = [PortfolioCategoryScore(category_id=c["categoryId"], score=c.get("score")) for c in summary.get("categories", [])]
            rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            top = [PortfolioProblem(finding_id=f.id, assessment_id=f.assessment_id, name=f.name, severity=f.severity,
                                    affected_records=f.affected_records, value_at_risk=f.value_at_risk)
                   for f in sorted(live, key=lambda f: (rank.get(f.severity, 4), -(f.value_at_risk or 0), -f.affected_records))[:3]]
            # The same deals can appear in several problems, so show the biggest single risk rather than a sum.
            value = max((f.value_at_risk or 0 for f in live), default=0)
        running = db.scalars(select(AssessmentRow).where(AssessmentRow.org_id == org_id, AssessmentRow.status.in_(("queued", "running"))).limit(1)).first()
        s = schedules.get(org_id)
        out.append(PortfolioOrg(
            org_id=org_id,
            organization_name=(conn.organization_name if conn else None) or names.get(org_id) or org_id,
            edition=conn.edition if conn else None,
            environment=conn.environment if conn else None,
            connection_status=conn.status if conn else "disconnected",
            active=bool(conn and active is not None and conn.id == active.id),
            instance_url=conn.instance_url if conn else None,
            latest_assessment_id=latest.id if latest else None,
            score=latest.overall_score if latest else None,
            previous_score=recent[1].overall_score if len(recent) > 1 else None,
            last_checked_at=_utc(latest.completed_at) if latest else None,
            trend=[r.overall_score for r in reversed(recent) if r.overall_score is not None],
            open_problems=open_n,
            critical_problems=critical,
            value_at_risk=value or None,
            running=running is not None,
            schedule=_schedule(s, conn) if s else None,
            high_problems=high,
            category_scores=cats,
            top_problems=top,
        ))
    return out


@router.post("/salesforce/connections/{org_id}/activate", response_model=PortfolioOrg | None)
def activate(org_id: str, db: Session = Depends(get_db)):
    """Make a saved org your active one (data explorer, new checks and the dashboard use it)."""
    ensure_org(org_id, "That org isn’t connected. Connect it first.")
    try:
        service.activate(db, org_id)
    except service.NotConnected:
        raise HTTPException(404, "That org isn’t connected. Connect it first.")
    from ..salesforce import explorer

    from .. import auth

    db.expire_all()
    user = auth.current()
    if user is not None and user.id != "local-user":
        from ..models import UserRow

        me = db.get(UserRow, user.id)
        auth._current.set(auth.principal(me, user.session_id))  # this request now sees the new active org
    return next((o for o in portfolio(db) if o.org_id == org_id), None)


@router.delete("/salesforce/connections/{org_id}", status_code=204)
def remove(org_id: str, _: Principal = Depends(require_admin), db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep)):
    """Disconnect a saved org (its past checks are kept)."""
    if service.row_for_org(db, org_id) is None:
        raise HTTPException(404, "That org isn’t connected.")
    service.disconnect(db, http, org_id)
    s = db.scalars(select(ScanScheduleRow).where(ScanScheduleRow.org_id == org_id)).first()
    if s:
        s.enabled = False
        db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- schedules

def _schedule(s: ScanScheduleRow, conn=None) -> ScanSchedule:
    return ScanSchedule(
        org_id=s.org_id, frequency=s.frequency, enabled=s.enabled, area_ids=s.area_ids, next_run_at=_utc(s.next_run_at),
        last_run_at=_utc(s.last_run_at), last_assessment_id=s.last_assessment_id, alert_email=s.alert_email,
        score_drop=s.score_drop, alert_new_critical=s.alert_new_critical,
        organization_name=conn.organization_name if conn else None,
    )


@router.get("/schedules", response_model=list[ScanSchedule])
def schedules(db: Session = Depends(get_db)):
    user = require_user()
    return [_schedule(s, service.row_for_org(db, s.org_id)) for s in db.scalars(select(ScanScheduleRow)) if user.sees(s.org_id)]


@router.put("/schedules/{org_id}", response_model=ScanSchedule)
def put_schedule(org_id: str, body: ScanScheduleUpdate, _: Principal = Depends(require_editor), db: Session = Depends(get_db)):
    ensure_org(org_id, "Connect this org before scheduling checks for it.")
    conn = service.row_for_org(db, org_id)
    if conn is None:
        raise HTTPException(404, "Connect this org before scheduling checks for it.")
    if body.frequency not in FREQUENCIES:
        raise HTTPException(422, "Choose daily, weekly or monthly.")
    areas = [a for a in (body.area_ids or []) if a in all_areas()] or None
    email = (body.alert_email or "").strip() or None
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "That alert email address doesn’t look right.")
    s = db.scalars(select(ScanScheduleRow).where(ScanScheduleRow.org_id == org_id)).first()
    now = datetime.now(timezone.utc)
    first = _utc(body.next_run_at) if body.next_run_at else advance(now, body.frequency)
    if s is None:
        s = ScanScheduleRow(id=str(uuid.uuid4()), org_id=org_id, frequency=body.frequency, next_run_at=first)
        db.add(s)
    elif s.frequency != body.frequency or body.next_run_at:
        s.next_run_at = first
    s.frequency, s.enabled, s.area_ids = body.frequency, body.enabled, areas
    s.alert_email, s.score_drop, s.alert_new_critical = email, body.score_drop, body.alert_new_critical
    db.commit()
    return _schedule(s, conn)


@router.delete("/schedules/{org_id}", status_code=204)
def delete_schedule(org_id: str, _: Principal = Depends(require_editor), db: Session = Depends(get_db)):
    ensure_org(org_id)
    s = db.scalars(select(ScanScheduleRow).where(ScanScheduleRow.org_id == org_id)).first()
    if s:
        db.delete(s)
        db.commit()
    return Response(status_code=204)


@router.post("/schedules/{org_id}/test-email", status_code=204)
def test_email(org_id: str, _: Principal = Depends(require_editor), db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    ensure_org(org_id)
    s = db.scalars(select(ScanScheduleRow).where(ScanScheduleRow.org_id == org_id)).first()
    if not s or not s.alert_email:
        raise HTTPException(422, "Add an alert email to this schedule first.")
    if not email_configured(settings):
        raise HTTPException(501, "Email isn’t set up on this server (SMTP_HOST and SMTP_FROM). Alerts still appear in the app.")
    send_email(settings, s.alert_email, "[Aquarient] Test alert", "This is a test alert from Aquarient CRM Health.\n")
    return Response(status_code=204)


# ---------------------------------------------------------------- notifications

@router.get("/me/notifications", response_model=list[AppNotification])
def notifications(db: Session = Depends(get_db)):
    user = require_user()
    rows = [r for r in db.scalars(select(NotificationRow).order_by(NotificationRow.created_at.desc()).limit(200)) if r.org_id is None or user.sees(r.org_id)][:50]
    return [AppNotification(id=r.id, title=r.title, body=r.body, created_at=_utc(r.created_at), read=r.read, link=r.link, kind=r.kind) for r in rows]


@router.post("/me/notifications/read", status_code=204)
def mark_read(body: MarkReadRequest | None = None, db: Session = Depends(get_db)):
    user = require_user()
    q = select(NotificationRow).where(NotificationRow.read.is_(False))
    if body and body.ids:
        q = q.where(NotificationRow.id.in_(body.ids[:200]))
    for r in db.scalars(q):
        if r.org_id is None or user.sees(r.org_id):
            r.read = True
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- proposal (SOW)

PHASES = [
    ("P1", "Phase 1 · Stabilise", "Critical problems that put revenue, security or the forecast at risk."),
    ("P2", "Phase 2 · Fix", "High-impact cleanup and process fixes."),
    ("P3", "Phase 3 · Optimise", "Usability, governance and longer-term improvements."),
]
HOURS_PER_WEEK = 30


@router.get("/assessments/{assessment_id}/proposal", response_model=Proposal)
def proposal(assessment_id: str, rate: float = Query(150, ge=0, le=5000), currency: str = Query("USD", max_length=3),
             db: Session = Depends(get_db)):
    """A statement of work drafted from the problems: phases, hours, cost and value at risk. Meant to be edited."""
    row = db.get(AssessmentRow, assessment_id)
    if row is None or row.status != "completed":
        raise HTTPException(404, "Health check not found or not finished.")
    ensure_org(row.org_id, "Health check not found or not finished.")
    results, found = combined_view(db, row)
    live = [f for f in found if f.status in OPEN]
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    live.sort(key=lambda f: (order.get(f.severity, 4), -(f.value_at_risk or 0), -f.affected_records))
    lines = []
    for f in live:
        phase = "P1" if f.severity == "critical" else "P2" if f.severity == "high" else "P3"
        lines.append(ProposalLine(
            finding_id=f.id, name=f.name, category_id=f.category_id, area_id=f.area_id, severity=f.severity, phase=phase,
            affected_records=f.affected_records, value_at_risk=f.value_at_risk, hours=playbooks.estimate_hours(f), action=f.recommended_action,
        ))
    phases = []
    for pid, name, text in PHASES:
        ls = [ln for ln in lines if ln.phase == pid]
        hours = round(sum(ln.hours for ln in ls), 1)
        phases.append(ProposalPhase(id=pid, name=name, description=text, hours=hours, cost=round(hours * rate, 2),
                                    value_at_risk=max((ln.value_at_risk or 0 for ln in ls), default=0) or None, problems=len(ls)))
    total_h = round(sum(p.hours for p in phases), 1)
    value = max((ln.value_at_risk or 0 for ln in lines), default=0)  # problems can overlap, so not summed
    crit = sum(1 for ln in lines if ln.severity == "critical")
    return Proposal(
        assessment_id=row.id, organization_name=row.organization_name, overall_score=results.get("overallScore"),
        rate=rate, currency=currency.upper(), hours=total_h, cost=round(total_h * rate, 2), weeks=math.ceil(total_h / HOURS_PER_WEEK) if total_h else 0,
        value_at_risk=value or None, phases=phases, lines=lines,
        summary=(f"Our health check of {row.organization_name or 'your Salesforce'} scored {results.get('overallScore')}/100 and found "
                            f"{len(lines)} open problems ({crit} critical)" + (f"; the largest single problem puts about {value:,.0f} {currency.upper()} of pipeline or revenue at risk" if value else "")
                            + f". We propose a three-phase plan of about {total_h:g} hours: stabilise the critical issues first, then fix high-impact "
                            "problems, then optimise usability and governance. Each phase ends with a re-check so progress is measured, not assumed."),
    )


# ---------------------------------------------------------------- benchmarks

def _percentile(value: float, peers: list[float]) -> int:
    below = sum(1 for p in peers if p < value) + 0.5 * sum(1 for p in peers if p == value)
    return round(100 * below / len(peers))


@router.get("/assessments/{assessment_id}/benchmarks", response_model=Benchmarks)
def benchmarks(assessment_id: str, db: Session = Depends(get_db)):
    """Compare a check with the latest check of every other org in this workspace (your portfolio)."""
    row = db.get(AssessmentRow, assessment_id)
    if row is None or row.status != "completed":
        raise HTTPException(404, "Health check not found or not finished.")
    ensure_org(row.org_id, "Health check not found or not finished.")
    mine, _ = combined_view(db, row)
    peers = []
    for org_id in {r.org_id for r in db.scalars(select(AssessmentRow).where(AssessmentRow.status == "completed", AssessmentRow.org_id != row.org_id)) if r.org_id}:
        latest = _latest(db, org_id)
        if latest:
            peers.append(combined_view(db, latest[0])[0])

    def line(key: str, label: str, value, peer_values: list) -> BenchmarkLine:
        vals = [v for v in peer_values if v is not None]
        ready = value is not None and len(vals) >= MIN_PEERS
        return BenchmarkLine(key=key, label=label, score=value, peers=len(vals),
                             median=sorted(vals)[len(vals) // 2] if vals else None,
                             percentile=_percentile(value, vals) if ready else None)

    lines = [line("overall", "Overall", mine.get("overallScore"), [p.get("overallScore") for p in peers])]
    for c in mine.get("categories", []):
        lines.append(line(c["categoryId"], c["categoryId"], c.get("score"),
                          [next((x.get("score") for x in p.get("categories", []) if x["categoryId"] == c["categoryId"]), None) for p in peers]))
    return Benchmarks(assessment_id=row.id, peers=len(peers), min_peers=MIN_PEERS, ready=len(peers) >= MIN_PEERS, lines=lines)


# ---------------------------------------------------------------- fix plan (built-in playbooks)

@router.post("/findings/{finding_id}/fix-plan", response_model=FixPlan)
def fix_plan(finding_id: str, db: Session = Depends(get_db)):
    """Step-by-step plan from the built-in playbooks."""
    f = db.get(FindingRow, finding_id)
    check = db.get(AssessmentRow, f.assessment_id) if f else None
    if f is None or check is None:
        raise HTTPException(404, "Problem not found.")
    ensure_org(check.org_id, "Problem not found.")
    return FixPlan.model_validate(playbooks.playbook(f))

