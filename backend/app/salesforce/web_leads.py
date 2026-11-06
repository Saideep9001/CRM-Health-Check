"""Web-to-Lead: the website Leads (Lead Source is a web value), their created-date period on the card, and whether they are
still arriving as usual, from their history (read live from Salesforce, read-only).

Health compares the last 14 days with the 12 weeks before (days 15 to 98): Stopped when none arrived lately but some did
before, Slowing when fewer than half the usual number arrived, Healthy otherwise, and No web leads when none arrived in a year.
"""
import re
from datetime import date, timedelta

from .activity import _range
from .client import SalesforceClient

# the health check saved its website Leads with its own 90-day window; the card picks its own period instead
_SAVED_WINDOW = re.compile(r"\s+AND\s+CreatedDate = LAST_N_DAYS:90\b|^CreatedDate = LAST_N_DAYS:90\s+AND\s+")
PERIOD_DAYS = (7, 14, 30)
WEEKS = 12
MONTHS = 12


def base(where: str | None) -> str | None:
    """The website-Lead condition (Lead Source), without the health check's own 90-day window."""
    return _SAVED_WINDOW.sub("", where).strip() or None if where else None


def created_in(where: str | None, period: str | None) -> str | None:
    """Website Leads created in the period picked: "any" (or none) = all of them; "7", "14", "30" = the last that many days;
    "range:YYYY-MM-DD:YYYY-MM-DD" = between those days, both included."""
    w = base(where)
    if not period or period == "any":
        return w
    if period.isdigit():
        if int(period) not in PERIOD_DAYS:
            raise ValueError("Pick any time, the last 7 or 14 days, the last month, or dates.")
        cond = f"CreatedDate = LAST_N_DAYS:{int(period)}"
    else:
        start, after = _range(period)
        cond = f"CreatedDate >= {start.isoformat()}T00:00:00Z AND CreatedDate < {after.isoformat()}T00:00:00Z"
    return f"({w}) AND {cond}" if w else cond


def _month_back(today: date, n: int) -> date:
    y, m = today.year, today.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return date(y, m, 1)


def history(sf: SalesforceClient, where: str | None, today: date | None = None, year: int | None = None) -> dict:
    """Website Leads per week (last 12 weeks) and per month (the last 12 months, or January to December of `year`), the
    years that have website Leads (for the year picker), the latest one, and the health verdict."""
    today = today or date.today()
    if year is not None and not 2000 <= year <= today.year:
        raise ValueError(f"Pick a year from 2000 to {today.year}.")
    w = base(where)
    cond = f"({w}) AND " if w else ""
    daily: dict[date, int] = {}
    days_back = 7 * (WEEKS + 2)  # the 12 weeks shown, plus the 2 just before for the baseline
    for r in sf.query(f"SELECT DAY_ONLY(CreatedDate) d, COUNT(Id) c FROM Lead WHERE {cond}CreatedDate = LAST_N_DAYS:{days_back} "
                      "GROUP BY DAY_ONLY(CreatedDate)").get("records", []):
        try:
            daily[date.fromisoformat(str(r.get("d"))[:10])] = int(r.get("c") or 0)
        except ValueError:
            continue
    ago = lambda d: (today - d).days  # noqa: E731
    in_days = lambda lo, hi: sum(c for d, c in daily.items() if lo <= ago(d) <= hi)  # noqa: E731
    weeks = []
    for i in reversed(range(WEEKS)):  # oldest first; the last one ends today
        end = today - timedelta(days=7 * i)
        start = end - timedelta(days=6)
        weeks.append({"label": f"{start.strftime('%d %b')} – {end.strftime('%d %b')}", "start": start.isoformat(), "end": end.isoformat(),
                      "count": in_days(7 * i, 7 * i + 6)})
    first = date(year, 1, 1) if year else _month_back(today, MONTHS - 1)
    until = f" AND CreatedDate < {year + 1}-01-01T00:00:00Z" if year else ""
    monthly = {(int(r.get("y") or 0), int(r.get("m") or 0)): int(r.get("c") or 0) for r in sf.query(
        f"SELECT CALENDAR_YEAR(CreatedDate) y, CALENDAR_MONTH(CreatedDate) m, COUNT(Id) c FROM Lead WHERE {cond}"
        f"CreatedDate >= {first.isoformat()}T00:00:00Z{until} GROUP BY CALENDAR_YEAR(CreatedDate), CALENDAR_MONTH(CreatedDate)").get("records", [])}
    months = []
    for i in range(12) if year else reversed(range(MONTHS)):
        m = date(year, i + 1, 1) if year else _month_back(today, i)
        months.append({"label": m.strftime("%b %Y"), "count": monthly.get((m.year, m.month), 0)})
    earliest = sf.query(f"SELECT CreatedDate FROM Lead{' WHERE ' + w if w else ''} ORDER BY CreatedDate ASC LIMIT 1").get("records", [])
    since = int((earliest[0].get("CreatedDate") or str(today.year))[:4]) if earliest else today.year
    years = list(range(today.year, max(2000, min(since, today.year)) - 1, -1))  # newest first
    latest = sf.query(f"SELECT CreatedDate FROM Lead{' WHERE ' + w if w else ''} ORDER BY CreatedDate DESC LIMIT 1").get("records", [])
    last = (latest[0].get("CreatedDate") or "")[:10] or None if latest else None
    recent = in_days(0, 13)
    before = in_days(14, 14 + 7 * WEEKS - 1)  # the 12 weeks before the last 14 days
    expected = round(before / (7 * WEEKS) * 14, 1)
    in_chart = sum(x["count"] for x in months)
    if not in_chart and not recent and not before and not year:
        verdict, tone = "No web leads", "muted"
        why = "No website Leads in the last 12 months. If your website has a form, it may not be connected to Salesforce."
    elif not recent and before:
        verdict, tone = "Stopped", "bad"
        why = f"No website Leads in the last 14 days, but {before:,} arrived in the 12 weeks before (about {expected:g} every 14 days). The web form may be broken."
    elif expected >= 2 and recent < expected / 2:
        verdict, tone = "Slowing", "warn"
        why = f"{recent:,} website Leads in the last 14 days, less than half the usual {expected:g} (from the 12 weeks before)."
    else:
        verdict, tone = "Healthy", "good"
        why = (f"{recent:,} website Leads in the last 14 days" + (f", in line with the usual {expected:g} (from the 12 weeks before)." if before else "."))
    return {"verdict": verdict, "tone": tone, "why": why, "last14": recent, "expected14": expected,
            "last7": in_days(0, 6), "lastCreated": last, "weeks": weeks, "months": months, "year": year, "years": years}
