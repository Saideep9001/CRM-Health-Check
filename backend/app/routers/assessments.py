"""Health checks (assessments) and their findings. See docs/API_CONTRACT.md → Assessments."""
import uuid
from datetime import datetime, timezone

import csv
import io
import re

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import Principal, ensure_org, require_editor, require_user
from ..config import Settings
from ..db import get_db
from ..deps import http_dep, settings_dep
from ..engine.combine import combined_view
from ..engine import jobs
from ..engine.runner import EXECUTABLE_AREA_IDS
from ..models import AssessmentRow, FindingRow
from ..salesforce import explorer, service
from ..salesforce.errors import SalesforceAuthExpired, SalesforceError
from ..schemas import (
    Assessment,
    AssessmentResults,
    AssessmentStatus,
    CreateAssessmentRequest,
    Finding,
    FindingRecordsPage,
    Paginated,
    UpdateFindingRequest,
)

router = APIRouter(tags=["assessments"])

VALID_AREAS = {f"area-{n}" for n in range(1, 22)}
ACTIVE = ("queued", "running")
SORTS = {
    "createdAt": AssessmentRow.created_at,
    "completedAt": AssessmentRow.completed_at,
    "name": AssessmentRow.name,
    "overallScore": AssessmentRow.overall_score,
}


def _utc(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def to_assessment(row: AssessmentRow) -> Assessment:
    return Assessment(
        id=row.id,
        name=row.name,
        connection_id=row.connection_id,
        organization_name=row.organization_name,
        org_id=row.org_id,
        status=row.status,  # type: ignore[arg-type]
        scope=row.scope,
        created_at=_utc(row.created_at),
        started_at=_utc(row.started_at),
        completed_at=_utc(row.completed_at),
        created_by=row.created_by,
        progress=row.progress,
        current_step=row.current_step,
        records_assessed=row.records_assessed,
        findings_count=row.findings_count,
        overall_score=row.overall_score,
        error_message=row.error_message,
    )


def to_finding(row: FindingRow) -> Finding:
    return Finding(
        id=row.id,
        assessment_id=row.assessment_id,
        name=row.name,
        category_id=row.category_id,
        area_id=row.area_id,
        severity=row.severity,  # type: ignore[arg-type]
        priority=row.priority,  # type: ignore[arg-type]
        affected_records=row.affected_records,
        business_impact=row.business_impact,
        recommended_action=row.recommended_action,
        status=row.status,  # type: ignore[arg-type]
        description=row.description,
        why_it_matters=row.why_it_matters,
        detected_at=_utc(row.detected_at),
        sample_records_url=row.sample_records_url,
        object_name=row.object_name,
        notes=row.notes,
        records_available=bool(row.records_object),
        value_at_risk=row.value_at_risk,
        fix_url=row.fix_url,
        previous_affected=row.previous_affected,
        change=_change(row),
    )


def _change(row: FindingRow) -> str:
    if row.previous_affected is None:
        return "new"
    if row.affected_records > row.previous_affected:
        return "worse"
    if row.affected_records < row.previous_affected:
        return "better"
    return "same"


def _get(db: Session, assessment_id: str) -> AssessmentRow:
    row = db.get(AssessmentRow, assessment_id)
    if row is None:
        raise HTTPException(404, "Health check not found.")
    ensure_org(row.org_id, "Health check not found.")
    return row


def _finding(db: Session, finding_id: str) -> tuple[FindingRow, AssessmentRow]:
    row = db.get(FindingRow, finding_id)
    check = db.get(AssessmentRow, row.assessment_id) if row else None
    if row is None or check is None:
        raise HTTPException(404, "Problem not found.")
    ensure_org(check.org_id, "Problem not found.")
    return row, check


def _page(items: list, total: int, page: int, page_size: int) -> Paginated:
    return Paginated(items=[i.model_dump(by_alias=True, mode="json") for i in items], total=total, page=page, page_size=page_size)


@router.get("/assessments", response_model=Paginated)
def list_assessments(
    status: AssessmentStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500, alias="pageSize"),
    sort: str = Query("-createdAt", max_length=40),
    all_orgs: bool = Query(False, alias="allOrgs", description="Include checks of every saved org, not just the active one"),
    db: Session = Depends(get_db),
):
    stmt = select(AssessmentRow)
    active = None if all_orgs else service.get_row(db)
    if active is not None and active.org_id:
        stmt = stmt.where(AssessmentRow.org_id == active.org_id)
    visible = require_user().allowed()
    if visible is not None:
        stmt = stmt.where(AssessmentRow.org_id.in_(visible or {""}))
    if status:
        stmt = stmt.where(AssessmentRow.status == status)
    col = SORTS.get(sort.lstrip("-"), AssessmentRow.created_at)
    stmt = stmt.order_by(col.desc().nulls_last() if sort.startswith("-") else col.asc().nulls_last(), AssessmentRow.created_at.desc())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return _page([to_assessment(r) for r in rows], total, page, page_size)


