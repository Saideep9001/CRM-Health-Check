"""Disconnecting an org: always forget its Salesforce access; optionally delete everything saved about it."""
import httpx
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import audit
from .auth import Principal
from .models import AssessmentRow, FindingRow, NotificationRow, ScanScheduleRow
from .salesforce import service

ACTIVE = ("queued", "running")


def saved_counts(db: Session, org_id: str) -> dict:
    """How much is saved about an org (shown before someone chooses to delete it)."""
    ids = select(AssessmentRow.id).where(AssessmentRow.org_id == org_id)
    return {
        "checks": int(db.scalar(select(func.count()).select_from(AssessmentRow).where(AssessmentRow.org_id == org_id)) or 0),
        "problems": int(db.scalar(select(func.count()).select_from(FindingRow).where(FindingRow.assessment_id.in_(ids))) or 0),
    }


def disconnect_org(db: Session, http: httpx.Client, org_id: str, *, delete_results: bool, actor: Principal) -> dict:
    """Revoke and forget the org's tokens. With `delete_results`, also permanently delete its health checks,
    problems (with notes and fix status), schedule and alerts. Returns what was deleted."""
    row = service.row_for_org(db, org_id)
    name = (row.organization_name if row else None) or org_id
    if delete_results and db.scalar(select(func.count()).select_from(AssessmentRow).where(AssessmentRow.org_id == org_id, AssessmentRow.status.in_(ACTIVE))):
        raise HTTPException(409, "A health check is running for this org. Cancel it or let it finish, then try again.")
    counts = saved_counts(db, org_id) if delete_results else {"checks": 0, "problems": 0}

    if row is not None:
        service.disconnect(db, http, org_id)
    schedule = db.scalars(select(ScanScheduleRow).where(ScanScheduleRow.org_id == org_id)).first()
    if delete_results:
        ids = select(AssessmentRow.id).where(AssessmentRow.org_id == org_id)
        db.execute(delete(FindingRow).where(FindingRow.assessment_id.in_(ids)))
        db.execute(delete(AssessmentRow).where(AssessmentRow.org_id == org_id))
        db.execute(delete(NotificationRow).where(NotificationRow.org_id == org_id))
        if schedule:
            db.delete(schedule)
        audit.record(db, audit.who(actor), "org.deleted", name,
                     f"Disconnected and deleted {counts['checks']:,} health checks and {counts['problems']:,} problems")
    else:
        if schedule:
            schedule.enabled = False  # nothing to run against until it's reconnected
        audit.record(db, audit.who(actor), "org.disconnected", name, "Saved results kept")
    db.commit()
    return counts
