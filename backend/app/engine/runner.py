"""Runs a health check in the background and stores scores and findings."""
import hashlib
import logging
import uuid
from datetime import datetime, timezone

import httpx

from sqlalchemy import select

from .. import alerts
from ..config import get_settings
from ..db import SessionLocal
from ..models import AssessmentRow, FindingRow
from ..salesforce import service
from ..salesforce.errors import SalesforceAuthExpired, SalesforceError
from . import adoption, data_quality, deep, integrations, quoting, reporting, workflows
from .combine import combined_view, summarize
from .core import DEFAULT_OBJECTS, PRIORITY, Ctx, NotSelected, Scope, Unavailable

log = logging.getLogger("aquarient.engine")

# Deeper outcome checks added to existing areas (see deep.py). Data Quality's scorecard stays last.
DEEP = {
    "area-7": [deep.automation_health],
    "area-8": [deep.report_trust],
    "area-10": [deep.forecast_setup],
    "area-20": [deep.sync_health],
}


def _with_deep(area: str, checks: list) -> list:
    extra = DEEP.get(area, [])
    if checks and checks[-1] is data_quality.scorecard:
        return [*checks[:-1], *extra, checks[-1]]
    return [*checks, *extra]


def _labels(module) -> dict:
    return {**module.STEP_LABELS, **deep.STEP_LABELS}


# area id -> (category id, checks, step labels)
_BASE = {
    **{area: ("data-quality", checks, _labels(data_quality)) for area, checks in data_quality.AREAS.items()},
    **{area: ("workflows", checks, _labels(workflows)) for area, checks in workflows.AREAS.items()},
    **{area: ("reporting", checks, _labels(reporting)) for area, checks in reporting.AREAS.items()},
    **{area: ("user-adoption", checks, _labels(adoption)) for area, checks in adoption.AREAS.items()},
    **{area: ("quoting", checks, _labels(quoting)) for area, checks in quoting.AREAS.items()},
    **{area: ("integrations", checks, _labels(integrations)) for area, checks in integrations.AREAS.items()},
}
AREAS = {area: (cat, _with_deep(area, checks), labels) for area, (cat, checks, labels) in _BASE.items()}
EXECUTABLE_AREA_IDS = sorted(AREAS, key=lambda a: int(a.split("-")[1]))

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mean(xs: list[float]) -> int | None:
    return round(sum(xs) / len(xs)) if xs else None


class Cancelled(Exception):
    pass


def execute(assessment_id: str, transport: httpx.BaseTransport | None = None) -> None:
    """Run a check a worker has already claimed (see jobs.py). Never raises: failures are stored on the check."""
    with SessionLocal() as db, httpx.Client(transport=transport, timeout=httpx.Timeout(60.0, connect=10.0)) as http:
        row = db.get(AssessmentRow, assessment_id)
        if row is None or row.status != "running":
            return
        try:
            _run(db, http, row)
        except Cancelled:
            row.current_step, row.worker_id = None, None
            db.commit()
        except SalesforceAuthExpired as exc:
            service.mark_expired(db, str(exc), row.org_id or None)
            _fail(db, row, "Your Salesforce connection timed out during the check. Reconnect and run it again.")
        except service.NotConnected:
            _fail(db, row, "Salesforce isn’t connected. Connect it and run the check again.")
        except BudgetTooLow as exc:
            _fail(db, row, str(exc))
        except Exception:  # noqa: BLE001 — store any unexpected error instead of leaving the run stuck
            log.exception("Health check %s failed", assessment_id)
            _fail(db, row, "Something went wrong while running the check. Please try again.")


def fingerprint(area_id: str, name: str, object_name: str | None) -> str:
    """The same problem across checks (area + problem + object)."""
    return hashlib.sha1(f"{area_id}|{name}|{object_name or ''}".encode()).hexdigest()


def _previous_findings(db, row: AssessmentRow, areas: set[str]) -> dict[str, FindingRow]:
    """Problems from the latest earlier check of this org, for the areas checked now, by fingerprint."""
    prev = db.scalars(
        select(AssessmentRow)
        .where(AssessmentRow.status == "completed", AssessmentRow.org_id == row.org_id, AssessmentRow.id != row.id)
        .order_by(AssessmentRow.completed_at.desc())
        .limit(1)
    ).first()
    if prev is None:
        return {}
    _, found = combined_view(db, prev)
    return {
        (f.fingerprint or fingerprint(f.area_id, f.name, f.object_name)): f
        for f in found
        if f.area_id in areas
    }


class BudgetTooLow(Exception):
    pass


