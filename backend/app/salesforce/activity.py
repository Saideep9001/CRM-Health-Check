"""Records with no activity for a while, with a period and a meaning of "activity" the person picks (read-only).

The filter is built here from a whitelist (basis) and a whole number of days, never from free text, so it can be
handed to `explorer.records_matching` like the health check's own filters.
"""
import re
from datetime import date, timedelta

from . import explorer
from .client import SalesforceClient

PERIODS = (90, 180, 365, 730)  # 3, 6, 12, 24 months
BASES = {"activity": "LastActivityDate", "edit": "LastModifiedDate"}  # tasks/events logged, or any change to the record
BASE_CONDS = {"Lead": "IsConverted = false"}  # only open Leads, as the health check counts them
# How long ago the last activity was, for the chart (ranges in days; the last one is "never").
BUCKETS = (("Under 3 months", 0, 90), ("3–6 months", 90, 180), ("6–12 months", 180, 365), ("1–2 years", 365, 730), ("Over 2 years", 730, None))


def _field(sf: SalesforceClient, obj: str, basis: str) -> str:
    if basis not in BASES:
        raise ValueError("Pick tasks and events, or any edit.")
    fields = explorer._fields(explorer._describe(sf, obj))
    f = BASES[basis]
    if f not in fields:  # e.g. an object with no activities: fall back to edits
        f = BASES["edit"]
    if f not in fields:
        raise ValueError("This object has no activity or edit date.")
    return f


def inactive_where(sf: SalesforceClient, obj: str, days: int, basis: str) -> tuple[str, str]:
    """(SOQL filter, date field) for records with no activity in `days` days, created before that."""
    if days not in PERIODS:
        raise ValueError("Pick 3, 6, 12 or 24 months.")
    f = _field(sf, obj, basis)
    fields = explorer._fields(explorer._describe(sf, obj))
    conds = [c for c in (BASE_CONDS.get(obj),) if c]
    conds.append(f"({f} = null OR {f} < LAST_N_DAYS:{days})")
    if "CreatedDate" in fields:
        conds.append(f"CreatedDate < LAST_N_DAYS:{days}")  # newer records haven't had the chance yet
    return " AND ".join(conds), f


def with_period(where: str, period: str) -> str:
    """The health check's own No Activity filter (6 months) for another period: "90" / "180" days (no activity in that
    time), or "range:YYYY-MM-DD:YYYY-MM-DD" (the last activity fell between those days, both included). Only the
    engine's `LAST_N_DAYS:180` conditions change."""
    if period.isdigit():
        if int(period) not in (90, 180):
            raise ValueError("Pick the last 3 or 6 months, or dates.")
        return where.replace("LAST_N_DAYS:180", f"LAST_N_DAYS:{period}")
    m = re.fullmatch(r"range:(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2})", period)
    try:
        start, end = (date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))) if m else (None, None)
    except ValueError:
        start = end = None
    if start is None or end is None or start > end or start > date.today() + timedelta(days=1):  # a day of slack for time zones
        raise ValueError("Pick a From date on or before the To date, not in the future.")
    after = end + timedelta(days=1)
    # LastActivityDate is a date; LastModifiedDate and CreatedDate are date-times.
    at = lambda f, d: d.isoformat() if f == "LastActivityDate" else f"{d.isoformat()}T00:00:00Z"  # noqa: E731
    where = re.sub(r"\((\w+) = null OR \1 < LAST_N_DAYS:180\)", lambda mt: f"({mt.group(1)} >= {at(mt.group(1), start)} AND {mt.group(1)} < {at(mt.group(1), after)})", where)
    return re.sub(r"\b(\w+) < LAST_N_DAYS:180\b", lambda mt: f"{mt.group(1)} < {at(mt.group(1), after)}", where)  # created by then


def inactivity(sf: SalesforceClient, obj: str, days: int, basis: str) -> dict:
    where, f = inactive_where(sf, obj, days, basis)
    base = BASE_CONDS.get(obj)
    count = lambda cond: int(sf.query(f"SELECT COUNT() FROM {obj}" + (f" WHERE {cond}" if cond else "")).get("totalSize") or 0)  # noqa: E731
    total = count(base)
    inactive = count(where)
    joined = (lambda c: f"{base} AND {c}" if base else c)  # noqa: E731
    buckets = []
    for label, lo, hi in BUCKETS:  # older than `lo` days and within `hi` days
        parts = ([f"{f} < LAST_N_DAYS:{lo}"] if lo else []) + ([f"{f} >= LAST_N_DAYS:{hi}"] if hi else [])
        buckets.append({"label": label, "count": count(joined(" AND ".join(parts)))})
    buckets.append({"label": "Never", "count": count(joined(f"{f} = null"))})
    label = explorer._fields(explorer._describe(sf, obj))[f].get("label") or f
    return {"object": obj, "days": days, "basis": basis, "field": f, "field_label": label,
            "total": total, "inactive": inactive, "buckets": buckets}
