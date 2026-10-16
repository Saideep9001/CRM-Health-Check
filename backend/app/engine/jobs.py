"""Database-backed job queue for health checks.

A health check is queued as an `assessment` row with status "queued". Workers
claim one at a time with an atomic UPDATE (plus SELECT … FOR UPDATE SKIP LOCKED on
PostgreSQL), so any number of workers can run side by side without picking the
same check. While a check runs, its worker writes a heartbeat; checks whose worker
stops checking in (crash, restart, deploy) are put back in the queue and retried,
up to `job_max_attempts`, then marked failed.
"""
import logging
import os
import socket
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import SessionLocal
from ..models import AssessmentRow
from . import scheduler

log = logging.getLogger("aquarient.jobs")

HEARTBEAT_SECONDS = 15


def _now() -> datetime:
    return datetime.now(timezone.utc)


def worker_id(kind: str, n: int = 0) -> str:
    return f"{kind}-{socket.gethostname()}-{os.getpid()}-{n}"


def claim(db: Session, wid: str, assessment_id: str | None = None) -> str | None:
    """Mark one queued check (the oldest, or a specific one) as running for this worker. Returns its id."""
    if assessment_id is None:
        q = select(AssessmentRow.id).where(AssessmentRow.status == "queued").order_by(AssessmentRow.created_at).limit(1)
        if db.get_bind().dialect.name == "postgresql":
            q = q.with_for_update(skip_locked=True)
        assessment_id = db.scalar(q)
        if assessment_id is None:
            db.rollback()
            return None
    now = _now()
    res = db.execute(
        update(AssessmentRow)
        .where(AssessmentRow.id == assessment_id, AssessmentRow.status == "queued")
        .values(
            status="running",
            worker_id=wid,
            heartbeat_at=now,
            started_at=func.coalesce(AssessmentRow.started_at, now),
            attempts=AssessmentRow.attempts + 1,
            progress=0,
            current_step="Connecting to Salesforce",
        )
    )
    db.commit()
    return assessment_id if res.rowcount == 1 else None


def _requeue_or_fail(db: Session, rows: list[AssessmentRow], max_attempts: int, why: str) -> tuple[int, int]:
    requeued = failed = 0
    for row in rows:
        if (row.attempts or 0) < max_attempts:
            row.status, row.worker_id, row.heartbeat_at = "queued", None, None
            row.progress, row.current_step = 0, "Restarting (the previous run was interrupted)"
            requeued += 1
        else:
            row.status, row.worker_id, row.current_step, row.completed_at = "failed", None, None, _now()
            row.error_message = f"The check was interrupted {row.attempts} times ({why}). Please run it again."
            failed += 1
    db.commit()
    return requeued, failed


def recover_stale(db: Session, settings: Settings) -> tuple[int, int]:
    """Re-queue (or fail) running checks whose worker stopped sending heartbeats."""
    cutoff = _now() - timedelta(seconds=settings.worker_heartbeat_timeout_seconds)
    rows = list(db.scalars(
        select(AssessmentRow).where(
            AssessmentRow.status == "running",
            (AssessmentRow.heartbeat_at < cutoff) | AssessmentRow.heartbeat_at.is_(None),
        )
    ).all())
    result = _requeue_or_fail(db, rows, settings.job_max_attempts, "its worker stopped responding")
    if rows:
        log.warning("Recovered %d stalled check(s): %d re-queued, %d failed", len(rows), *result)
    return result


def recover_own_host(db: Session, settings: Settings, kind: str) -> tuple[int, int]:
    """On start-up of an embedded worker, earlier runs on this machine can't still be alive: recover them now."""
    prefix = f"{kind}-{socket.gethostname()}-"
    rows = list(db.scalars(
        select(AssessmentRow).where(AssessmentRow.status == "running", AssessmentRow.worker_id.like(f"{prefix}%"))
    ).all())
    rows = [r for r in rows if not (r.worker_id or "").startswith(f"{prefix}{os.getpid()}-")]
    return _requeue_or_fail(db, rows, settings.job_max_attempts, "the server restarted")


class _Heartbeat(threading.Thread):
    """Updates `heartbeat_at` every few seconds while a check runs."""

    def __init__(self, assessment_id: str, wid: str):
        super().__init__(daemon=True, name=f"heartbeat-{assessment_id[:8]}")
        self.assessment_id, self.wid = assessment_id, wid
        self.done = threading.Event()

    def run(self) -> None:
        while not self.done.wait(HEARTBEAT_SECONDS):
            try:
                with SessionLocal() as db:
                    db.execute(
                        update(AssessmentRow)
                        .where(AssessmentRow.id == self.assessment_id, AssessmentRow.worker_id == self.wid)
                        .values(heartbeat_at=_now())
                    )
                    db.commit()
            except Exception:  # noqa: BLE001 — a missed heartbeat is retried on the next tick
                log.exception("Heartbeat failed for %s", self.assessment_id)


def run_claimed(assessment_id: str, wid: str, transport: httpx.BaseTransport | None = None) -> None:
    from .runner import execute  # local import: runner imports models/db too

    beat = _Heartbeat(assessment_id, wid)
    beat.start()
    try:
        execute(assessment_id, transport)
    finally:
        beat.done.set()


def run_now(assessment_id: str, transport: httpx.BaseTransport | None = None) -> None:
    """Inline mode (tests): claim this specific check and run it in the current thread."""
    wid = worker_id("inline")
    with SessionLocal() as db:
        if claim(db, wid, assessment_id) is None:
            return
    run_claimed(assessment_id, wid, transport)


def work_once(wid: str, settings: Settings, transport: httpx.BaseTransport | None = None) -> bool:
    """Recover stalled checks, then run the next queued one. Returns True if a check ran."""
    with SessionLocal() as db:
        recover_stale(db, settings)
        if settings.scheduler_enabled:
            try:
                scheduler.enqueue_due(db)
            except Exception:  # noqa: BLE001 — a scheduling problem must not stop the worker
                log.exception("Couldn't queue scheduled checks")
                db.rollback()
        assessment_id = claim(db, wid)
    if assessment_id is None:
        return False
    log.info("Worker %s running health check %s", wid, assessment_id)
    run_claimed(assessment_id, wid, transport)
    return True


def work_forever(wid: str, stop: threading.Event, transport_factory: Callable[[], httpx.BaseTransport | None] = lambda: None) -> None:
    settings = get_settings()
    log.info("Worker %s started", wid)
    while not stop.is_set():
        try:
            if work_once(wid, settings, transport_factory()):
                continue  # look for more work straight away
        except Exception:  # noqa: BLE001 — keep the worker alive; the check itself records its own failure
            log.exception("Worker %s hit an error", wid)
        stop.wait(settings.worker_poll_seconds)
    log.info("Worker %s stopped", wid)


def start_threads(kind: str, stop: threading.Event, transport_factory: Callable[[], httpx.BaseTransport | None] = lambda: None,
                  recover_host: bool = False) -> list[threading.Thread]:
    """Start worker threads. `recover_host` is only safe when this is the only worker process on the machine."""
    settings = get_settings()
    if recover_host:
        with SessionLocal() as db:
            requeued, failed = recover_own_host(db, settings, kind)
            if requeued or failed:
                log.warning("Picked up %d check(s) interrupted by a restart (%d re-queued, %d failed)", requeued + failed, requeued, failed)
    threads = []
    for n in range(max(1, settings.worker_threads)):
        t = threading.Thread(target=work_forever, args=(worker_id(kind, n), stop, transport_factory), daemon=True, name=f"{kind}-worker-{n}")
        t.start()
        threads.append(t)
    return threads