# A full health check uses a few hundred API calls; leave plenty for the client's own integrations.
MIN_API_CALLS_LEFT = 1000
MIN_API_SHARE_LEFT = 0.05


def _check_api_budget(sf) -> None:
    try:
        lim = (sf.limits() or {}).get("DailyApiRequests") or {}
    except SalesforceError:
        return  # can't tell; carry on
    left, cap = lim.get("Remaining"), lim.get("Max")
    if left is not None and cap and (left < MIN_API_CALLS_LEFT or left < cap * MIN_API_SHARE_LEFT):
        raise BudgetTooLow(f"Only {left:,} of today’s {cap:,} Salesforce API calls are left, so the check didn’t start "
                           "to protect your other integrations. Try again after the daily limit resets.")


def _fail(db, row: AssessmentRow, message: str) -> None:
    row.status, row.error_message, row.completed_at, row.current_step, row.worker_id = "failed", message, _now(), None, None
    db.commit()


def _link_measures(metrics: list, findings: list) -> None:
    """Tie each problem a check raised to the measure the same check produced (so one panel shows both)."""
    if not metrics:
        return
    for f in findings:
        if f.measure:
            continue
        objs = {f.records_object, f.object_name} - {None}

        def fit(m) -> tuple:
            m_objs = {r.get("object") for r in (m.records or [])}
            same_records = any(r.get("object") == f.records_object and r.get("where") == f.records_where for r in (m.records or []))
            return (m.label == f.name, same_records, bool(objs & m_objs), m.score is not None)

        f.measure = max(metrics, key=fit).label


