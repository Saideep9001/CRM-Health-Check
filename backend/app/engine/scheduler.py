"""Scheduled health checks: queue a check for each org whose schedule is due.

Workers call `enqueue_due` on every poll. Each schedule is claimed with a conditional UPDATE on
next_run_at, so two workers can never queue the same scheduled run twice.
"""
import calendar
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..alerts import SCHEDULER, notify
from ..models import AssessmentRow, ScanScheduleRow
from ..salesforce import service

log = logging.getLogger("aquarient.scheduler")
ACTIVE = ("queued", "running")
FREQUENCIES = ("daily", "weekly", "monthly")


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def advance(when: datetime, frequency: str) -> datetime:
    if frequency == "daily":
        return when + timedelta(days=1)
    if frequency == "weekly":
        return when + timedelta(weeks=1)
    month = when.month % 12 + 1
    year = when.year + (1 if when.month == 12 else 0)
    return when.replace(year=year, month=month, day=min(when.day, calendar.monthrange(year, month)[1]))


def next_after(now: datetime, start: datetime, frequency: str) -> datetime:
    """The first run time after `now`, stepping from `start` (skips runs missed while the server was off)."""
    t = _utc(start)
    while t <= now:
        t = advance(t, frequency)
    return t


def all_areas() -> list[str]:
    from .runner import EXECUTABLE_AREA_IDS

    return list(EXECUTABLE_AREA_IDS)


def category_of(area_ids: list[str]) -> list[str]:
    from .runner import AREAS

    return sorted({AREAS[a][0] for a in area_ids if a in AREAS})


def enqueue_due(db: Session, now: datetime | None = None) -> list[str]:
    """Queue checks for due schedules. Returns the new check ids."""
    now = now or datetime.now(timezone.utc)
    due = db.scalars(select(ScanScheduleRow).where(ScanScheduleRow.enabled.is_(True), ScanScheduleRow.next_run_at <= now)).all()
    queued: list[str] = []
    for s in due:
        old = s.next_run_at
        claimed = db.execute(
            update(ScanScheduleRow).where(ScanScheduleRow.id == s.id, ScanScheduleRow.next_run_at == old)
            .values(next_run_at=next_after(now, old, s.frequency), last_run_at=now)
        ).rowcount
        db.commit()
        if claimed != 1:
            continue  # another worker took it
        conn = service.row_for_org(db, s.org_id)
        if conn is None or conn.status == "expired":
            notify(db, "Scheduled check skipped", f"{(conn.organization_name if conn else None) or 'An org'}’s Salesforce connection has expired or was removed. "
                   "Reconnect it so scheduled checks can run.", kind="alert", org_id=s.org_id, link="/connection")
            continue
        busy = db.scalar(select(func.count()).select_from(AssessmentRow).where(AssessmentRow.org_id == s.org_id, AssessmentRow.status.in_(ACTIVE)))
        if busy:
            continue
        areas = [a for a in (s.area_ids or all_areas()) if a in all_areas()] or all_areas()
        row = AssessmentRow(
            id=str(uuid.uuid4()),
            name=f"Scheduled {s.frequency} check",
            connection_id=conn.org_id or str(conn.id),
            organization_name=conn.organization_name or "",
            org_id=conn.org_id or "",
            status="queued",
            scope={"categoryIds": category_of(areas), "areaIds": areas, "staleLeadDays": 30, "stuckOpportunityDays": 60},
            created_by=SCHEDULER,
            progress=0,
            current_step="Waiting to start",
        )
        db.add(row)
        s.last_assessment_id = row.id
        db.commit()
        queued.append(row.id)
        log.info("Queued scheduled check %s for org %s", row.id, s.org_id)
    return queued
