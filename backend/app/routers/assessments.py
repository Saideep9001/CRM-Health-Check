"""Health checks (assessments) and their findings. See docs/API_CONTRACT.md → Assessments."""
import uuid
from datetime import date, datetime, timedelta, timezone

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
from ..engine.core import in_list, soql_str
from ..engine.runner import EXECUTABLE_AREA_IDS
from ..models import AssessmentRow, FindingRow
from ..salesforce import activity, assignment, eac, email_templates, explorer, finder, paths, queues, rep_activity, service, web_leads
from ..salesforce.errors import SalesforceAuthExpired, SalesforceError
from ..schemas import (
    FieldValues,
    QueueCount,
    RuleTargets,
    SalesPath,
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


WEB_LABEL = "Web-to-Lead issues"

# Area 5 Opportunity cards whose records can be narrowed to one sales stage (the Stage chips above the table)
STAGE_CARDS = {"Stuck Opportunities", "Missing Next Steps", "Opportunities with an Overdue Close Date"}


def _by_stage(label: str, rec: dict) -> bool:
    return rec.get("object") == "Opportunity" and (label in STAGE_CARDS or label.startswith("No Activity"))


def _by_queue(rec: dict) -> bool:
    """Can this measure's records be narrowed to one Lead queue (Stuck Queue-Owned Leads, Inactive Lead Assignment Rules), one
    Status (Stale Leads) or one Stage (Stuck Opportunities, Missing Next Steps, No Activity in 6 Months on Opportunities, Overdue Close Date)?"""
    return (rec.get("extra") == "days_in_queue" or bool(rec.get("by_queue")) or rec.get("inactive_queues") is not None
            or bool(rec.get("by_status")) or bool(rec.get("by_stage")))


# Sales leadership opportunities: the Close Date filter above the table
CLOSE_PERIODS = {"this_month": "THIS_MONTH", "last_month": "LAST_MONTH", "this_quarter": "THIS_QUARTER", "last_quarter": "LAST_QUARTER",
                 "this_year": "THIS_YEAR", "last_year": "LAST_YEAR"}
OPP_DATE_FIELDS = {"created": ("CreatedDate", True), "closed": ("CloseDate", False)}  # field, and whether it's a date-time


def _opp_period(field: str, datetime_field: bool, value: str) -> str | None:
    """One date filter: a Salesforce date literal (month, quarter, year), a half year (January–June or July–December), or
    "range:YYYY-MM-DD:YYYY-MM-DD"; None for all dates."""
    if value in ("", "all"):
        return None
    if value in CLOSE_PERIODS:
        return f"{field} = {CLOSE_PERIODS[value]}"
    start = end = None
    if value in ("this_half", "last_half"):
        today = datetime.now(timezone.utc).date()
        first_half = today.month <= 6
        if value == "this_half":
            start, end = (date(today.year, 1, 1), date(today.year, 6, 30)) if first_half else (date(today.year, 7, 1), date(today.year, 12, 31))
        else:
            start, end = (date(today.year - 1, 7, 1), date(today.year - 1, 12, 31)) if first_half else (date(today.year, 1, 1), date(today.year, 6, 30))
        start, end = start.isoformat(), end.isoformat()
    elif (rng := re.fullmatch(r"range:(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2})", value)) and rng[1] <= rng[2]:
        start, end = rng[1], rng[2]
    else:
        raise HTTPException(422, "Pick a date period: this or last month, quarter, half year or year, or a From date on or before the To date.")
    if datetime_field:
        return f"{field} >= {start}T00:00:00Z AND {field} <= {end}T23:59:59Z"
    return f"{field} >= {start} AND {field} <= {end}"


def _close_date_where(period: str, fields: dict[str, tuple[str, bool]] | None = None) -> str | None:
    """Sales leadership opportunities' date filters, e.g. "created:this_month|closed:last_quarter": the Created Date and/or the
    Close Date (see _opp_period). A bare period is the Close Date (Closed Won / Closed Lost). None when no date is limited."""
    fields = fields or OPP_DATE_FIELDS
    conds = []
    for part in filter(None, period.split("|")):
        which, _, value = part.partition(":") if part.split(":", 1)[0] in fields else (list(fields)[-1], "", part)
        field, is_dt = fields[which]
        if cond := _opp_period(field, is_dt, value):
            conds.append(cond)
    return " AND ".join(conds) or None
# …and its status chips, which split All with no overlap: Closed Won must be closed too (a deal still open can carry IsWon = true when
# its stage's type was changed in Setup after it was saved, and would otherwise count as both Open and Closed Won)
OPP_STATUS = {"all": None, "open": "IsClosed = false", "won": "IsClosed = true AND IsWon = true", "lost": "IsClosed = true AND IsWon = false"}
# the status chips of each leadership table (a check saved before cases had just True: the opportunities' chips)
# Leads: Open = not converted and not in a closed status (Salesforce has no closed flag on lead statuses, so by its name:
# "Closed - Not Converted", "Unqualified", "Disqualified"…); Not Converted = every lead not converted
OPEN_LEAD = ("IsConverted = false AND (NOT Status LIKE 'Closed%') AND (NOT Status LIKE '%Unqualified%') "
             "AND (NOT Status LIKE '%Disqualified%')")
STATUS_FILTERS = {"opportunity": OPP_STATUS, "case": {"all": None, "open": "IsClosed = false", "closed": "IsClosed = true"},
                  "lead": {"all": None, "open": OPEN_LEAD, "converted": "IsConverted = true", "not_converted": "IsConverted = false"}}
# the leads' Converted column only means something for All (in the other views every lead has the same answer); Converted Date for
# All and Converted
HIDE_BY_STATUS = {"lead": {"open": ["IsConverted", "ConvertedDate"], "converted": ["IsConverted"],
                           "not_converted": ["IsConverted", "ConvertedDate"]}}
LEAD_DATE_FIELDS = {"created": ("CreatedDate", True), "converted": ("ConvertedDate", False)}
CAMPAIGN_COLUMN = {"name": "CampaignName", "label": "Campaign Name", "type": "string"}  # after Converted
# Customer support leadership: the Created Date and Closed Date filters (the same choices for both)
CASE_DATE_FIELDS = {"created": "CreatedDate", "closed": "ClosedDate"}
CASE_DATE_PERIODS = {"today": "TODAY", "last_week": "LAST_WEEK", "last_14": "LAST_N_DAYS:14", "this_month": "THIS_MONTH"}
CASE_AGE_COLUMN = {"name": "CaseAge", "label": "Case Age (Days)", "type": "int"}  # right after Reason
# Sales leadership opportunities: when the deal was closed (its Close Date, once it's closed), after Date Opened
DATE_CLOSED_COLUMN = {"name": "DateClosed", "label": "Date Closed", "type": "date"}


def _case_dates_where(period: str) -> str | None:
    """Customer support leadership's date filters, e.g. "created:today|closed:range:2026-11-01:2026-11-10": per date (created or closed),
    today, last week, the last 14 days, this month, or "range:YYYY-MM-DD:YYYY-MM-DD"; "all" (or nothing) for any date. A bare
    period means the Created Date (as before both dates could be picked). None when no date is limited."""
    conds = []
    for part in filter(None, period.split("|")):
        which, _, value = part.partition(":") if part.split(":", 1)[0] in CASE_DATE_FIELDS else ("created", "", part)
        field = CASE_DATE_FIELDS[which]
        if value in ("", "all"):
            continue
        if value in CASE_DATE_PERIODS:
            conds.append(f"{field} = {CASE_DATE_PERIODS[value]}")
            continue
        rng = re.fullmatch(r"range:(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2})", value)
        if not (rng and rng[1] <= rng[2]):
            raise HTTPException(422, "Pick a date period: today, last week, the last 14 days, this month, or a From date on or before the To date.")
        conds.append(f"{field} >= {rng[1]}T00:00:00Z AND {field} <= {rng[2]}T23:59:59Z")
    return " AND ".join(conds) or None


# Report usage: how much each report is used, after its own columns
# the last column, frozen: its share of all runs
USAGE_COLUMN = {"name": "UsagePct", "label": "Usage %", "type": "string", "frozen": True}
REPORT_TYPE_COLUMN = {"name": "ReportType", "label": "Report Type", "type": "string"}  # by its name, right after Report Name
SOURCE_REPORTS_COLUMN = {"name": "SourceReports", "label": "Source Reports", "type": "lines"}  # dashboards: one report per line
# dashboards: Dashboard Type in words, where the type was (Static: runs as one set user; Dynamic: as the viewer; team: a manager can view as their team)
DASHBOARD_MODE_COLUMN = {"name": "DashboardMode", "label": "Dashboard Running User", "type": "string"}
DASHBOARD_MODES = {"SpecifiedUser": "Static", "LoggedInUser": "Dynamic", "MyTeamUser": "Dynamic (team)"}
# Required field gaps: the rules each record breaks, one per line, the last column, frozen so it stays in view
BROKEN_RULES_COLUMN = {"name": "BrokenRules", "label": "Broken rule", "type": "lines", "frozen": True}
# its rule filter: the kind of rule, and how that kind's rules read in the Broken rule column (“Field: Page layout “X””)
RULE_KINDS = {"field": "Required on the field", "layout": "Page layout", "validation": "Validation rule", "trigger": "Apex trigger"}


# one role per line, the last column, frozen so it stays in view while the table scrolls sideways
def _rule_owner_ids(rec: dict) -> set[str]:
    """Inactive Lead Assignment Rules: the owners its records can be narrowed to (the inactive queues, and every inactive
    rule's queues and users), all Salesforce ids saved by the check."""
    ids = {q["id"] for q in rec.get("inactive_queues") or []} | {t["id"] for r in rec.get("rule_targets") or [] for t in r["targets"]}
    return {i for i in ids if re.fullmatch(r"00[5G][A-Za-z0-9]{12}([A-Za-z0-9]{3})?", i or "")}


# Account Hierarchy Chains: each parent Account's batch (the table groups its rows by it) and its Child Accounts, one per
# line, the last column, frozen; both saved by the check
# Possible Missing Parent Accounts: how sure, why (one clue per line) and the suggested parent (last, frozen); saved by the check
# The note (why it was guessed) shows under the suggested parent in the table, and as its own column in the CSV.
GUESS_COLUMNS = [{"name": "Confidence", "label": "Confidence", "type": "string"},
                 {"name": "WhyParent", "label": "Note (why it was guessed)", "type": "lines", "hidden": True},
                 {"name": "SuggestedParent", "label": "Suggested Parent Account", "type": "string", "frozen": True, "note": "WhyParent"}]
BATCH_COLUMN = {"name": "HierarchyBatch", "label": "Batch", "type": "int"}
CHILDREN_COLUMN = {"name": "ChildAccounts", "label": "Child Accounts", "type": "lines", "frozen": True}
DEAL_ROLES_COLUMN = {"name": "OpenDealRoles", "label": "Roles on Open Deals", "type": "lines", "frozen": True}
# Contacts to Multiple Accounts: every Account a Contact is related to, one per line ("lines" = shown stacked in the table).
RELATED_ACCOUNTS_COLUMN = {"name": "RelatedAccounts", "label": "Related Accounts", "type": "lines", "frozen": True}


def _add_related_accounts(sf, columns: list[dict], records: list[dict]) -> list[dict]:
    """Each listed Contact's Accounts (Account Contact Relationships, read live): its own Account first, then the others by
    name, one per line. The column goes last, frozen so it stays in view while the table scrolls sideways."""
    ids = [r["id"] for r in records if re.fullmatch(r"003[A-Za-z0-9]{12}([A-Za-z0-9]{3})?", r.get("id") or "")]
    accounts: dict[str, list[str]] = {}
    for i in range(0, len(ids), 200):
        chunk = ", ".join(f"'{x}'" for x in ids[i:i + 200])
        body = sf.query(f"SELECT ContactId, Account.Name, IsDirect FROM AccountContactRelation WHERE ContactId IN ({chunk}) "
                        "ORDER BY IsDirect DESC, Account.Name", max_rows=20000)
        rows = list(body.get("records", []))
        while not body.get("done", True) and body.get("nextRecordsUrl"):
            body = sf.get(body["nextRecordsUrl"])
            rows += body.get("records", [])
        for row in rows:
            name = (row.get("Account") or {}).get("Name")
            if name:
                accounts.setdefault(row["ContactId"][:15], []).append(name)
    for r in records:
        r["values"][RELATED_ACCOUNTS_COLUMN["name"]] = "\n".join(accounts.get((r.get("id") or "")[:15], [])) or None
    return [*(c for c in columns if c["name"] != RELATED_ACCOUNTS_COLUMN["name"]), RELATED_ACCOUNTS_COLUMN]  # last, frozen


def _with_extra(sf, rec: dict, columns: list[dict], records: list[dict]) -> list[dict]:
    """A measure's column that isn't a Salesforce field, added to the listed records: Days in Queue (worked out live, so it's
    always current), or the reason saved by the check (Assignment Gap Reason, Potential Match)."""
    if rec.get("extra") == "days_in_queue":
        return queues.add_days_in_queue(sf, columns, records)
    if rec.get("extra") == "assignment_gap":
        return assignment.add_gap_reason(columns, records, rec.get("reasons") or {}, rec.get("reason"))
    if rec.get("extra") == "rule_match":
        return assignment.add_reason(columns, records, rec.get("reasons") or {}, rec.get("reason"), column=assignment.MATCH_COLUMN)
    if rec.get("extra") == "related_accounts":
        return _add_related_accounts(sf, columns, records)
    if rec.get("extra") == "parent_guess":  # Possible Missing Parent Accounts: the most likely first
        saved = rec.get("reasons") or {}
        guess = lambda r: saved.get(r.get("id") or "") or {}  # noqa: E731
        for r in records:
            r["values"].update({"Confidence": guess(r).get("confidence"), "WhyParent": guess(r).get("why"),
                                "SuggestedParent": guess(r).get("parent")})
        records.sort(key=lambda r: (guess(r).get("rank", 9), str(r["values"].get("Name") or "").lower()))
        names = {c["name"] for c in GUESS_COLUMNS}
        return [*(c for c in columns if c["name"] not in names), *GUESS_COLUMNS]
    if rec.get("extra") == "inactive_parent":  # Child Accounts Under Inactive Parents: the inactive parent first, pinned on the left
        parent = next((c for c in columns if c["name"] == "ParentId"), None)
        if parent is None:
            return columns
        return [{**parent, "label": "Inactive Parent Account", "pinned": True}, *(c for c in columns if c["name"] != "ParentId")]
    if rec.get("extra") == "hierarchy":  # Account Hierarchy Chains: parent Accounts by batch, each with its Child Accounts
        saved = rec.get("reasons") or {}
        place = lambda r: saved.get(r.get("id") or "") or {}  # noqa: E731
        for r in records:
            r["values"].update({BATCH_COLUMN["name"]: place(r).get("batch"), CHILDREN_COLUMN["name"]: place(r).get("children")})
        # batch by batch, the top Account first (the rows come from Salesforce by name)
        records.sort(key=lambda r: (place(r).get("batch") or 10**9, place(r).get("level") or 0, str(r["values"].get("Name") or "").lower()))
        names = {BATCH_COLUMN["name"], CHILDREN_COLUMN["name"]}
        return [BATCH_COLUMN, *(c for c in columns if c["name"] not in names), CHILDREN_COLUMN]
    if rec.get("extra") == "case_age":  # Customer support leadership: days from opened to closed (or to today, while open)
        now = datetime.now(timezone.utc)
        for r in records:
            opened, closed = r["values"].get("CreatedDate"), r["values"].get("ClosedDate")
            try:
                start = datetime.fromisoformat(str(opened).replace("Z", "+00:00").replace("+0000", "+00:00"))
                end = datetime.fromisoformat(str(closed).replace("Z", "+00:00").replace("+0000", "+00:00")) if closed else now
                r["values"]["CaseAge"] = max(0, (end - start).days)
            except (TypeError, ValueError):
                r["values"]["CaseAge"] = None
        cols = [{**c, "label": {"CreatedDate": "Date Opened", "ClosedDate": "Date Closed"}.get(c["name"], c["label"])}
                for c in columns if c["name"] != CASE_AGE_COLUMN["name"]]
        at = next((i + 1 for i, c in enumerate(cols) if c["name"] == "Reason"), len(cols))
        cols.insert(at, CASE_AGE_COLUMN)
        return cols
    if rec.get("extra") == "lead_campaign":  # Marketing leadership: each lead's latest campaign, after Converted
        ids = [r["id"] for r in records if r.get("id") and re.fullmatch(r"[A-Za-z0-9]{15,18}", r["id"])]
        latest: dict[str, list[str]] = {}
        if ids:
            try:
                rows = sf.query("SELECT LeadId, Campaign.Name FROM CampaignMember WHERE LeadId IN ("
                                + ", ".join(f"'{i}'" for i in ids) + ") ORDER BY CreatedDate DESC").get("records", [])
            except SalesforceAuthExpired:
                raise
            except SalesforceError:
                rows = []
            for m in rows:
                name = (m.get("Campaign") or {}).get("Name")
                if name and name not in latest.setdefault(str(m.get("LeadId") or "")[:15], []):
                    latest[str(m.get("LeadId") or "")[:15]].append(name)
        for r in records:
            names = latest.get((r.get("id") or "")[:15], [])
            r["values"]["CampaignName"] = (names[0] + (f" (+{len(names) - 1} more)" if len(names) > 1 else "")) if names else None
        hide = set(rec.get("hide_cols") or [])
        cols = [{**c, "hidden": True} if c["name"] in hide else c for c in columns if c["name"] != CAMPAIGN_COLUMN["name"]]
        at = next((i + 1 for i, c in enumerate(cols) if c["name"] == "IsConverted"), len(cols))
        cols.insert(at, CAMPAIGN_COLUMN)
        return cols
    if rec.get("extra") == "opp_dates":  # Sales leadership opportunities: Date Opened (created) and Date Closed (Close Date, once closed)
        for r in records:
            r["values"]["DateClosed"] = r["values"].get("CloseDate") if r["values"].get("IsClosed") else None
        cols = [{**c, "hidden": True} if c["name"] == "IsClosed" else {**c, "label": "Date Opened"} if c["name"] == "CreatedDate" else c
                for c in columns if c["name"] != DATE_CLOSED_COLUMN["name"]]
        at = next((i + 1 for i, c in enumerate(cols) if c["name"] == "CreatedDate"), len(cols))
        cols.insert(at, DATE_CLOSED_COLUMN)
        return cols
    if rec.get("extra") == "report_usage":  # Report & dashboard usage: its share of all runs, frozen last
        saved, known = rec.get("reasons") or {}, bool(rec.get("usage_known"))
        report = rec.get("object") == "Report"
        for r in records:
            u = saved.get((r.get("id") or "")[:15]) or {}
            if not rec.get("no_usage"):
                r["values"]["UsagePct"] = f"{u.get('usage', 0)}%" if known else "N/A"
            if report:
                api = r["values"].get("ReportTypeApiName")
                r["values"]["ReportType"] = (rec.get("report_types") or {}).get(api) or api
            else:
                r["values"]["SourceReports"] = "\n".join((rec.get("sources") or {}).get((r.get("id") or "")[:15], [])) or None
                if not r["values"].get("DashboardResultRefreshedDate"):  # Salesforce leaves it empty: the check read it from the status
                    r["values"]["DashboardResultRefreshedDate"] = (rec.get("refreshed") or {}).get((r.get("id") or "")[:15])
                kind = r["values"].get("Type")
                r["values"]["DashboardMode"] = DASHBOARD_MODES.get(kind, kind)
        cols = [c for c in columns if c["name"] not in (USAGE_COLUMN["name"], REPORT_TYPE_COLUMN["name"], SOURCE_REPORTS_COLUMN["name"],
                                                         DASHBOARD_MODE_COLUMN["name"])]
        if report:  # the type's name right after Report Name; its API name stays hidden
            cols = [{**c, "hidden": True} if c["name"] == "ReportTypeApiName" else c for c in cols]
            at = next((i + 1 for i, c in enumerate(cols) if c["name"] == "Name"), len(cols))
            cols.insert(at, REPORT_TYPE_COLUMN)
        else:  # dashboards: Static / Dynamic where the type was; Last Refreshed Date; Source Reports after Last Modified Date
            cols = [{**c, "hidden": True} if c["name"] == "Type" else {**c, "label": "Last Refreshed Date"}
                    if c["name"] == "DashboardResultRefreshedDate" else c for c in cols]
            at = next((i + 1 for i, c in enumerate(cols) if c["name"] == "Type"), len(cols))  # Static / Dynamic where the type was
            cols.insert(at, DASHBOARD_MODE_COLUMN)
            at = next((i + 1 for i, c in enumerate(cols) if c["name"] == "LastModifiedDate"), len(cols))
            cols.insert(at, SOURCE_REPORTS_COLUMN)
        return cols if rec.get("no_usage") else [*cols, USAGE_COLUMN]
    if rec.get("extra") == "broken_rules":  # Required field gaps: the rules each record breaks, frozen on the right
        reasons = rec.get("reasons") or {}
        for r in records:
            r["values"][BROKEN_RULES_COLUMN["name"]] = reasons.get(r.get("id") or "")
        return [*(c for c in columns if c["name"] != BROKEN_RULES_COLUMN["name"]), BROKEN_RULES_COLUMN]
    if rec.get("extra") == "deal_roles":  # Multi-Deal Contacts: each Contact's roles on open deals, saved by the check
        reasons = rec.get("reasons") or {}
        for r in records:
            roles = reasons.get(r.get("id") or "")
            if roles and "\n" not in roles:  # saved by an older check as "2 open deals: A on X; B on Y"
                roles = re.sub(r"^\d+ open deals: ", "", roles).replace("; ", "\n")
            r["values"][DEAL_ROLES_COLUMN["name"]] = roles
        return [*(c for c in columns if c["name"] != DEAL_ROLES_COLUMN["name"]), DEAL_ROLES_COLUMN]
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
    if (rec or {}).get("extra") == "inactive_parent":  # Child Accounts Under Inactive Parents: the parent is always the first column
        names.insert(0, "ParentId")
    return list(dict.fromkeys(names))

def _unused_where(rec: dict, period: str) -> str:
    """Report usage / Dashboard usage, for the filter above the table: "all" = every one; "used" = used in the card's 180 days;
    "30" / "90" / "180" = unused: not used in that many days (or ever), past the 30-day grace period; "range:YYYY-MM-DD:YYYY-MM-DD" =
    unused, last used between the dates. Reports by their Last Run date; dashboards by their last refresh, saved by the check
    (Salesforce can't filter on it)."""
    base = rec.get("base_where") or "NamespacePrefix = null"
    used_days = int(rec.get("used_days") or 180)
    rng = re.fullmatch(r"range:(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2})", period)
    if period not in ("all", "used", "30", "90", "180") and not (rng and rng[1] <= rng[2]):
        raise HTTPException(422, "Pick All, Used, or Unused for the last 30, 90 or 180 days or a From date on or before the To date.")
    if period == "all":
        return base
    if period == "used" and rec.get("usage_known"):  # with Event Monitoring: only those with a share of runs (0% belongs under Unused)
        ids = [i for i, v in (rec.get("reasons") or {}).items() if (v or {}).get("runs") and re.fullmatch(r"[A-Za-z0-9]{15,18}", i)]
        return f"{base} AND " + ("Id IN (" + ", ".join(f"'{i}'" for i in ids) + ")" if ids else "Id = null")
    if rec.get("object") == "Report":
        if period == "used":
            return f"{base} AND LastRunDate = LAST_N_DAYS:{used_days}"
        if rng:
            return f"{base} AND LastRunDate >= {rng[1]}T00:00:00Z AND LastRunDate <= {rng[2]}T23:59:59Z"
        return f"{base} AND (LastRunDate < LAST_N_DAYS:{int(period)} OR LastRunDate = null) AND CreatedDate < LAST_N_DAYS:30"
    dashes = rec.get("dash_dates") or {}
    when = lambda v: str((v.get("date") if isinstance(v, dict) else v) or "")[:10]  # noqa: E731 - older checks saved just the date
    old = lambda v: v.get("old", True) if isinstance(v, dict) else True  # noqa: E731
    today = datetime.now(timezone.utc).date()
    if period == "used":
        cutoff = (today - timedelta(days=used_days)).isoformat()
        ids = [i for i, v in dashes.items() if when(v) and when(v) >= cutoff]
    elif rng:
        ids = [i for i, v in dashes.items() if when(v) and rng[1] <= when(v) <= rng[2]]
    else:
        cutoff = (today - timedelta(days=int(period))).isoformat()
        ids = [i for i, v in dashes.items() if old(v) and (not when(v) or when(v) < cutoff)]
    ids = [i for i in ids if re.fullmatch(r"[A-Za-z0-9]{15,18}", i)]
    return f"{base} AND " + ("Id IN (" + ", ".join(f"'{i}'" for i in ids) + ")" if ids else "Id = null")


def _indicator_records(db: Session, assessment_id: str, area_id: str, label: str, obj: str | None,
                       only: str | None = None, period: str | None = None, queue: str | None = None,
                       days: int | None = None, record_type: str | None = None) -> tuple[dict, str, str]:
    """(object, where, org id, title) for one measure of one area, as saved by the health check that measured it.
    `only` = comma-separated fields: just the records with a problem in one of them (a flagged value, or for a
    missing-fields measure an empty value). `period` (No Activity only) = "90", "180" or "range:YYYY-MM-DD:YYYY-MM-DD" instead of
    the health check's 6 months. `queue` (Stuck Queue-Owned Leads only) = just the Leads in that queue, by its id; `days` = the
    Leads in a queue more than 3, 5 or 7 days (0 = every Lead in a queue; the card's own threshold when not given).
    `record_type` (Stale Leads only) = just the Leads of one record type, by its id ("none" = the Leads with no record type)."""
    row = _get(db, assessment_id)
    area = next((a for a in (row.results or {}).get("areas", []) if a.get("areaId") == area_id), None)
    ind = next((i for i in (area or {}).get("indicators", []) if i.get("label") == label), None)
    recs = (ind or {}).get("records") or []
    rec = next((r for r in recs if obj in (None, r.get("object"))), None)
    if rec is None:
        raise HTTPException(404, "This measure isn’t about specific records.")
    if _by_stage(label, rec):  # works on checks saved before the Stage chips too
        rec = {**rec, "by_stage": True}
    if period and (rec.get("close_period") or rec.get("lead_dates")):  # opportunities (Created / Close Date), leads (Created / Converted)
        cond = _close_date_where(period, LEAD_DATE_FIELDS if rec.get("lead_dates") else None)
        if cond:
            rec = {**rec, "where": f"{explorer.and_part(rec['where'])} AND {cond}" if rec.get("where") else cond}
        period = None
    if period and rec.get("created_period"):  # Customer support leadership: cases created and/or closed in the periods picked
        cond = _case_dates_where(period)
        if cond:
            rec = {**rec, "where": f"{explorer.and_part(rec['where'])} AND {cond}" if rec.get("where") else cond}
        period = None
    if period and rec.get("unused_period"):  # Report / Dashboard usage: All, Used or Unused (for a period), picked above the table
        rec = {**rec, "where": _unused_where(rec, period), "no_usage": rec.get("no_usage") or period not in ("all", "used")}  # Unused: no Usage %
        period = None
    if label == WEB_LABEL:  # Web-to-Lead: the website Leads created in the period picked (any time by default)
        try:
            rec = {**rec, "where": web_leads.created_in(rec.get("where"), period), "order": "-CreatedDate"}  # newest first
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        period = None
    if period:
        stale = rec.get("stale_days") is not None  # Stale Leads: its own days and basis, saved by the check
        if not (label.startswith("No Activity") or stale) or not rec.get("where"):
            raise HTTPException(422, "Only the No Activity and Stale Leads measures take a period.")
        try:
            where = (activity.stale_with_period(rec["where"], int(rec["stale_days"]), bool(rec.get("stale_history")), period) if stale
                     else activity.with_period(rec["where"], period))
            rec = {**rec, "where": where}
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
    if record_type:
        if not rec.get("by_status"):
            raise HTTPException(422, "Only the Stale Leads measure takes a record type.")
        if record_type == "none":
            cond = "RecordTypeId = null"
        elif re.fullmatch(r"012[A-Za-z0-9]{12}([A-Za-z0-9]{3})?", record_type):
            cond = f"RecordTypeId = '{record_type}'"
        else:
            raise HTTPException(422, "Unknown record type.")
        rec = {**rec, "where": f"{explorer.and_part(rec['where'])} AND {cond}" if rec.get("where") else cond}
    if queue and rec.get("rule_kinds") is not None:  # Required field gaps: only the records breaking one kind of rule
        if queue not in RULE_KINDS:
            raise HTTPException(422, "Unknown kind of rule.")
        ids = [i for i, kinds in rec["rule_kinds"].items() if queue in kinds and re.fullmatch(r"[A-Za-z0-9]{15,18}", i)]
        cond = "Id IN (" + ", ".join(f"'{i}'" for i in ids) + ")" if ids else "Id = null"
        notes = (rec.get("kind_notes") or {}).get(queue) or {}
        reasons = {i: "\n".join(line for line in (rec.get("reasons") or {}).get(i, "").split("\n") if f": {RULE_KINDS[queue]}" in line)
                   for i in ids}
        rec = {**rec, "where": f"{explorer.and_part(rec['where'])} AND {cond}" if rec.get("where") else cond, "notes": notes, "reasons": reasons}
        queue = None
    if queue and rec.get("status_filter"):  # the leadership tables' status chips: opportunities (All, Open, Won, Lost), cases (All, Open, Closed)
        kind = rec["status_filter"] if isinstance(rec["status_filter"], str) else "opportunity"
        chips = STATUS_FILTERS.get(kind, OPP_STATUS)
        if queue not in chips:
            raise HTTPException(422, "Unknown status.")
        if chips[queue]:
            rec = {**rec, "where": f"{explorer.and_part(rec['where'])} AND {chips[queue]}" if rec.get("where") else chips[queue]}
        if hide := HIDE_BY_STATUS.get(kind, {}).get(queue):
            rec = {**rec, "hide_cols": hide}
        queue = None
    if queue:
        if not _by_queue(rec):
            raise HTTPException(422, "Only the Stuck Queue-Owned Leads and Inactive Lead Assignment Rules measures take a queue.")
        if rec.get("by_status") or rec.get("by_stage"):  # Stale Leads: one Status; the Opportunity cards: one Stage
            field = "StageName" if rec.get("by_stage") else "Status"
            if not re.fullmatch(r"[\w .,&/()'%+-]{1,80}", queue):
                raise HTTPException(422, f"Unknown {'Stage' if field == 'StageName' else 'Status'}.")
            cond = f"{field} = {soql_str(queue)}"
            rec = {**rec, "where": f"{explorer.and_part(rec['where'])} AND {cond}" if rec.get("where") else cond}
        elif rec.get("inactive_queues") is not None:  # Inactive Lead Assignment Rules: an inactive queue, or a rule's queues and users
            picked = [q.strip() for q in queue.split(",") if q.strip()]
            allowed = _rule_owner_ids(rec)
            if not picked or len(picked) > 100 or any(q not in allowed for q in picked):
                raise HTTPException(422, "Unknown queue.")
            base = rec.get("open_where") or rec["where"]  # the open Leads, so a rule's users count too
            rec = {**rec, "where": f"{explorer.and_part(base)} AND OwnerId IN ({', '.join(repr(q) for q in picked)})"}
        else:
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
    if rec.get("extra") == "inactive_parent":  # Child Accounts Under Inactive Parents: grouped by the parent (checks saved before it was)
        rec = {**rec, "order": "Parent.Name"}
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
    period: str | None = Query(None, max_length=120, description='No Activity only: "90", "180" or "range:YYYY-MM-DD:YYYY-MM-DD"'),
    queue: str | None = Query(None, max_length=80, description="A Lead queue's id (Stuck Queue-Owned Leads, Inactive Lead Assignment Rules)"),
    days: int | None = Query(None, ge=0, le=7, description="Stuck Queue-Owned Leads only: in a queue more than 3, 5 or 7 days (0 = all)"),
    fields: str | None = Query(None, max_length=1200, description="Comma-separated fields to show as the columns, instead of the measure's"),
    record_type: str | None = Query(None, max_length=20, description='Stale Leads only: a Lead record type\'s id, or "none" (no record type)'),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    """The records a measure counted, live from Salesforce (200 per page)."""
    rec, org_id, _ = _indicator_records(db, assessment_id, area_id, label, object, only, period, queue, days, record_type)
    picked = _picked(fields, rec)
    page = _salesforce(db, http, settings, lambda sf: explorer.records_matching(
        sf, rec["object"], rec.get("where"), cursor, columns=picked or rec.get("columns"), order=rec.get("order"), filters=_filters(filters),
        exact=bool(picked) or bool(rec.get("exact_columns"))), org_id)
    if rec.get("extra"):
        page["columns"] = _salesforce(db, http, settings, lambda sf: _with_extra(sf, rec, page["columns"], page["records"]), org_id)
    if rec.get("extra") == "hierarchy":
        page["sorted_by"] = BATCH_COLUMN["name"]  # the table groups the rows by batch
    notes = rec.get("notes") or {}  # why each value was flagged, saved by the check (e.g. Data Standardization)
    page["cell_notes"] = {r["id"]: notes[r["id"]] for r in page["records"] if r.get("id") in notes}
    if (g := rec.get("group_totals")) and not cursor:  # each group's count and totals (e.g. per owner), over every record listed
        page["group_totals"] = _salesforce(db, http, settings, lambda sf: explorer.group_totals(
            sf, rec["object"], rec.get("where"), _filters(filters), g["by"], g.get("sums") or [], g.get("count_by"), g.get("count_where")), org_id)
    if rec.get("sub_groups"):  # the fields rows are grouped by within each group (each named once per block)
        page["sub_groups"] = rec["sub_groups"]
    return page


@router.get("/assessments/{assessment_id}/areas/{area_id}/indicator-queues", response_model=list[QueueCount])
def indicator_queues(
    assessment_id: str,
    area_id: str,
    label: str = Query(..., max_length=200),
    object: str | None = Query(None, max_length=80),
    days: int | None = Query(None, ge=0, le=7),
    period: str | None = Query(None, max_length=120, description="Stale Leads: the period picked on the card"),
    record_type: str | None = Query(None, max_length=20, description='Stale Leads only: a Lead record type\'s id, or "none" (no record type)'),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    """Every queue that can own Leads, with how many of the measure's Leads sit in each (0 for the others), most first, for
    its Queue filter (Stuck Queue-Owned Leads); for Stale Leads, each Status the Leads are stuck in (of the record type picked)."""
    rec, org_id, _ = _indicator_records(db, assessment_id, area_id, label, object, period=period, days=days, record_type=record_type)
    if not _by_queue(rec):
        raise HTTPException(422, "Only the Stuck Queue-Owned Leads and Inactive Lead Assignment Rules measures are listed by queue.")
    where = f" WHERE {rec['where']}" if rec.get("where") else ""
    if rec.get("by_stage"):  # Stuck Opportunities, Missing Next Steps, No Activity: how many deals in each Stage, in the stages' order
        def stages(sf):
            rows = sf.query(f"SELECT StageName s, COUNT(Id) c FROM {rec['object']}{where} GROUP BY StageName LIMIT 200").get("records", [])
            counts = {r["s"]: int(r.get("c") or 0) for r in rows if r.get("s")}
            try:
                order = [s.get("ApiName") for s in sf.query("SELECT ApiName, SortOrder FROM OpportunityStage ORDER BY SortOrder").get("records", [])]
            except SalesforceAuthExpired:
                raise
            except SalesforceError:
                order = []
            rank = {n: i for i, n in enumerate(order)}
            return [{"id": n, "name": n, "count": c} for n, c in sorted(counts.items(), key=lambda x: (rank.get(x[0], len(rank)), x[0]))]
        return _salesforce(db, http, settings, stages, org_id)
    if rec.get("by_status"):  # Stale Leads: how many Leads are stuck in each Status, most first
        def statuses(sf):
            rows = sf.query(f"SELECT Status s, COUNT(Id) c FROM {rec['object']}{where} GROUP BY Status ORDER BY COUNT(Id) DESC LIMIT 100").get("records", [])
            return [{"id": r["s"], "name": r["s"], "count": int(r.get("c") or 0)} for r in rows if r.get("s")]
        return _salesforce(db, http, settings, statuses, org_id)
    if rec.get("inactive_queues") is not None:  # Inactive Lead Assignment Rules: only the queues out of the active routing
        def count(sf):
            out = [{**q, "count": int(sf.query(f"SELECT COUNT() FROM {rec['object']}{where} AND OwnerId = '{q['id']}'").get("totalSize") or 0)}
                   for q in rec["inactive_queues"]] if where else []
            return sorted(out, key=lambda q: (-q["count"], q["name"].lower()))
        return _salesforce(db, http, settings, count, org_id)

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
        routed = rec.get("routed_queues")  # the queues the active rule assigns to, saved by the check (None = not known)
        out = [{"id": i, "name": n, "count": counts.get(n, 0), "active": None if routed is None else i in routed} for i, n in queues.items()]
        return sorted(out, key=lambda q: (-q["count"], q["name"].lower()))

    return _salesforce(db, http, settings, load, org_id)


@router.get("/assessments/{assessment_id}/areas/{area_id}/indicator-record-types", response_model=list[QueueCount])
def indicator_record_types(
    assessment_id: str,
    area_id: str,
    label: str = Query(..., max_length=200),
    object: str | None = Query(None, max_length=80),
    period: str | None = Query(None, max_length=120, description="Stale Leads: the period picked on the card"),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    """Stale Leads: the org's Lead record types, each with how many of the stale Leads (for the period picked) have it, most
    first, for the Record Type filter. Empty when Leads have no record types."""
    rec, org_id, _ = _indicator_records(db, assessment_id, area_id, label, object, period=period)
    if not rec.get("by_status"):
        raise HTTPException(422, "Only the Stale Leads measure is listed by record type.")
    where = f" WHERE {rec['where']}" if rec.get("where") else ""

    def load(sf):
        try:
            types = {r["Id"]: (r.get("Name") or r["Id"], bool(r.get("IsActive"))) for r in sf.query(
                f"SELECT Id, Name, IsActive FROM RecordType WHERE SobjectType = {soql_str(rec['object'])} ORDER BY Name LIMIT 200").get("records", [])}
            if not types:
                return []  # no record types: nothing to pick
            counts = {r.get("r"): int(r.get("c") or 0) for r in sf.query(
                f"SELECT RecordTypeId r, COUNT(Id) c FROM {rec['object']}{where} GROUP BY RecordTypeId").get("records", [])}
        except SalesforceAuthExpired:
            raise
        except SalesforceError:  # no RecordTypeId on the object, or the record types can't be read
            return []
        out = [{"id": i, "name": n, "count": counts.get(i, 0)} for i, (n, active) in types.items() if active or counts.get(i)]
        if counts.get(None):  # Leads with no record type
            out.append({"id": "none", "name": "No record type", "count": counts[None]})
        return sorted(out, key=lambda t: (-t["count"], t["name"].lower()))

    return _salesforce(db, http, settings, load, org_id)


@router.get("/assessments/{assessment_id}/areas/{area_id}/web-lead-history")
def web_lead_history(
    assessment_id: str,
    area_id: str,
    label: str = Query(WEB_LABEL, max_length=200),
    year: int | None = Query(None, description="The chart's calendar year (none = the last 12 months)"),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
) -> dict:
    """Web-to-Lead: website Leads per week and per month, the latest one, and whether they're still arriving as usual
    (Healthy, Slowing, Stopped or No web leads), read live from Salesforce."""
    if label != WEB_LABEL:
        raise HTTPException(422, "Only the Web-to-Lead measure has a lead history.")
    rec, org_id, _ = _indicator_records(db, assessment_id, area_id, label, "Lead")
    if year is not None and not 2000 <= year <= datetime.now(timezone.utc).year + 1:
        raise HTTPException(422, "Pick a year from 2000 to this year.")
    return _salesforce(db, http, settings, lambda sf: web_leads.history(sf, rec.get("where"), year=year), org_id)


@router.get("/assessments/{assessment_id}/email-templates")
def email_templates_view(assessment_id: str, status: str = Query("all", description="all, active or inactive"),
                         db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep),
                         settings: Settings = Depends(settings_dep)) -> dict:
    """Email template availability: every email template with its type, status, the area it's used for and its share of all
    template use, read live from Salesforce."""
    row = _get(db, assessment_id)
    if status not in email_templates.STATUSES:
        raise HTTPException(422, "Pick all, active or inactive.")
    return _salesforce(db, http, settings, lambda sf: email_templates.email_templates(sf, status), row.org_id)


@router.get("/assessments/{assessment_id}/rep-activity")
def rep_activity_view(assessment_id: str, days: int = Query(rep_activity.DEFAULT_DAYS, description="7, 14, 30 or 90"),
                      start: date | None = Query(None, alias="from", description="Custom dates: the first day (YYYY-MM-DD)"),
                      end: date | None = Query(None, alias="to", description="Custom dates: the last day, included"),
                      db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)) -> dict:
    """Reps with No Activities Logged Recently: each rep with their Profile and how many Emails, Events and Tasks they logged
    in the last `days` days, read live from Salesforce."""
    row = _get(db, assessment_id)
    try:
        rep_activity.window(days, start, end)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return _salesforce(db, http, settings, lambda sf: rep_activity.rep_activity(sf, days, start, end), row.org_id)


@router.get("/assessments/{assessment_id}/eac-health")
def eac_health(assessment_id: str, db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep),
               settings: Settings = Depends(settings_dep)) -> dict:
    """Einstein Activity Capture (EAC) Health: system status, assigned users and the ones needing attention, and the
    activity flowing in, read live from Salesforce."""
    row = _get(db, assessment_id)
    return _salesforce(db, http, settings, eac.eac_health, row.org_id)


