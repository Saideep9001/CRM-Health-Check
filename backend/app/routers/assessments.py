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
from ..engine.core import in_list
from ..engine.runner import EXECUTABLE_AREA_IDS
from ..models import AssessmentRow, FindingRow
from ..salesforce import activity, assignment, explorer, finder, queues, service
from ..salesforce.errors import SalesforceAuthExpired, SalesforceError
from ..schemas import (
    FieldValues,
    QueueCount,
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


def _measure_links(db: Session, rows: list[FindingRow]) -> dict[str, str]:
    """For problems saved before they recorded their measure: the measure of the same check, same area, that
    selected exactly the same records (identical object and filter), else one with the same name."""
    need = [r for r in rows if not r.measure]
    if not need:
        return {}
    checks = {a.id: a for a in db.scalars(select(AssessmentRow).where(AssessmentRow.id.in_({r.assessment_id for r in need})))}
    links: dict[str, str] = {}
    for r in need:
        area = next((a for a in ((checks.get(r.assessment_id) and checks[r.assessment_id].results) or {}).get("areas", [])
                     if a.get("areaId") == r.area_id), None)
        indicators = (area or {}).get("indicators", [])
        exact = next((i["label"] for i in indicators for rec in (i.get("records") or [])
                      if r.records_object and rec.get("object") == r.records_object and rec.get("where") == r.records_where), None)
        named = next((i["label"] for i in indicators if i.get("label") == r.name), None)
        if exact or named:
            links[r.id] = exact or named
    return links


def to_finding(row: FindingRow, measure: str | None = None) -> Finding:
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
        measure=row.measure or measure,
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
    visible = require_user().org_condition(AssessmentRow.org_id)  # your company's orgs you may see
    if visible is not None:
        stmt = stmt.where(visible)
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
    shown = found[start : start + page_size]
    links = _measure_links(db, shown)
    return _page([to_finding(r, links.get(r.id)) for r in shown], len(found), page, page_size)


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
    filters: str | None = Query(None, max_length=12000, description='JSON list of {"field","op","value"} column filters'),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    """The records a problem is about, live from Salesforce (200 per page)."""
    row, org_id = _finding_with_records(db, finding_id)
    return _salesforce(db, http, settings, lambda sf: explorer.records_matching(
        sf, row.records_object, row.records_where, cursor, filters=_filters(filters)), org_id)


@router.get("/findings/{finding_id}/values", response_model=FieldValues)
def finding_values(
    finding_id: str,
    field: str = Query(..., max_length=120),
    filters: str | None = Query(None, max_length=12000),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    """The values of one column among a problem's records, for its filter drop-down."""
    row, org_id = _finding_with_records(db, finding_id)
    return _salesforce(db, http, settings, lambda sf: explorer.field_values(
        sf, row.records_object, field, None, _filters(filters), base_where=row.records_where), org_id)


def _filters(raw: str | None) -> list[dict]:
    try:
        return finder.parse_filters(raw)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


CSV_LIMIT = 10_000


@router.get("/findings/{finding_id}/records.csv")
def finding_records_csv(
    finding_id: str,
    filters: str | None = Query(None, max_length=12000),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    """Download the affected records (up to 10,000) as a spreadsheet — only those the column filters keep."""
    row, org_id = _finding_with_records(db, finding_id)
    return _records_csv(db, http, settings, org_id, row.records_object, row.records_where, row.name, filters=_filters(filters))


def _by_queue(rec: dict) -> bool:
    """Can this measure's records be narrowed to one Lead queue (Stuck Queue-Owned Leads, Inactive Lead Assignment Rules)?"""
    return rec.get("extra") == "days_in_queue" or bool(rec.get("by_queue"))


def _with_extra(sf, rec: dict, columns: list[dict], records: list[dict]) -> list[dict]:
    """A measure's column that isn't a Salesforce field, added to the listed records: Days in Queue (worked out live, so it's
    always current), or the reason saved by the check (Assignment Gap Reason, Potential Match)."""
    if rec.get("extra") == "days_in_queue":
        return queues.add_days_in_queue(sf, columns, records)
    if rec.get("extra") == "assignment_gap":
        return assignment.add_gap_reason(columns, records, rec.get("reasons") or {}, rec.get("reason"))
    if rec.get("extra") == "rule_match":
        return assignment.add_reason(columns, records, rec.get("reasons") or {}, rec.get("reason"), column=assignment.MATCH_COLUMN)
    return columns


def _records_csv(db: Session, http: httpx.Client, settings: Settings, org_id: str | None, obj: str, where: str | None, title: str,
                 columns: list[str] | None = None, order: str | None = None, filters: list[dict] | None = None,
                 notes: dict[str, dict[str, str]] | None = None, rec: dict | None = None, exact: bool = False) -> Response:
    def collect(sf):
        page = explorer.records_matching(sf, obj, where, page_size=2000, columns=columns, order=order, filters=filters, exact=exact)
        rows = list(page["records"])
        while page["next_cursor"] and len(rows) < CSV_LIMIT:
            page = explorer.records_matching(sf, obj, where, page["next_cursor"], page_size=2000, columns=columns, order=order, exact=exact)
            rows += page["records"]
        rows = rows[:CSV_LIMIT]
        cols = _with_extra(sf, rec or {}, page["columns"], rows)
        return cols, rows, page["record_url_prefix"]

    columns, rows, prefix = _salesforce(db, http, settings, collect, org_id)
    out = io.StringIO()
    out.write("\ufeff")  # so Excel opens accents correctly
    w = csv.writer(out)
    labels = {c["name"]: c["label"] for c in columns}
    w.writerow([c["label"] for c in columns] + (["Why it’s flagged"] if notes else []) + ["Salesforce link"])
    for r in rows:
        vals = r["values"]
        why = "; ".join(f"{labels.get(f, f)}: {n}" for f, n in (notes or {}).get(r.get("id") or "", {}).items())
        w.writerow([r["ref_names"].get(c["name"]) or ("" if vals.get(c["name"]) is None else vals.get(c["name"])) for c in columns]
                   + ([why] if notes else []) + [f"{prefix}{r['id']}" if r.get("id") else ""])
    name = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower() or "records"
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


# ---------------- the records behind one measure ("What we measure") ----------------

MAX_PICKED = 10  # fields a person can pick to show as a records table's columns


def _picked(fields: str | None, rec: dict | None = None) -> list[str] | None:
    """Fields picked to show as the columns (checked; the object's describe drops any it doesn't have)."""
    names = [f.strip() for f in (fields or "").split(",") if f.strip()]
    if not names:
        return None
    if len(names) > MAX_PICKED or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", f) for f in names):
        raise HTTPException(422, f"Pick up to {MAX_PICKED} fields.")
    if (rec or {}).get("extra") == "days_in_queue":  # Days in Queue counts from the Created Date when the owner never changed
        names.append("CreatedDate")
    return list(dict.fromkeys(names))

def _indicator_records(db: Session, assessment_id: str, area_id: str, label: str, obj: str | None,
                       only: str | None = None, period: str | None = None, queue: str | None = None,
                       days: int | None = None) -> tuple[dict, str, str]:
    """(object, where, org id, title) for one measure of one area, as saved by the health check that measured it.
    `only` = comma-separated fields: just the records with a problem in one of them (a flagged value, or for a
    missing-fields measure an empty value). `period` (No Activity only) = "90", "180" or "range:YYYY-MM-DD:YYYY-MM-DD" instead of
    the health check's 6 months. `queue` (Stuck Queue-Owned Leads only) = just the Leads in that queue, by its id; `days` = the
    Leads in a queue more than 3, 5 or 7 days (0 = every Lead in a queue; the card's own threshold when not given)."""
    row = _get(db, assessment_id)
    area = next((a for a in (row.results or {}).get("areas", []) if a.get("areaId") == area_id), None)
    ind = next((i for i in (area or {}).get("indicators", []) if i.get("label") == label), None)
    recs = (ind or {}).get("records") or []
    rec = next((r for r in recs if obj in (None, r.get("object"))), None)
    if rec is None:
        raise HTTPException(404, "This measure isn’t about specific records.")
    if period:
        if not label.startswith("No Activity") or not rec.get("where"):
            raise HTTPException(422, "Only the No Activity measures take a period.")
        try:
            rec = {**rec, "where": activity.with_period(rec["where"], period)}
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
    if rec.get("queue_days") is not None:  # Stuck Queue-Owned Leads: the Leads past the threshold picked on the card
        picked = rec["queue_days"] if days is None else days
        if picked not in (0, *queues.DAYS):
            raise HTTPException(422, "Pick more than 3, 5 or 7 days, or every Lead in a queue.")
        if picked:
            rec = {**rec, "where": " AND ".join([explorer.and_part(rec["where"]), *queues.longer_than(picked, bool(rec.get("history")))])}
    elif days is not None:
        raise HTTPException(422, "Only the Stuck Queue-Owned Leads measure takes a number of days.")
    if queue:
        if not _by_queue(rec):
            raise HTTPException(422, "Only the Stuck Queue-Owned Leads and Inactive Lead Assignment Rules measures take a queue.")
        if not re.fullmatch(r"00G[A-Za-z0-9]{12}([A-Za-z0-9]{3})?", queue):
            raise HTTPException(422, "Unknown queue.")
        rec = {**rec, "where": f"{explorer.and_part(rec['where'])} AND OwnerId = '{queue}'" if rec.get("where") else f"OwnerId = '{queue}'"}
    if only:
        fields = [f.strip() for f in only.split(",") if f.strip()][:20]
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(\.Name)?", f) for f in fields):  # a field, or a parent's name (Account.Name)
            raise HTTPException(422, "Unknown field.")
        notes = rec.get("notes")
        if notes is not None:  # flagged values (Data Standardization): the records with a reason on one of these fields
            ids = [i for i, n in notes.items() if any(f in n for f in fields)]
            where = "Id IN (" + ", ".join(f"'{i}'" for i in ids if re.fullmatch(r"[A-Za-z0-9]{15,18}", i)) + ")" if ids else "Id = null"
        elif label.startswith("Missing"):  # the records with any of these fields empty
            where = " OR ".join(f"{f} = null" for f in fields)
        else:
            raise HTTPException(422, "This measure can’t be narrowed to fields.")
        if rec.get("where"):  # within the measure's own records (its time window, open leads only…)
            where = f"{explorer.and_part(rec['where'])} AND ({where})"
        cols = rec.get("columns") or []  # the chosen fields right after the name, so they're always in view
        rec = {**rec, "where": where, "columns": list(dict.fromkeys(cols[:1] + fields + cols[1:]))}
    return rec, row.org_id, f"{label} {rec['object']}"


@router.get("/assessments/{assessment_id}/areas/{area_id}/indicator-records", response_model=FindingRecordsPage)
def indicator_records(
    assessment_id: str,
    area_id: str,
    label: str = Query(..., max_length=200),
    object: str | None = Query(None, max_length=80),
    cursor: str | None = Query(None, max_length=200),
    filters: str | None = Query(None, max_length=12000, description='JSON list of {"field","op","value"} column filters'),
    only: str | None = Query(None, max_length=1200, description="Comma-separated fields: only records with a problem in one of them"),
    period: str | None = Query(None, max_length=40, description='No Activity only: "90", "180" or "range:YYYY-MM-DD:YYYY-MM-DD"'),
    queue: str | None = Query(None, max_length=80, description="Stuck Queue-Owned Leads only: the queue's id"),
    days: int | None = Query(None, ge=0, le=7, description="Stuck Queue-Owned Leads only: in a queue more than 3, 5 or 7 days (0 = all)"),
    fields: str | None = Query(None, max_length=1200, description="Comma-separated fields to show as the columns, instead of the measure's"),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    """The records a measure counted, live from Salesforce (200 per page)."""
    rec, org_id, _ = _indicator_records(db, assessment_id, area_id, label, object, only, period, queue, days)
    picked = _picked(fields, rec)
    page = _salesforce(db, http, settings, lambda sf: explorer.records_matching(
        sf, rec["object"], rec.get("where"), cursor, columns=picked or rec.get("columns"), order=rec.get("order"), filters=_filters(filters),
        exact=bool(picked)), org_id)
    if rec.get("extra"):
        page["columns"] = _salesforce(db, http, settings, lambda sf: _with_extra(sf, rec, page["columns"], page["records"]), org_id)
    notes = rec.get("notes") or {}  # why each value was flagged, saved by the check (e.g. Data Standardization)
    page["cell_notes"] = {r["id"]: notes[r["id"]] for r in page["records"] if r.get("id") in notes}
    return page


@router.get("/assessments/{assessment_id}/areas/{area_id}/indicator-queues", response_model=list[QueueCount])
def indicator_queues(
    assessment_id: str,
    area_id: str,
    label: str = Query(..., max_length=200),
    object: str | None = Query(None, max_length=80),
    days: int | None = Query(None, ge=0, le=7),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    """Every queue that can own Leads, with how many of the measure's Leads sit in each (0 for the others), most first, for
    its Queue filter (Stuck Queue-Owned Leads)."""
    rec, org_id, _ = _indicator_records(db, assessment_id, area_id, label, object, days=days)
    if not _by_queue(rec):
        raise HTTPException(422, "Only the Stuck Queue-Owned Leads and Inactive Lead Assignment Rules measures are listed by queue.")
    where = f" WHERE {rec['where']}" if rec.get("where") else ""

    def load(sf):
        counts = {r["o"]: int(r.get("c") or 0) for r in sf.query(
            f"SELECT Owner.Name o, COUNT(Id) c FROM {rec['object']}{where} GROUP BY Owner.Name ORDER BY COUNT(Id) DESC LIMIT 200").get("records", [])
            if r.get("o")}
        queues: dict[str, str] = {}  # id -> name
        try:  # the org's Lead queues, so the empty ones show too
            for r in sf.query(f"SELECT QueueId, Queue.Name FROM QueueSobject WHERE SobjectType = '{rec['object']}' LIMIT 500").get("records", []):
                if r.get("QueueId") and (r.get("Queue") or {}).get("Name"):
                    queues[r["QueueId"]] = r["Queue"]["Name"]
        except SalesforceAuthExpired:
            raise
        except SalesforceError:
            pass
        missing = [n for n in counts if n not in queues.values()]
        if missing:  # counted, but not listed as a Lead queue (or the list couldn't be read): find them by name
            for r in sf.query(f"SELECT Id, Name FROM Group WHERE Type = 'Queue' AND {in_list('Name', missing)}").get("records", []):
                queues.setdefault(r["Id"], r["Name"])
        out = [{"id": i, "name": n, "count": counts.get(n, 0)} for i, n in queues.items()]
        return sorted(out, key=lambda q: (-q["count"], q["name"].lower()))

    return _salesforce(db, http, settings, load, org_id)


@router.get("/assessments/{assessment_id}/areas/{area_id}/indicator-values", response_model=FieldValues)
def indicator_values(
    assessment_id: str,
    area_id: str,
    label: str = Query(..., max_length=200),
    field: str = Query(..., max_length=120),
    object: str | None = Query(None, max_length=80),
    filters: str | None = Query(None, max_length=12000),
    only: str | None = Query(None, max_length=1200),
    period: str | None = Query(None, max_length=40, description='No Activity only: "90", "180" or "range:YYYY-MM-DD:YYYY-MM-DD"'),
    queue: str | None = Query(None, max_length=80, description="Stuck Queue-Owned Leads only: the queue's id"),
    days: int | None = Query(None, ge=0, le=7, description="Stuck Queue-Owned Leads only: in a queue more than 3, 5 or 7 days (0 = all)"),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    """The values of one column among a measure's records, for its filter drop-down."""
    rec, org_id, _ = _indicator_records(db, assessment_id, area_id, label, object, only, period, queue, days)
    return _salesforce(db, http, settings, lambda sf: explorer.field_values(
        sf, rec["object"], field, None, _filters(filters), base_where=rec.get("where")), org_id)


@router.get("/assessments/{assessment_id}/areas/{area_id}/indicator-records.csv")
def indicator_records_csv(
    assessment_id: str,
    area_id: str,
    label: str = Query(..., max_length=200),
    object: str | None = Query(None, max_length=80),
    filters: str | None = Query(None, max_length=12000),
    only: str | None = Query(None, max_length=1200),
    period: str | None = Query(None, max_length=40, description='No Activity only: "90", "180" or "range:YYYY-MM-DD:YYYY-MM-DD"'),
    queue: str | None = Query(None, max_length=80, description="Stuck Queue-Owned Leads only: the queue's id"),
    days: int | None = Query(None, ge=0, le=7, description="Stuck Queue-Owned Leads only: in a queue more than 3, 5 or 7 days (0 = all)"),
    fields: str | None = Query(None, max_length=1200, description="Comma-separated fields to show as the columns, instead of the measure's"),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    rec, org_id, title = _indicator_records(db, assessment_id, area_id, label, object, only, period, queue, days)
    picked = _picked(fields, rec)
    return _records_csv(db, http, settings, org_id, rec["object"], rec.get("where"), title, picked or rec.get("columns"), rec.get("order"),
                        _filters(filters), notes=rec.get("notes"), rec=rec, exact=bool(picked))


@router.get("/findings/{finding_id}", response_model=Finding)
def get_finding(finding_id: str, db: Session = Depends(get_db)):
    """One problem (for its own page)."""
    row, _check = _finding(db, finding_id)
    return to_finding(row, _measure_links(db, [row]).get(row.id))


@router.patch("/findings/{finding_id}", response_model=Finding)
def update_finding(finding_id: str, body: UpdateFindingRequest, _: Principal = Depends(require_editor), db: Session = Depends(get_db)):
    row, _check = _finding(db, finding_id)
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] is not None:
        row.status = data["status"]
    if "notes" in data:
        row.notes = (data["notes"] or "").strip() or None
    db.commit()
    return to_finding(row, _measure_links(db, [row]).get(row.id))