@router.post("/assessments", response_model=Assessment, status_code=201)
def create_assessment(
    body: CreateAssessmentRequest,
    background: BackgroundTasks,
    request: Request,
    user: Principal = Depends(require_editor),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
):
    conn = service.get_row(db)
    if conn is None or conn.status != "connected":
        raise HTTPException(409, "Salesforce isn’t connected. Connect it first, then run the health check.")
    if body.connection_id != service.to_schema(conn, settings).id:
        raise HTTPException(409, "That Salesforce connection has changed. Refresh the page and try again.")
    unknown = [a for a in body.scope.area_ids if a not in VALID_AREAS]
    if unknown:
        raise HTTPException(422, f"Unknown areas: {', '.join(unknown)}.")
    if not any(a in EXECUTABLE_AREA_IDS for a in body.scope.area_ids):
        raise HTTPException(422, "None of the selected areas can be checked automatically.")
    if db.scalar(select(func.count()).select_from(AssessmentRow).where(AssessmentRow.status.in_(ACTIVE), AssessmentRow.org_id == (conn.org_id or ""))):
        raise HTTPException(409, "A health check is already running for this Salesforce. Wait for it to finish or cancel it first.")

    row = AssessmentRow(
        id=str(uuid.uuid4()),
        name=body.name.strip(),
        connection_id=body.connection_id,
        organization_name=conn.organization_name or "",
        org_id=conn.org_id or "",
        status="queued",
        scope=body.scope.model_dump(by_alias=True),
        notes=(body.notes or "").strip() or None,
        created_by=user.name,
        progress=0,
        current_step="Waiting to start",
    )
    db.add(row)
    db.commit()
    if settings.job_mode == "inline":
        background.add_task(jobs.run_now, row.id, getattr(request.app.state, "http_transport", None))
    # Otherwise a worker (embedded or external) picks it up from the queue within a few seconds.
    return to_assessment(row)


@router.get("/assessments/{assessment_id}", response_model=Assessment)
def get_assessment(assessment_id: str, db: Session = Depends(get_db)):
    return to_assessment(_get(db, assessment_id))


@router.post("/assessments/{assessment_id}/cancel", response_model=Assessment)
def cancel_assessment(assessment_id: str, _: Principal = Depends(require_editor), db: Session = Depends(get_db)):
    row = _get(db, assessment_id)
    if row.status not in ACTIVE:
        raise HTTPException(409, "This health check has already finished.")
    # A worker running it notices at its next step and stops; a queued one is simply never picked up.
    row.status, row.completed_at, row.current_step = "cancelled", datetime.now(timezone.utc), None
    db.commit()
    return to_assessment(row)


@router.get("/assessments/{assessment_id}/results", response_model=AssessmentResults)
def get_results(assessment_id: str, db: Session = Depends(get_db)):
    row = _get(db, assessment_id)
    if row.status != "completed" or not row.results:
        raise HTTPException(404, "Results aren’t ready yet.")
    results, _ = combined_view(db, row)
    return AssessmentResults.model_validate(results)


