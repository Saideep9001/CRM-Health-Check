"""Disconnecting an org: its Salesforce access is revoked and everything saved about it is deleted.

Nothing about an org outlives its connection: health checks, problems (with notes and fix status), schedules and alerts
are removed with it, and every person's org lists stop mentioning it. Results exist only while the org is connected.
"""
import httpx
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import audit
from .auth import Principal
from .models import AssessmentRow, FindingRow, NotificationRow, ScanScheduleRow, SalesforceConnectionRow, UserRow
from .salesforce import service

ACTIVE = ("queued", "running")


def saved_counts(db: Session, org_id: str) -> dict:
    """How much is saved about an org (shown before it's disconnected, since all of it is deleted)."""
    ids = select(AssessmentRow.id).where(AssessmentRow.org_id == org_id)
    return {
        "checks": int(db.scalar(select(func.count()).select_from(AssessmentRow).where(AssessmentRow.org_id == org_id)) or 0),
        "problems": int(db.scalar(select(func.count()).select_from(FindingRow).where(FindingRow.assessment_id.in_(ids))) or 0),
    }


def _forget(db: Session, org_ids: set[str]) -> None:
    """Delete everything saved about these orgs, and take them off every person's lists."""
    if not org_ids:
        return
    checks = select(AssessmentRow.id).where(AssessmentRow.org_id.in_(org_ids))
    db.execute(delete(FindingRow).where(FindingRow.assessment_id.in_(checks)))
    db.execute(delete(AssessmentRow).where(AssessmentRow.org_id.in_(org_ids)))
    db.execute(delete(NotificationRow).where(NotificationRow.org_id.in_(org_ids)))
    db.execute(delete(ScanScheduleRow).where(ScanScheduleRow.org_id.in_(org_ids)))
    for u in db.scalars(select(UserRow)):
        if u.active_org_id in org_ids:
            u.active_org_id = None
        if set(u.org_ids or []) & org_ids:
            u.org_ids = [o for o in u.org_ids if o not in org_ids]
        if set(u.hidden_org_ids or []) & org_ids:
            u.hidden_org_ids = [o for o in u.hidden_org_ids if o not in org_ids]


def disconnect_org(db: Session, http: httpx.Client, org_id: str, *, actor: Principal) -> dict:
    """Revoke and forget the org's tokens and permanently delete everything saved about it. Returns what was deleted."""
    row = service.row_for_org(db, org_id)
    name = (row.organization_name if row else None) or org_id
    if db.scalar(select(func.count()).select_from(AssessmentRow).where(AssessmentRow.org_id == org_id, AssessmentRow.status.in_(ACTIVE))):
        raise HTTPException(409, "A health check is running for this org. Stop it or let it finish, then disconnect.")
    counts = saved_counts(db, org_id)
    if row is not None:
        service.disconnect(db, http, org_id)
    _forget(db, {org_id})
    audit.record(db, audit.who(actor), "org.deleted", name,
                 f"Disconnected; deleted {counts['checks']:,} health checks and {counts['problems']:,} problems")
    db.commit()
    return counts


def purge_disconnected(db: Session) -> int:
    """Delete results left behind by orgs that are no longer connected (e.g. disconnected before results were always
    deleted). Run at start-up. Returns how many health checks were removed."""
    connected = {o for o in db.scalars(select(SalesforceConnectionRow.org_id)) if o}
    orphans = {o or "" for o in db.scalars(select(AssessmentRow.org_id).distinct())} - connected
    orphans |= {o for o in db.scalars(select(ScanScheduleRow.org_id)) if o not in connected}
    orphans |= {o for o in db.scalars(select(NotificationRow.org_id).distinct()) if o and o not in connected}
    if any(db.scalar(select(func.count()).select_from(AssessmentRow).where(AssessmentRow.org_id == o, AssessmentRow.status.in_(ACTIVE)))
           for o in orphans):
        orphans = {o for o in orphans if not db.scalar(select(func.count()).select_from(AssessmentRow).where(
            AssessmentRow.org_id == o, AssessmentRow.status.in_(ACTIVE)))}  # never pull a running check out from under its worker
    n = int(db.scalar(select(func.count()).select_from(AssessmentRow).where(AssessmentRow.org_id.in_(orphans))) or 0) if orphans else 0
    _forget(db, orphans)
    db.commit()
    return n