def _run(db, http: httpx.Client, row: AssessmentRow) -> None:
    sf = service.client_for(db, http, get_settings(), org_id=row.org_id or None)  # this check's org, not the active one
    sf.cache_reads = False  # a health check reads Salesforce live, never from the click cache
    _check_api_budget(sf)
    scope = row.scope or {}
    objects = tuple(dict.fromkeys(scope.get("objects") or DEFAULT_OBJECTS))  # keep order, drop repeats
    ctx = Ctx(sf, Scope(scope.get("lookbackDays"), scope.get("staleLeadDays", 30), scope.get("stuckOpportunityDays", 60), objects))
    area_ids = [a for a in scope.get("areaIds", []) if a in AREAS]
    steps = [(a, check) for a in area_ids for check in AREAS[a][1]]
    # Each step's share of the progress bar: none for the per-object steps whose object wasn't chosen (they're skipped at once).
    per_object = {"account": "Account", "contact": "Contact", "lead": "Lead", "opportunity": "Opportunity"}

    def weight(check) -> float:
        name = check.__name__
        if check.__module__.endswith("data_quality") and name.endswith("_cards"):
            obj = per_object.get(name.split("_")[0])
            if obj and obj not in objects or name.startswith("other_object") and not ctx.others():
                return 0.0
        return 1.0

    weights = [weight(check) for _, check in steps]
    total = sum(weights) or 1.0
    before = [sum(weights[:k]) for k in range(len(steps))]  # the share done when each step starts
    failures: dict[str, list[str]] = {}
    skipped: dict[str, list[str]] = {}
    ran: set[str] = set()  # areas where at least one check applied to the chosen objects

    for i, (area_id, check) in enumerate(steps):
        db.refresh(row)
        if row.status == "cancelled":
            raise Cancelled()
        row.progress = round(100 * before[i] / total)
        row.current_step = AREAS[area_id][2].get(check, "Checking your data")
        db.commit()
        ctx.area_id = area_id

        def report(done: float, i: int = i) -> None:  # progress within this step, saved only when the % changes
            pct = round(100 * (before[i] + done * weights[i]) / total)
            if pct != row.progress:
                row.progress = pct
                db.commit()

        ctx.on_progress = report
        before_m, before_f = len(ctx.metrics.get(area_id, [])), len(ctx.findings)
        try:
            check(ctx)
            ran.add(area_id)
        except NotSelected:
            pass  # none of this check's objects were chosen
        except Unavailable as exc:
            ran.add(area_id)
            skipped.setdefault(area_id, []).append(str(exc))
        except SalesforceAuthExpired:
            raise
        except (SalesforceError, httpx.HTTPError) as exc:
            log.warning("Check %s failed: %s", check.__name__, exc)
            failures.setdefault(area_id, []).append(f"{row.current_step}: {exc}")
        except Exception:  # noqa: BLE001 — one broken check shouldn't stop the others
            log.exception("Check %s crashed", check.__name__)
            failures.setdefault(area_id, []).append(f"{row.current_step}: unexpected error")
        _link_measures(ctx.metrics.get(area_id, [])[before_m:], ctx.findings[before_f:])

    db.refresh(row)
    if row.status == "cancelled":
        raise Cancelled()

    # ---- scores
    areas = []
    for area_id in sorted(scope.get("areaIds", []), key=lambda a: int(a.split("-")[1])):
        if area_id not in AREAS:
            areas.append({"areaId": area_id, "score": None, "status": "skipped", "indicators": [], "recordsEvaluated": None, "message": "This area isn’t checked automatically yet."})
            continue
        metrics = ctx.metrics.get(area_id, [])
        score = _mean([m.score for m in metrics if m.score is not None])
        notes = failures.get(area_id, []) + skipped.get(area_id, [])
        status = "assessed" if metrics or area_id in ran and not failures.get(area_id) else ("failed" if failures.get(area_id) else "skipped")
        areas.append({
            "areaId": area_id,
            "score": score,
            "status": status,
            "indicators": [{"label": m.label, "value": m.value, "unit": m.unit, "direction": m.direction, "score": m.score,
                            "how": m.how, "rule": m.rule, "records": m.records, "criteria": m.criteria,
                            "fieldScores": m.field_scores, "fieldList": m.field_list, "ruleList": m.rule_list, "outOf": m.out_of, "outOfLabel": m.out_of_label}
                           for m in metrics],
            "recordsEvaluated": sum(ctx.totals.values()) or None,
            "message": ("Some checks couldn’t run: " + " · ".join(notes)) if notes
            else None if area_id in ran else "None of the chosen objects are covered by this area.",
        })

    summary = summarize(areas)
    records = sum(ctx.totals.values())

    # ---- findings, compared with the previous check of the same org
    now = _now()
    checked = {a["areaId"] for a in areas if a["status"] == "assessed"}
    previous = _previous_findings(db, row, checked)
    current_prints: set[str] = set()
    for f in ctx.findings:
        fp = fingerprint(f.area_id, f.name, f.object_name)
        current_prints.add(fp)
        prev = previous.get(fp)
        # Keep people's triage: a problem they were reviewing or accepted stays that way; a "fixed" one that's back reopens.
        status = prev.status if prev is not None and prev.status in ("in-review", "accepted-risk") else "open"
        db.add(FindingRow(
            id=str(uuid.uuid4()),
            assessment_id=row.id,
            name=f.name,
            category_id=AREAS[f.area_id][0],
            area_id=f.area_id,
            severity=f.severity,
            priority=PRIORITY[f.severity],
            affected_records=f.affected_records,
            description=f.description,
            why_it_matters=f.why_it_matters,
            business_impact=f.business_impact,
            recommended_action=f.recommended_action,
            sample_records_url=f.sample_records_url,
            object_name=f.object_name,
            records_object=f.records_object,
            records_where=f.records_where,
            measure=f.measure,
            value_at_risk=f.value_at_risk,
            fix_url=f.fix_url,
            fingerprint=fp,
            previous_affected=prev.affected_records if prev is not None else None,
            status=status,
            notes=prev.notes if prev is not None else None,
            detected_at=now,
        ))
    resolved = [
        {"name": p.name, "areaId": p.area_id, "categoryId": p.category_id, "objectName": p.object_name,
         "severity": p.severity, "previousAffected": p.affected_records}
        for fp, p in previous.items()
        if fp not in current_prints
    ]

    problems: dict[str, int] = {}
    for f in ctx.findings:
        if f.object_name:
            problems[f.object_name] = problems.get(f.object_name, 0) + 1
    by_object = [
        {
            "name": obj,
            "label": ctx.label(obj),
            "records": st.records,
            "completeness": st.completeness,
            "duplicates": st.duplicates,
            "problems": problems.get(obj, 0),
        }
        for obj in objects
        if (st := ctx.stats.get(obj)) is not None
    ]

    row.results = {"assessmentId": row.id, **summary, "recordsAssessed": records, "areas": areas, "objects": by_object, "resolved": resolved}
    row.status = "completed" if any(a["status"] == "assessed" for a in areas) else "failed"
    if row.status == "failed":
        row.error_message = "None of the selected checks could run. " + " · ".join(sum(failures.values(), []) + sum(skipped.values(), []))[:900]
    row.progress, row.current_step, row.completed_at, row.worker_id = 100, None, now, None
    row.records_assessed = records
    db.commit()
    if row.status == "completed":
        # Headline numbers include areas carried forward from earlier checks.
        combined, findings = combined_view(db, row)
        row.overall_score, row.findings_count = combined["overallScore"], len(findings)
        db.commit()
        alerts.after_run(db, row)