@router.get("/assessments/{assessment_id}/findings", response_model=Paginated)
def list_findings(
    assessment_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000, alias="pageSize"),
    db: Session = Depends(get_db),
):
    row = _get(db, assessment_id)
    if row.status == "completed":
        # Includes problems from earlier checks for areas this check didn't cover.
        _, found = combined_view(db, row)
    else:
        found = list(db.scalars(select(FindingRow).where(FindingRow.assessment_id == assessment_id)).all())
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    # Most urgent first; within an urgency, the most money at risk, then the most records.
    found.sort(key=lambda f: (order.get(f.severity, 4), -(f.value_at_risk or 0), -f.affected_records))
    start = (page - 1) * page_size
    return _page([to_finding(r) for r in found[start : start + page_size]], len(found), page, page_size)


def _finding_with_records(db: Session, finding_id: str) -> tuple[FindingRow, str]:
    row, check = _finding(db, finding_id)
    if not row.records_object:
        raise HTTPException(404, "This problem isn’t about specific records.")
    return row, check.org_id


def _salesforce(db: Session, http: httpx.Client, settings: Settings, fn, org_id: str | None = None):
    try:
        sf = service.client_for(db, http, settings, org_id=org_id or None)  # the problem's own org, not the active one
    except service.NotConnected:
        raise HTTPException(409, "Salesforce isn’t connected. Connect it to see the records.")
    try:
        return fn(sf)
    except explorer.NotFound:
        raise HTTPException(404, "Those records can’t be read with the connected user.")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except SalesforceAuthExpired as exc:
        service.mark_expired(db, str(exc))
        raise HTTPException(409, "Your Salesforce connection has timed out. Please reconnect.")
    except SalesforceError as exc:
        raise HTTPException(424, f"Salesforce couldn’t return the records. {exc}")
    except httpx.HTTPError:
        raise HTTPException(424, "Couldn’t reach Salesforce. Please try again.")


@router.get("/findings/{finding_id}/records", response_model=FindingRecordsPage)
def finding_records(
    finding_id: str,
    cursor: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    """The records a problem is about, live from Salesforce (200 per page)."""
    row, org_id = _finding_with_records(db, finding_id)
    return _salesforce(db, http, settings, lambda sf: explorer.records_matching(sf, row.records_object, row.records_where, cursor), org_id)


CSV_LIMIT = 10_000


@router.get("/findings/{finding_id}/records.csv")
def finding_records_csv(
    finding_id: str,
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    """Download the affected records (up to 10,000) as a spreadsheet."""
    row, org_id = _finding_with_records(db, finding_id)

    def collect(sf):
        page = explorer.records_matching(sf, row.records_object, row.records_where, page_size=2000)
        rows = list(page["records"])
        while page["next_cursor"] and len(rows) < CSV_LIMIT:
            page = explorer.records_matching(sf, row.records_object, row.records_where, page["next_cursor"], page_size=2000)
            rows += page["records"]
        return page["columns"], rows[:CSV_LIMIT], page["record_url_prefix"]

    columns, rows, prefix = _salesforce(db, http, settings, collect, org_id)
    out = io.StringIO()
    out.write("\ufeff")  # so Excel opens accents correctly
    w = csv.writer(out)
    w.writerow([c["label"] for c in columns] + ["Salesforce link"])
    for r in rows:
        vals = r["values"]
        w.writerow([r["ref_names"].get(c["name"]) or ("" if vals.get(c["name"]) is None else vals.get(c["name"])) for c in columns]
                   + [f"{prefix}{r['id']}" if r.get("id") else ""])
    name = re.sub(r"[^A-Za-z0-9]+", "-", row.name).strip("-").lower() or "records"
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


@router.patch("/findings/{finding_id}", response_model=Finding)
def update_finding(finding_id: str, body: UpdateFindingRequest, _: Principal = Depends(require_editor), db: Session = Depends(get_db)):
    row, _check = _finding(db, finding_id)
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] is not None:
        row.status = data["status"]
    if "notes" in data:
        row.notes = (data["notes"] or "").strip() or None
    db.commit()
    return to_finding(row)
