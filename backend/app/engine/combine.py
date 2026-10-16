"""Combine health checks so every area shows its most recent result.

A check can cover just some areas (e.g. only Area 2). Its results then carry
forward, for every other area, the result of the most recent earlier completed
check of the same org that did assess it, together with that check's problems.
Nothing is copied: problems keep their original rows, so status and notes
updates stay in one place.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AssessmentRow, FindingRow

DATA_QUALITY_CATEGORIES = {"data-quality"}
SALES_PROCESS_CATEGORIES = {"workflows", "reporting"}
MAX_EARLIER = 50  # earlier checks to look through


def _mean(xs: list[float]) -> int | None:
    return round(sum(xs) / len(xs)) if xs else None


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def category_of(area_id: str) -> str | None:
    from .runner import AREAS  # local import: runner imports this module

    entry = AREAS.get(area_id)
    if entry:
        return entry[0]
    # Areas the engine can't run yet still belong to a category for display.
    n = int(area_id.split("-")[1]) if area_id.startswith("area-") else 0
    for cat, (lo, hi) in {"data-quality": (1, 2), "workflows": (3, 7), "reporting": (8, 11), "user-adoption": (12, 14),
                          "quoting": (15, 17), "integrations": (18, 21)}.items():
        if lo <= n <= hi:
            return cat
    return None


def summarize(areas: list[dict]) -> dict:
    """Category, overall, data quality and sales process scores from area results."""
    cat_scores: dict[str, list[float]] = {}
    for a in areas:
        cat = category_of(a["areaId"])
        if cat and a["status"] == "assessed" and a["score"] is not None:
            cat_scores.setdefault(cat, []).append(a["score"])
    categories = [{"categoryId": c, "score": _mean(s)} for c, s in cat_scores.items()]
    scored = [c for c in categories if c["score"] is not None]
    return {
        "categories": categories,
        "overallScore": _mean([c["score"] for c in scored]),
        "dataQualityScore": _mean([c["score"] for c in scored if c["categoryId"] in DATA_QUALITY_CATEGORIES]),
        "salesProcessScore": _mean([c["score"] for c in scored if c["categoryId"] in SALES_PROCESS_CATEGORIES]),
    }


def combined_view(db: Session, row: AssessmentRow) -> tuple[dict, list[FindingRow]]:
    """Results and problems for `row`, with older results filling areas it didn't check."""
    results = dict(row.results or {})
    areas: dict[str, dict] = {}
    source: dict[str, str] = {}  # area id -> assessment the result comes from
    for a in results.get("areas", []):
        areas[a["areaId"]] = {**a, "checkedAt": _iso(row.completed_at) if a["status"] == "assessed" else None, "sourceAssessmentId": row.id}
        if a["status"] == "assessed":
            source[a["areaId"]] = row.id

    if row.completed_at is not None:
        earlier = db.scalars(
            select(AssessmentRow)
            .where(
                AssessmentRow.status == "completed",
                AssessmentRow.org_id == row.org_id,
                AssessmentRow.id != row.id,
                AssessmentRow.completed_at < row.completed_at,
            )
            .order_by(AssessmentRow.completed_at.desc())
            .limit(MAX_EARLIER)
        ).all()
        for prev in earlier:
            for a in (prev.results or {}).get("areas", []):
                aid = a["areaId"]
                if a.get("status") == "assessed" and aid not in source:
                    areas[aid] = {**a, "checkedAt": _iso(prev.completed_at), "sourceAssessmentId": prev.id, "message": None}
                    source[aid] = prev.id

    ordered = sorted(areas.values(), key=lambda a: int(a["areaId"].split("-")[1]))
    results.update(summarize(ordered))
    results["areas"] = ordered
    results["assessmentId"] = row.id

    ids = set(source.values()) | {row.id}
    rows = db.scalars(select(FindingRow).where(FindingRow.assessment_id.in_(ids))).all()
    # A problem belongs to the view if its area's result comes from its own check.
    # Settings-type problems from this check stay even if its area wasn't scored.
    findings = [f for f in rows if source.get(f.area_id, row.id) == f.assessment_id]
    results["objects"] = _combine_objects(db, row, source, findings)
    return results, findings


# Which per-object numbers each area measures.
_OBJECT_FIELDS = {"records": None, "duplicates": "area-1", "completeness": "area-2"}


def _combine_objects(db: Session, row: AssessmentRow, source: dict[str, str], findings: list[FindingRow]) -> list[dict]:
    """Per-object rows: each number comes from the check that the area it belongs to came from."""
    checks = {row.id: row} | {r.id: r for r in db.scalars(select(AssessmentRow).where(AssessmentRow.id.in_(set(source.values())))).all()}
    merged: dict[str, dict] = {}
    for check_id in [row.id, *[i for i in dict.fromkeys(source.values()) if i != row.id]]:
        for o in (checks[check_id].results or {}).get("objects", []):
            m = merged.setdefault(o["name"], {"name": o["name"], "label": o.get("label") or o["name"], "records": None, "completeness": None, "duplicates": None})
            for key, area in _OBJECT_FIELDS.items():
                if m[key] is None and o.get(key) is not None and (area is None or source.get(area) == check_id):
                    m[key] = o[key]
    problems: dict[str, int] = {}
    for f in findings:
        if f.object_name:
            problems[f.object_name] = problems.get(f.object_name, 0) + 1
    return [{**m, "problems": problems.get(name, 0)} for name, m in merged.items()]