@router.get("/assessments/{assessment_id}/sales-paths", response_model=list[SalesPath])
def sales_paths(assessment_id: str, db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep),
                settings: Settings = Depends(settings_dep)):
    """Sales stage guidance gaps: the org's Opportunity Sales Paths (active first), each with every stage of its sales process
    and that stage's "Guidance for Success" and key fields, read live from Salesforce Setup."""
    row = _get(db, assessment_id)
    return _salesforce(db, http, settings, paths.sales_paths, row.org_id)


@router.get("/assessments/{assessment_id}/areas/{area_id}/indicator-rule-targets", response_model=RuleTargets)
def indicator_rule_targets(
    assessment_id: str,
    area_id: str,
    label: str = Query(..., max_length=200),
    object: str | None = Query(None, max_length=80),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    """Inactive Lead Assignment Rules: each inactive rule with who it assigns to (queues and users), and the inactive Lead
    queues, each with how many open Leads it owns now (live), for the chips above the records."""
    rec, org_id, _ = _indicator_records(db, assessment_id, area_id, label, object)
    if rec.get("inactive_queues") is None:
        raise HTTPException(422, "Only the Inactive Lead Assignment Rules measure is listed by rule.")
    rules = rec.get("rule_targets") or []
    targets: dict[str, dict] = {q["id"]: {"id": q["id"], "name": q["name"], "type": "Queue", "inactive": True} for q in rec["inactive_queues"]}
    for r in rules:
        for t in r["targets"]:
            targets.setdefault(t["id"], {**t, "inactive": False})
    ids = sorted(_rule_owner_ids(rec))
    base = rec.get("open_where") or "IsConverted = false"

    def load(sf):
        counts: dict[str, int] = {}
        for i in range(0, len(ids), 100):
            chunk = ", ".join(repr(x) for x in ids[i:i + 100])
            for row in sf.query(f"SELECT OwnerId o, COUNT(Id) c FROM {rec['object']} WHERE {explorer.and_part(base)} AND OwnerId IN ({chunk}) "
                                "GROUP BY OwnerId").get("records", []):
                counts[row["o"]] = int(row.get("c") or 0)
        out_targets = sorted(({**t, "count": counts.get(t["id"], 0)} for t in targets.values() if t["id"] in ids),
                             key=lambda t: (-t["count"], t["name"].lower()))
        out_rules = [{"name": r["name"], "targets": [t["id"] for t in r["targets"] if t["id"] in ids],
                      "count": sum(counts.get(t["id"], 0) for t in r["targets"])} for r in rules]
        return {"rules": out_rules, "targets": out_targets}

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
    period: str | None = Query(None, max_length=120, description='No Activity only: "90", "180" or "range:YYYY-MM-DD:YYYY-MM-DD"'),
    queue: str | None = Query(None, max_length=80, description="A Lead queue's id (Stuck Queue-Owned Leads, Inactive Lead Assignment Rules)"),
    days: int | None = Query(None, ge=0, le=7, description="Stuck Queue-Owned Leads only: in a queue more than 3, 5 or 7 days (0 = all)"),
    record_type: str | None = Query(None, max_length=20, description='Stale Leads only: a Lead record type\'s id, or "none" (no record type)'),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    """The values of one column among a measure's records, for its filter drop-down."""
    rec, org_id, _ = _indicator_records(db, assessment_id, area_id, label, object, only, period, queue, days, record_type)
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
    period: str | None = Query(None, max_length=120, description='No Activity only: "90", "180" or "range:YYYY-MM-DD:YYYY-MM-DD"'),
    queue: str | None = Query(None, max_length=80, description="A Lead queue's id (Stuck Queue-Owned Leads, Inactive Lead Assignment Rules)"),
    days: int | None = Query(None, ge=0, le=7, description="Stuck Queue-Owned Leads only: in a queue more than 3, 5 or 7 days (0 = all)"),
    fields: str | None = Query(None, max_length=1200, description="Comma-separated fields to show as the columns, instead of the measure's"),
    record_type: str | None = Query(None, max_length=20, description='Stale Leads only: a Lead record type\'s id, or "none" (no record type)'),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    rec, org_id, title = _indicator_records(db, assessment_id, area_id, label, object, only, period, queue, days, record_type)
    picked = _picked(fields, rec)
    return _records_csv(db, http, settings, org_id, rec["object"], rec.get("where"), title, picked or rec.get("columns"), rec.get("order"),
                        _filters(filters), notes=rec.get("notes"), rec=rec, exact=bool(picked) or bool(rec.get("exact_columns")))


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
