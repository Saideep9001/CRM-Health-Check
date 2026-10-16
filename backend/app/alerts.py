"""Notifications and alerts after a health check finishes.

In-app notifications are always stored. Email is sent only when SMTP is configured (SMTP_HOST etc.) and the
org's schedule has an alert address — nothing is ever emailed otherwise.
"""
import logging
import smtplib
import threading
import uuid
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .models import AssessmentRow, FindingRow, NotificationRow, ScanScheduleRow, UserPrefsRow

log = logging.getLogger("aquarient.alerts")
SCHEDULER = "Scheduler"


def notify(db: Session, title: str, body: str, *, kind: str = "info", org_id: str | None = None, link: str | None = None) -> NotificationRow:
    row = NotificationRow(id=str(uuid.uuid4()), kind=kind, title=title[:255], body=body, org_id=org_id, link=link)
    db.add(row)
    db.commit()
    return row


def _prefs(db: Session) -> dict:
    row = db.get(UserPrefsRow, 1)
    return ((row.settings if row else None) or {}).get("notifications") or {}


def _previous(db: Session, row: AssessmentRow) -> AssessmentRow | None:
    return db.scalars(
        select(AssessmentRow)
        .where(AssessmentRow.status == "completed", AssessmentRow.org_id == row.org_id, AssessmentRow.id != row.id,
               AssessmentRow.completed_at <= row.completed_at)
        .order_by(AssessmentRow.completed_at.desc()).limit(1)
    ).first()


def after_run(db: Session, row: AssessmentRow, settings: Settings | None = None) -> list[NotificationRow]:
    """Compare a finished check with the org's previous one and raise alerts. Never raises."""
    try:
        return _after_run(db, row, settings or get_settings())
    except Exception:  # noqa: BLE001 — alerts must never break a finished check
        log.exception("Couldn't create alerts for %s", row.id)
        return []


def _after_run(db: Session, row: AssessmentRow, settings: Settings) -> list[NotificationRow]:
    if row.status != "completed":
        return []
    schedule = db.scalars(select(ScanScheduleRow).where(ScanScheduleRow.org_id == row.org_id)).first()
    prefs = _prefs(db)
    prev = _previous(db, row)
    org = row.organization_name or "your Salesforce"
    link = f"/results?assessment={row.id}"
    out: list[NotificationRow] = []
    alerts: list[str] = []

    drop_limit = schedule.score_drop if schedule else 5
    if prev is not None and prev.overall_score is not None and row.overall_score is not None:
        drop = prev.overall_score - row.overall_score
        if drop >= drop_limit:
            alerts.append(f"The health score fell from {prev.overall_score} to {row.overall_score} (−{drop}).")
    if prev is not None and (schedule.alert_new_critical if schedule else True) and prefs.get("criticalFindings", True):
        new_critical = db.scalars(select(FindingRow).where(
            FindingRow.assessment_id == row.id, FindingRow.severity == "critical", FindingRow.previous_affected.is_(None))).all()
        if new_critical:
            names = ", ".join(f.name for f in new_critical[:5]) + (" …" if len(new_critical) > 5 else "")
            alerts.append(f"{len(new_critical)} new critical problem{'s' if len(new_critical) != 1 else ''}: {names}.")
    if alerts:
        out.append(notify(db, f"Alert: {org}", " ".join(alerts), kind="alert", org_id=row.org_id, link=link))

    scheduled = row.created_by == SCHEDULER
    if scheduled or prefs.get("assessmentCompleted", True):
        trend = ""
        if prev is not None and prev.overall_score is not None and row.overall_score is not None:
            d = row.overall_score - prev.overall_score
            trend = f" ({'+' if d >= 0 else '−'}{abs(d)} since the last check)"
        what = "Scheduled check" if scheduled else "Health check"
        out.append(notify(db, f"{what} finished: {org}",
                          f"Health score {row.overall_score if row.overall_score is not None else '—'}{trend}, {row.findings_count or 0} problems.",
                          org_id=row.org_id, link=link))

    if schedule and schedule.alert_email and (alerts or scheduled):
        subject = f"[Aquarient] {'Alert' if alerts else 'Scheduled check'}: {org}"
        lines = alerts or [f"Health score {row.overall_score}, {row.findings_count or 0} problems."]
        url = f"{settings.frontend_origin.rstrip('/')}{link}"
        send_email(settings, schedule.alert_email, subject, "\n".join(lines) + f"\n\nOpen the results: {url}\n")
    return out


def email_configured(settings: Settings) -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def send_email(settings: Settings, to: str, subject: str, text: str, wait: bool = False) -> None:
    """Send a plain-text email in the background. Does nothing unless SMTP is configured."""
    if not email_configured(settings):
        return

    def go() -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
        msg.set_content(text)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
                if settings.smtp_starttls:
                    s.starttls()
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        except Exception:  # noqa: BLE001 — a mail problem must not affect the app
            log.exception("Couldn't send alert email to %s", to)

    if wait:
        go()
    else:
        threading.Thread(target=go, daemon=True, name="alert-email").start()
