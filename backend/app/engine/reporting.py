"""Category 3 — Reporting & Dashboards (areas 8 to 11).

Based on the Aquarient RevenueOps Consultant Guide v1.0. Indicator labels match
src/config/categories.ts exactly. Everything is read-only SOQL; a few checks look
at report and dashboard names to see whether key topics are covered at all.
"""
import csv
import io
import re
from collections import Counter
from datetime import date, datetime, timezone

from ..salesforce.errors import SalesforceAuthExpired, SalesforceError
from .core import Ctx, FindingDraft, Unavailable, pct, rate_score
from .workflows import OPEN_OPPS, _LOST_REASON, _ids_in, _worth, activity_by_owner, sales_reps

UNUSED_DAYS = 180


# Where in Salesforce each setup problem is fixed.
SETTING_FIX = {
    'No dashboards': '/lightning/o/Dashboard/home',
    'Key leadership reports are missing': '/lightning/o/Report/home',
    'Lead Status changes aren’t tracked': '/lightning/setup/ObjectManager/Lead/FieldsAndRelationships/view',
    'Opportunity changes aren’t tracked': '/lightning/setup/ObjectManager/Opportunity/FieldsAndRelationships/view',
    'No report shows stuck deals': '/lightning/o/Report/home',
    'No report shows overdue deals': '/lightning/o/Report/home',
    'No report analyses why deals are lost': '/lightning/o/Report/home',
    'Win-loss can’t be analysed': '/lightning/o/Report/home',
    'Deals can’t be reported by region': '/lightning/setup/ObjectManager/Opportunity/FieldsAndRelationships/view',
    'No product data on won deals': '/lightning/o/Product2/home',
    'Products have no families': '/lightning/o/Product2/home',
}


def _setting(ctx: Ctx, name: str, description: str, action: str, severity: str = "medium", obj: str | None = None) -> None:
    ctx.findings.append(FindingDraft(
        area_id=ctx.area_id,
        name=name,
        severity=severity,  # type: ignore[arg-type]
        affected_records=0,
        description=description,
        why_it_matters="Leaders can only act on what they can see. Missing or cluttered reporting means decisions are made on gut feel.",
        business_impact="Slower, less confident decisions and problems spotted too late.",
        recommended_action=action,
        object_name=obj,
        fix_url=ctx.setup_url(SETTING_FIX[name]) if name in SETTING_FIX else None,
    ))


def _reports(ctx: Ctx) -> list[dict]:
    """All reports the connected user can see (name, folder, last run), cached for the run."""
    if "reports" not in ctx.memo:
        if not ctx.has_object("Report"):
            raise Unavailable("Reports can’t be read with this user.")
        ctx.memo["reports"] = ctx.rows("SELECT Id, Name, FolderName, LastRunDate, CreatedDate FROM Report WHERE NamespacePrefix = null ORDER BY Name LIMIT 10000", 10000)
    return ctx.memo["reports"]


def _dashboards(ctx: Ctx) -> list[dict]:
    if "dashboards" not in ctx.memo:
        ctx.memo["dashboards"] = (
            ctx.rows("SELECT Id, Title, FolderName, LastViewedDate, CreatedDate FROM Dashboard WHERE NamespacePrefix = null ORDER BY Title LIMIT 5000", 5000)
            if ctx.has_object("Dashboard") else []
        )
    return ctx.memo["dashboards"]


def _has_report(ctx: Ctx, pattern: str) -> bool:
    """Is there any report or dashboard whose name matches this topic?"""
    rx = re.compile(pattern, re.I)
    try:
        names = [r.get("Name") or "" for r in _reports(ctx)] + [d.get("Title") or "" for d in _dashboards(ctx)]
    except Unavailable:
        return True  # can't tell; don't raise a false alarm
    return any(rx.search(n) for n in names)


# ---------------------------------------------------------------- area 8: unused reports, leadership insights

USAGE_DAYS = 30  # report runs counted from Event Monitoring's Report event log
USAGE_MAX_LOGS = 31  # daily log files read
USAGE_MAX_LOG_BYTES = 200_000_000  # a log file bigger than this is skipped


_EVENT_ID = {"Report": ("REPORT_ID_DERIVED", "REPORT_ID"), "Dashboard": ("DASHBOARD_ID_DERIVED", "DASHBOARD_ID")}


def _runs(ctx: Ctx, kind: str) -> tuple[dict[str, dict], str | None]:
    """Per report or dashboard (15-character id) in the last 30 days, from Event Monitoring's Report / Dashboard event log: its share
    of all runs (usage %) and its runs. ({}, why) when it isn't available: Salesforce records runs only with Event
    Monitoring (Shield or the add-on)."""
    if not ctx.has_object("EventLogFile"):
        return {}, "This org doesn’t have Event Monitoring (or the connected user can’t read event logs), so how often each one is used isn’t recorded"
    logs: list[dict] = []
    for soql in (f"SELECT Id, LogDate, LogFileLength FROM EventLogFile WHERE EventType = '{kind}' AND Interval = 'Daily' "
                 f"AND LogDate = LAST_N_DAYS:{USAGE_DAYS} ORDER BY LogDate DESC",
                 f"SELECT Id, LogDate, LogFileLength FROM EventLogFile WHERE EventType = '{kind}' AND LogDate = LAST_N_DAYS:{USAGE_DAYS} "
                 "ORDER BY LogDate DESC"):
        try:
            logs = ctx.rows(soql, limit=USAGE_MAX_LOGS)
            break
        except SalesforceAuthExpired:
            raise
        except SalesforceError:
            continue
    if not logs:
        return {}, f"Event Monitoring has no {kind} event logs for the last {USAGE_DAYS} days (that event type may not be in this org’s licence)"
    runs: Counter = Counter()
    version = ctx.sf.settings.sf_api_version
    for log in logs:
        if (log.get("LogFileLength") or 0) > USAGE_MAX_LOG_BYTES or not log.get("Id"):
            continue
        try:
            text = ctx.sf.request("GET", f"/services/data/{version}/sobjects/EventLogFile/{log['Id']}/LogFile", accept="text/csv").text
        except SalesforceAuthExpired:
            raise
        except SalesforceError:
            continue
        for row in csv.DictReader(io.StringIO(text)):
            rid = next((row[c] for c in _EVENT_ID[kind] if row.get(c)), "")[:15]
            if not rid:
                continue
            runs[rid] += 1
    total = sum(runs.values())
    return {rid: {"runs": n, "usage": round(100 * n / total, 1)}
            for rid, n in runs.items()}, None


# The table, as Salesforce names the fields: grouped by folder; Usage is added (frozen, last) when it's listed.
REPORT_USAGE_COLUMNS = ["FolderName", "Name", "ReportTypeApiName", "CreatedById", "CreatedDate", "LastViewedDate", "LastRunDate",
                        "LastModifiedById", "LastModifiedDate"]


def _report_type_names(ctx: Ctx) -> dict[str, str]:
    """Report type API name -> the name people see in Salesforce (e.g. Opportunity -> “Opportunities”), from the Analytics API."""
    try:
        body = ctx.sf.get(f"/services/data/{ctx.sf.settings.sf_api_version}/analytics/reportTypes")
    except SalesforceAuthExpired:
        raise
    except SalesforceError:
        return {}
    out: dict[str, str] = {}
    for group in body if isinstance(body, list) else []:
        for t in group.get("reportTypes") or []:
            if t.get("type"):
                out[t["type"]] = t.get("label") or t["type"]
    return out
# Dashboards, as the org names the fields: Title, Dashboard Type, Created By/Date, Running User, Last Modified By/Date. The refreshed
# date (when it was last run) is read for its usage score but not shown; Source Reports and Usage are added when it's listed.
DASHBOARD_USAGE_COLUMNS = ["FolderName", "Title", "Type", "CreatedById", "CreatedDate", "RunningUserId", "LastModifiedById", "LastModifiedDate",
                           "DashboardResultRefreshedDate"]


def _dashboard_sources(ctx: Ctx, dashboard_ids: list[str]) -> dict[str, list[str]]:
    """The reports each dashboard's components show (dashboard id 15 -> report names, in order), from its components."""
    safe = [i for i in dashboard_ids if re.fullmatch(r"[A-Za-z0-9]{15,18}", i or "")]
    if not safe or not ctx.has_object("DashboardComponent"):
        return {}
    names = {str(r.get("Id") or "")[:15]: r.get("Name") or "" for r in _reports(ctx)}
    out: dict[str, list[str]] = {}
    for i in range(0, len(safe), 200):  # Salesforce wants components asked for by dashboard
        try:
            rows = ctx.rows("SELECT DashboardId, CustomReportId FROM DashboardComponent WHERE DashboardId IN ("
                            + ", ".join(f"'{x}'" for x in safe[i:i + 200]) + ")", 50000)
        except SalesforceAuthExpired:
            raise
        except SalesforceError:
            return out
        for r in rows:
            rid = str(r.get("CustomReportId") or "")[:15]
            name = names.get(rid) or (f"Report {rid}" if rid else "")
            mine = out.setdefault(str(r.get("DashboardId") or "")[:15], [])
            if name and name not in mine:
                mine.append(name)
    return out


# Each report's (or dashboard's) usage score: how recently it was used. Run in the last 30 days (or found in Event Monitoring's runs) = 100.
USAGE_SCORE_STEPS = ((30, 100), (90, 75), (180, 50), (365, 25))


def usage_score(days: int | None, runs: int = 0) -> int:
    """100 used in the last 30 days, 75 within 90, 50 within 180, 25 within a year, 0 older or never."""
    if runs:
        return 100
    if days is None:
        return 0
    return next((score for limit, score in USAGE_SCORE_STEPS if days <= limit), 0)


def days_since(value: object) -> int | None:
    text = str(value or "")[:10]
    try:
        return (datetime.now(timezone.utc).date() - date.fromisoformat(text)).days if text else None
    except ValueError:
        return None


def report_usage(ctx: Ctx) -> None:
    """Report & dashboard usage: every report and dashboard, by folder, with who made and changed it, when it was last viewed and run,
    and its usage: a score from how recently it was used, and its share of all runs (Event Monitoring). The card's score is the
    average of those scores."""
    reports = _reports(ctx)
    total = len(reports)
    report_runs, why_not = _runs(ctx, "Report")
    has_dash = ctx.has_object("Dashboard")
    dash_runs, dash_why = _runs(ctx, "Dashboard") if has_dash else ({}, None)
    dashes: list[dict] = []
    if has_dash:
        try:  # when each dashboard's data was last refreshed (when it was last run)
            dashes = ctx.rows("SELECT Id, DashboardResultRefreshedDate FROM Dashboard WHERE NamespacePrefix = null LIMIT 5000", 5000)
            dash_date = "DashboardResultRefreshedDate"
        except SalesforceAuthExpired:
            raise
        except SalesforceError:
            dashes, dash_date = _dashboards(ctx), "LastViewedDate"
    scores = [usage_score(days_since(r.get("LastRunDate")), (report_runs.get(str(r.get("Id") or "")[:15]) or {}).get("runs", 0)) for r in reports]
    scores += [usage_score(days_since(d.get(dash_date)), (dash_runs.get(str(d.get("Id") or "")[:15]) or {}).get("runs", 0)) for d in dashes]
    used = sum(1 for x in scores if x >= 75)  # used in the last 90 days
    score = round(sum(scores) / len(scores), 1) if scores else 100
    records = [("Report", "NamespacePrefix = null")] + ([("Dashboard", "NamespacePrefix = null")] if has_dash else [])
    steps = ", ".join(f"{sc} within {d} days" for d, sc in USAGE_SCORE_STEPS)
    m = ctx.metric(
        "Report & dashboard usage", pct(used, len(scores)) if scores else 0, "%", "higher-better", score,
        how="Every report and dashboard, grouped by folder, with Usage %: its share of all report (or dashboard) runs in the last 30 days, "
            "from Event Monitoring. The number is the share used in the last 90 days; the score averages how recently each one was used.",
        rule=f"Each report and dashboard scores by how recently it was used: {steps}, 0 older or never. The card’s score is their average.",
        records=records,
        recent=False,
        columns=REPORT_USAGE_COLUMNS + [c for c in DASHBOARD_USAGE_COLUMNS if c not in REPORT_USAGE_COLUMNS],
        order="FolderName",
        extra="report_usage",
        criteria=[
            ("Records checked", f"{total:,} reports" + (f" and {len(dashes):,} dashboards" if has_dash else "")
             + " (from installed packages aren’t counted)."),
            ("Usage score", f"Per report or dashboard: {steps}, and 0 when older or never used. Reports by their Last Run date, dashboards "
             "by when their data was last refreshed. Run in the last 30 days in Event Monitoring = 100"),
            ("What's counted", f"{used:,} of {len(scores):,} reports and dashboards ({pct(used, len(scores)):.0f}%) were used in the last 90 days "
             f"(score 75 or more). Average usage score: {score:.0f}."),
            ("Usage %", f"Each report’s share of all report runs in the last {USAGE_DAYS} days ({sum(v['runs'] for v in report_runs.values()):,} runs)"
             if report_runs else f"N/A: {why_not}"),
            ("Report Type", "The report type each report is built on, by the name Salesforce shows (its API name when the name can’t be read)"),
            ("Dashboard columns", "The org’s own fields: Title, Dashboard Type, Created By, Created Date, Running User, Last Modified By, "
             "Last Modified Date; and Source Reports, the reports its components show"),
            ("Last Viewed Date", "When the report was last opened, as Salesforce keeps it. Salesforce records this per user, "
             "so it’s the connected user’s last view"),
            ("Last Run", "Reports: the Last Run date. Dashboards: when their data was last refreshed (used for the usage score)"),
            ("Dashboards", (f"Usage % from the Dashboard event log ({sum(v['runs'] for v in dash_runs.values()):,} views)" if dash_runs
                            else f"Usage % N/A: {dash_why}") if has_dash else "Dashboards can’t be read with this user"),
        ],
    )
    for spec in m.records or []:
        spec["exact_columns"] = True  # just these columns, in this order
        spec["columns"] = REPORT_USAGE_COLUMNS if spec["object"] == "Report" else DASHBOARD_USAGE_COLUMNS
        runs = report_runs if spec["object"] == "Report" else dash_runs
        spec["reasons"] = runs
        spec["usage_known"] = bool(runs)
        spec["date_field"] = "LastRunDate" if spec["object"] == "Report" else "DashboardResultRefreshedDate"
        if spec["object"] == "Report":
            spec["report_types"] = _report_type_names(ctx)  # Report Type shown by its name, not its API name
        else:
            spec["sources"] = _dashboard_sources(ctx, [str(d.get("Id") or "") for d in dashes])  # Source Reports, per dashboard


def unused_reports(ctx: Ctx) -> None:
    _reports(ctx)
    total = ctx.count("Report", "NamespacePrefix = null", "CreatedDate < LAST_N_DAYS:30", recent=False)
    stale = (f"(LastRunDate < LAST_N_DAYS:{UNUSED_DAYS} OR LastRunDate = null)", "NamespacePrefix = null", "CreatedDate < LAST_N_DAYS:30")
    n = ctx.count("Report", *stale, recent=False) if total else 0
    ctx.totals["Report"] = total
    score = rate_score(n / total, 0.8) if total else 100
    ctx.metric(
        "Unused reports", n, "count", "lower-better", score,
        how=f"We count reports that nobody has run in the last {UNUSED_DAYS} days (or ever), out of all reports older than 30 days. Reports from installed packages are left out.",
        rule="100 when every report has been run recently, falling evenly to 0 when 80% of reports are unused.",
        records=("Report", *stale),
        recent=False,
        columns=["Name", "LastRunDate", "FolderName", "CreatedDate", "OwnerId"],
        order="LastRunDate",
        criteria=[
            ("Records checked", f"{total:,} reports created more than 30 days ago. Reports from installed packages aren’t counted, and newer reports get a 30-day grace period."),
            ("Fields checked", "Last Run date and Created date"),
            ("Unused", f"Not run in the last {UNUSED_DAYS} days, or never run at all, and created more than 30 days ago."),
            ("What's counted", f"{n:,} of {total:,} reports ({pct(n, total):.0f}%) are unused."),
            ("Records listed", "Every unused report, oldest last run first (never-run reports at the top)."),
        ],
    )
    if n:
        oldest = ctx.rows(f"SELECT Name, FolderName, LastRunDate FROM Report WHERE {' AND '.join(stale)} ORDER BY LastRunDate ASC NULLS FIRST LIMIT 5", 5)
        ctx.finding(
            name="Reports nobody runs",
            records=("Report", *stale),
            recent=False,
            fix="/lightning/o/Report/home",
            score=score,
            affected=n,
            description=f"{n:,} of your {total:,} reports ({pct(n, total):.0f}%) haven’t been run in {UNUSED_DAYS}+ days (reports from installed packages aren’t counted). For example: "
            + ", ".join(f"“{r.get('Name')}” ({r.get('FolderName') or 'no folder'})" for r in oldest) + ".",
            why="Hundreds of old reports make it hard to find the right one, and people end up building yet another copy.",
            impact="Wasted time, conflicting numbers, and slower reporting.",
            action="Archive or delete unused reports (move them to an “Archive” folder first, then delete after 90 days). Keep one trusted report per question.",
            obj="Report",
        )


def unused_dashboards(ctx: Ctx) -> None:
    if not ctx.has_object("Dashboard"):
        raise Unavailable("Dashboards can’t be read with this user.")
    total = ctx.count("Dashboard", "NamespacePrefix = null", "CreatedDate < LAST_N_DAYS:30", recent=False)
    n = ctx.count("Dashboard", f"(LastViewedDate < LAST_N_DAYS:{UNUSED_DAYS} OR LastViewedDate = null)", "NamespacePrefix = null", "CreatedDate < LAST_N_DAYS:30", recent=False) if total else 0
    no_dashboards = total == 0 and ctx.count("Dashboard", "NamespacePrefix = null", recent=False) == 0
    score = 40 if no_dashboards else rate_score(n / total, 0.8) if total else 100
    ctx.metric(
        "Unused dashboards", n, "count", "lower-better", score,
        how=f"We count dashboards that haven’t been opened in the last {UNUSED_DAYS} days (or ever) by the connected user, out of all dashboards older than 30 days. Dashboards from installed packages are left out.",
        rule="100 when every dashboard has been opened recently, falling evenly to 0 when 80% are unused. If there are no dashboards at all, the score is 40.",
        records=("Dashboard", f"(LastViewedDate < LAST_N_DAYS:{UNUSED_DAYS} OR LastViewedDate = null)", "NamespacePrefix = null", "CreatedDate < LAST_N_DAYS:30"),
        recent=False,
        columns=["Title", "LastViewedDate", "FolderName", "CreatedDate"],
        order="LastViewedDate",
        criteria=[
            ("Records checked", f"{total:,} dashboards created more than 30 days ago. Dashboards from installed packages aren’t counted."),
            ("Fields checked", "Last Viewed date and Created date"),
            ("Unused", f"Not opened in the last {UNUSED_DAYS} days, or never opened, and created more than 30 days ago."),
            ("Whose views", "Salesforce only shares view dates for the connected user, so this reflects that user’s viewing."),
            ("What's counted", f"{n:,} of {total:,} dashboards ({pct(n, total):.0f}%) are unused." if total else "There are no dashboards older than 30 days to check."),
            ("No dashboards at all", "There are no dashboards in this org, so the score is set to 40." if no_dashboards else ""),
            ("Records listed", "Every unused dashboard, least recently viewed first (never-viewed ones at the top)."),
        ],
    )
    if no_dashboards:
        _setting(
            ctx,
            "No dashboards",
            "There are no dashboards, so managers and leaders have no at-a-glance view of the business.",
            "Build a small set of dashboards: a sales leader view (pipeline, forecast, win rate) and a manager view (activity, stuck deals).",
            obj="Dashboard",
        )
        return
    ctx.finding(
        name="Dashboards nobody opens",
        records=("Dashboard", f"(LastViewedDate < LAST_N_DAYS:{UNUSED_DAYS} OR LastViewedDate = null)", "NamespacePrefix = null", "CreatedDate < LAST_N_DAYS:30"),
        recent=False,
        fix="/lightning/o/Dashboard/home",
        score=score,
        affected=n,
        description=f"{n:,} of {total:,} dashboards ({pct(n, total):.0f}%) haven’t been opened in {UNUSED_DAYS}+ days by the connected user. "
        "Salesforce only shares view dates per user, so connect as a leader who uses dashboards for the most accurate picture.",
        why="Dashboards nobody opens don’t drive decisions, and they hide the ones that matter.",
        impact="Leaders miss problems that the right dashboard would show.",
        action="Retire unused dashboards, and subscribe managers to the few that matter so they arrive by email every week.",
        obj="Dashboard",
    )


_MESSY_NAME = re.compile(r"^(copy of|new .*report|untitled|test\b|report\s*\d+$)|\bcopy\b|\(\d+\)$", re.I)
_UNFILED = re.compile(r"unfiled|private|my personal|personal custom", re.I)


def reporting_organization(ctx: Ctx) -> None:
    reports = _reports(ctx)
    unfiled = [r for r in reports if _UNFILED.search(r.get("FolderName") or "")]
    messy = [r for r in reports if _MESSY_NAME.search((r.get("Name") or "").strip())]
    issues = len({r["Id"] for r in unfiled + messy})
    score = rate_score(issues / len(reports), 0.4) if reports else 100
    ctx.metric(
        "Reporting organization issues", issues, "count", "lower-better", score,
        how="We count reports that sit in unfiled or private folders, or have copy/test-style names like “Copy of…”, “Untitled” or “Test”. Each report is counted once.",
        rule="100 when no report has these issues, falling evenly to 0 when 40% of reports do. A problem is raised when the score is below 90.",
        records=("Report", ctx.ids_in([r["Id"] for r in unfiled + messy])),
        recent=False,
        columns=["FolderName", "Name", "LastRunDate", "OwnerId"],
        order="FolderName",
        criteria=[
            ("Records checked", f"{len(reports):,} reports (reports from installed packages aren’t counted)."),
            ("Fields checked", "Report name and folder name"),
            ("Unfiled or private", "The folder name contains “Unfiled”, “Private”, “My Personal” or “Personal Custom”."),
            ("Messy name", "The name starts with “Copy of”, “New … report”, “Untitled” or “Test”, is just “Report” plus a number, contains the word “copy”, or ends with a number in brackets like “(2)”. Upper/lower case is ignored."),
            ("What's counted", f"{issues:,} reports with at least one issue: {len(unfiled):,} in unfiled or private folders and {len(messy):,} with messy names. A report with both is counted once."),
            ("Flagged when", "The score is below 90."),
            ("Records listed", "Every report with an issue, sorted by folder (up to 200 reports)."),
        ],
    )
    parts = []
    if unfiled:
        parts.append(f"{len(unfiled):,} sit in unfiled or private folders")
    if messy:
        examples = ", ".join("“" + str(r.get("Name")) + "”" for r in messy[:3])
        parts.append(f"{len(messy):,} have copy/test-style names (e.g. {examples})")
    ctx.finding(
        name="Disorganised reports",
        records=("Report", ctx.ids_in([r["Id"] for r in unfiled + messy])),
        recent=False,
        fix="/lightning/o/Report/home",
        score=score,
        affected=issues,
        description=f"Of {len(reports):,} reports, " + " and ".join(parts) + ".",
        why="Without clear folders and names, people can’t find trusted reports and build duplicates.",
        impact="Conflicting numbers in meetings and wasted time.",
        action="Set up folders by team or role (e.g. Sales Leadership, Sales Managers, Marketing), agree a naming convention, and move or rename the rest.",
        obj="Report",
        min_score=90,
    )


LEADERSHIP_TOPICS = {
    "Pipeline": r"pipeline|open opp|opportunit(y|ies) by stage",
    "Forecast": r"forecast|commit|bookings",
    "Win rate": r"win.?rate|won|lost|win.?loss|closed",
    "Rep activity": r"activit|calls|tasks|meetings",
    "Lead conversion": r"lead.*(conver|source|funnel)|conversion|mql|sql",
}


def leadership_reporting(ctx: Ctx) -> None:
    _reports(ctx)
    missing = [topic for topic, rx in LEADERSHIP_TOPICS.items() if not _has_report(ctx, rx)]
    ctx.metric(
        "Leadership reporting gaps", len(missing), "count", "lower-better", 100 - 20 * len(missing),
        how="We look at the names of your reports and dashboards to see whether each of 5 key leadership topics is covered: pipeline, forecast, win rate, rep activity and lead conversion. We count the topics with no matching report or dashboard.",
        rule="Starts at 100 and loses 20 points for each missing topic, so 0 when all 5 are missing.",
        criteria=[
            ("Records checked", "The names of all reports and dashboards the connected user can see (excluding installed packages)."),
            ("Pipeline", "A name containing “pipeline”, “open opp” or “opportunities by stage”."),
            ("Forecast", "A name containing “forecast”, “commit” or “bookings”."),
            ("Win rate", "A name containing “win rate”, “won”, “lost”, “win-loss” or “closed”."),
            ("Rep activity", "A name containing “activit…”, “calls”, “tasks” or “meetings”."),
            ("Lead conversion", "A name containing “lead” followed by “conver…”, “source” or “funnel”, or containing “conversion”, “MQL” or “SQL”."),
            ("Matching", "Upper/lower case is ignored. If reports can’t be read at all, every topic is treated as covered."),
            ("What's counted", f"{len(missing)} of 5 topics have no matching report or dashboard" + (f": {', '.join(missing)}." if missing else ".")),
        ],
    )
    if missing:
        _setting(
            ctx,
            "Key leadership reports are missing",
            f"No report or dashboard seems to cover: {', '.join(missing)} (based on report and dashboard names).",
            "Build one trusted report for each missing topic and add them to a leadership dashboard with a weekly subscription.",
            severity="high" if len(missing) >= 3 else "medium",
            obj="Report",
        )


# ---------------------------------------------------------------- area 9: activity, handoffs, deal progress

LOW_ACTIVITY = 5  # tasks/events per rep in 30 days


def sales_activity_gaps(ctx: Ctx) -> None:
    reps = sales_reps(ctx)
    counts = activity_by_owner(ctx, 30)
    low = sorted((counts.get(uid, 0), name) for uid, name in reps.items() if counts.get(uid, 0) < LOW_ACTIVITY)
    low_ids = [uid for uid in reps if counts.get(uid, 0) < LOW_ACTIVITY]
    score = rate_score(len(low) / len(reps), 0.6) if reps else 100
    ctx.metric(
        "Sales activity gaps", len(low), "count", "lower-better", score,
        how=f"Among active people who own open Opportunities or Leads, we count those who logged fewer than {LOW_ACTIVITY} tasks or events in the last 30 days.",
        rule="100 when everyone logs enough activity, falling evenly to 0 when 60% of these people log too little.",
        records=("User", ctx.ids_in(low_ids)),
        recent=False,
        columns=["Name", "Username", "LastLoginDate"],
        order="Name",
        criteria=[
            ("Records checked", f"{len(reps):,} active people who own at least one open Opportunity or unconverted Lead. Queues, bots, integration users and non-sales profiles are left out."),
            ("Activity counted", "Tasks and events they own that were created in the last 30 days."),
            ("Low activity", f"Fewer than {LOW_ACTIVITY} tasks and events combined in 30 days."),
            ("What's counted", f"{len(low):,} of {len(reps):,} people ({pct(len(low), len(reps)):.0f}%) have low activity."),
            ("Records listed", "Every person with low activity, sorted by name (up to 200 people)."),
        ],
    )
    ctx.finding(
        name="Reps with very little logged activity",
        records=("User", ctx.ids_in(low_ids)),
        recent=False,
        score=score,
        affected=len(low),
        description=f"{len(low)} of {len(reps)} people who own open deals or leads logged fewer than {LOW_ACTIVITY} tasks or events in 30 days: "
        + ", ".join(f"{name} ({n})" for n, name in low[:8]) + (" …" if len(low) > 8 else "") + ".",
        why="Managers can’t coach or compare effort when activity isn’t in Salesforce.",
        impact="No early warning when a rep or territory slows down.",
        action="Build an “Activities by rep (last 30 days)” report for managers, and turn on automatic activity capture so emails and meetings log themselves.",
        obj="User",
    )


def opps_without_open_tasks(ctx: Ctx) -> None:
    total = ctx.count("Opportunity", OPEN_OPPS)
    with_task: set[str] = set()
    if total and ctx.has_object("Task"):
        what = [str(r.get("w")) for r in ctx.sf.query("SELECT WhatId w, COUNT(Id) c FROM Task WHERE IsClosed = false AND What.Type = 'Opportunity' GROUP BY WhatId LIMIT 2000").get("records", [])]
        for i in range(0, len(what), 200):
            ids = _ids_in(what[i:i + 200])
            if ids:
                with_task |= {r["Id"] for r in ctx.rows(f"SELECT Id FROM Opportunity WHERE {OPEN_OPPS} AND Id IN ({ids})")}
    n = total - len(with_task)
    score = rate_score(n / total, 0.8) if total else 100
    ctx.metric(
        "Opportunities without open Tasks", n, "count", "lower-better", score,
        how="We count open Opportunities that have no open task linked to them, so nothing is scheduled to move them forward.",
        rule="100 when every open deal has an open task, falling evenly to 0 when 80% have none.",
        records=(("Opportunity", OPEN_OPPS, "Id NOT IN (" + ", ".join(repr(i) for i in sorted(with_task)) + ")") if 0 < len(with_task) <= 300 else ("Opportunity", OPEN_OPPS) if not with_task else None),
        columns=["Name", "StageName", "Amount", "CloseDate", "OwnerId"],
        order="CloseDate",
        criteria=[
            ("Records checked", f"{total:,} open Opportunities"),
            ("Open task", "A task that isn’t completed and is linked to the deal (the task’s Related To is the Opportunity)."),
            ("What's counted", f"{n:,} of {total:,} open deals ({pct(n, total):.0f}%) have no open task; {len(with_task):,} have at least one."),
            ("Records listed", "Every open deal with no open task, soonest close date first."
             if len(with_task) <= 300 else "Not available: too many deals have open tasks to list the rest exactly."),
        ],
    )
    ctx.finding(
        name="Open deals with no open task",
        records=(("Opportunity", OPEN_OPPS, "Id NOT IN (" + ", ".join(repr(i) for i in sorted(with_task)) + ")") if 0 < len(with_task) <= 300 else ("Opportunity", OPEN_OPPS) if not with_task else None),
        score=score,
        affected=n,
        description=f"{n:,} of {total:,} open Opportunities ({pct(n, total):.0f}%) have no open task, so nothing is scheduled to move them forward.",
        why="A deal with no scheduled next action usually stalls.",
        impact="Slower deals and pipeline that quietly goes stale.",
        action="Ask reps to keep at least one open task (with a due date) on every open deal, and give managers a report of deals with none.",
        obj="Opportunity",
        url=ctx.list_url("Opportunity"),
    )


def _history_tracked(ctx: Ctx, obj: str, fld: str) -> bool | None:
    try:
        rows = ctx.setup(
            f"SELECT QualifiedApiName, IsFieldHistoryTracked FROM FieldDefinition WHERE EntityDefinition.QualifiedApiName = '{obj}' AND QualifiedApiName = '{fld}'",
            tooling=False,
        )
    except Unavailable:
        return None
    return bool(rows and rows[0].get("IsFieldHistoryTracked"))


def handoff_visibility(ctx: Ctx) -> None:
    new_opps = ctx.count("Opportunity", "CreatedDate = LAST_N_DAYS:365", recent=False)
    no_source = ctx.count("Opportunity", "CreatedDate = LAST_N_DAYS:365", "LeadSource = null", recent=False) if new_opps and ctx.has_field("Opportunity", "LeadSource") else 0
    missing_pct = pct(no_source, new_opps)
    score = rate_score(no_source / new_opps, 0.5) if new_opps else 100
    status_tracked = _history_tracked(ctx, "Lead", "Status")
    if status_tracked is False:
        score = min(score, 70)
        _setting(
            ctx,
            "Lead Status changes aren’t tracked",
            "Field History Tracking is off for Lead Status, so you can’t see how long leads spend in each step or where marketing-to-sales handoffs stall.",
            "Turn on Field History Tracking for Lead Status, and use the “Leads with Converted Lead Information” report type for the funnel.",
            obj="Lead",
        )
    ctx.metric(
        "Marketing-to-sales handoff visibility", missing_pct, "%", "lower-better", score,
        how="The share of Opportunities created in the last 12 months that have no Lead Source. We also check whether changes to Lead Status are tracked in field history.",
        rule="100 when every new deal has a Lead Source, falling evenly to 0 when 50% have none. If Lead Status changes aren’t tracked, the score is capped at 70.",
        records=("Opportunity", "CreatedDate = LAST_N_DAYS:365", "LeadSource = null"),
        recent=False,
        columns=["Name", "LeadSource", "CreatedDate", "StageName", "Amount", "OwnerId"],
        order="CreatedDate",
        criteria=[
            ("Records checked", f"{new_opps:,} Opportunities created in the last 365 days (open or closed)."),
            ("Field checked", "Lead Source"),
            ("What's counted", f"{no_source:,} of {new_opps:,} new deals ({missing_pct:.0f}%) have an empty Lead Source."),
            ("Lead Status history", "Tracked: changes to Lead Status are recorded." if status_tracked
             else "Not tracked, so the score is capped at 70." if status_tracked is False else "Couldn’t be checked with this user, so it doesn’t affect the score."),
            ("Records listed", "Every new deal with no Lead Source, oldest first."),
        ],
    )
    ctx.finding(
        name="New deals with no Lead Source",
        records=("Opportunity", "CreatedDate = LAST_N_DAYS:365", "LeadSource = null"),
        recent=False,
        score=score,
        affected=no_source,
        description=f"{no_source:,} of {new_opps:,} Opportunities created in the last year ({missing_pct:.0f}%) have no Lead Source, so you can’t tell which channels create pipeline.",
        why="Without a source on each deal, marketing and sales can’t agree on what works.",
        impact="Budget goes to the wrong channels.",
        action="Make Lead Source required on new Opportunities (it carries over from converted Leads), and report pipeline by source monthly.",
        obj="Opportunity",
        url=ctx.list_url("Opportunity"),
    )


def pipeline_progression(ctx: Ctx) -> None:
    total = ctx.count("Opportunity", OPEN_OPPS)
    if not ctx.has_field("Opportunity", "LastStageChangeDate"):
        raise Unavailable("This org can’t report when deals change stage.")
    cond = ("LastStageChangeDate = null", "CreatedDate < LAST_N_DAYS:30")
    n = ctx.count("Opportunity", OPEN_OPPS, *cond) if total else 0
    score = rate_score(n / total, 0.5) if total else 100
    if _history_tracked(ctx, "Opportunity", "StageName") is False and _history_tracked(ctx, "Opportunity", "Amount") is False:
        _setting(
            ctx,
            "Opportunity changes aren’t tracked",
            "Field History Tracking is off for key Opportunity fields, so you can’t see when amounts or stages changed or measure pipeline velocity.",
            "Turn on Field History Tracking for Stage, Amount, and Close Date, and use the “Opportunities with History” report type.",
            severity="low",
            obj="Opportunity",
        )
    ctx.metric(
        "Pipeline progression gaps", n, "count", "lower-better", score,
        how="We count open Opportunities that are more than 30 days old and have never changed stage since they were created.",
        rule="100 when every older open deal has moved stage, falling evenly to 0 when 50% never have.",
        records=("Opportunity", OPEN_OPPS, *cond),
        columns=["Name", "LastStageChangeDate", "CreatedDate", "StageName", "Amount", "CloseDate", "OwnerId"],
        order="CreatedDate",
        criteria=[
            ("Records checked", f"{total:,} open Opportunities"),
            ("Fields checked", "Last Stage Change date and Created date"),
            ("Never progressed", "No stage change has ever been recorded and the deal was created more than 30 days ago."),
            ("What's counted", f"{n:,} of {total:,} open deals ({pct(n, total):.0f}%) never progressed."),
            ("Records listed", "Every open deal that never progressed, oldest first."),
        ],
    )
    if n:
        value = ctx.amount("Opportunity", OPEN_OPPS, *cond)
        ctx.finding(
            name="Deals that never moved past their first stage",
            records=("Opportunity", OPEN_OPPS, *cond),
            value=value,
            score=score,
            affected=n,
            description=f"{n:,} of {total:,} open Opportunities ({pct(n, total):.0f}%) are 30+ days old and have never changed stage{_worth(value)}.",
            why="Deals that never progress inflate the pipeline and hide where the real funnel breaks.",
            impact="Unreliable conversion rates and forecasts.",
            action="Review these deals: move them forward with a clear next step or close them. Track stage-to-stage conversion in a pipeline report.",
            obj="Opportunity",
            url=ctx.list_url("Opportunity"),
        )


# ---------------------------------------------------------------- area 10: regions, stuck deals, lost deals

def stuck_visibility(ctx: Ctx) -> None:
    days = int(ctx.scope.stuck_opportunity_days)
    total = ctx.count("Opportunity", OPEN_OPPS)
    cond = (f"(LastStageChangeDate < LAST_N_DAYS:{days} OR (LastStageChangeDate = null AND CreatedDate < LAST_N_DAYS:{days}))"
            if ctx.has_field("Opportunity", "LastStageChangeDate") else f"LastModifiedDate < LAST_N_DAYS:{days}")
    n = ctx.count("Opportunity", OPEN_OPPS, cond) if total else 0
    ctx.metric(
        "Stuck Opportunities", n, "count", "lower-better", rate_score(n / total, 0.4) if total else 100,
        how=f"We count open Opportunities that haven’t changed stage in {days}+ days (or, if stage-change dates aren’t available, haven’t been edited in {days}+ days).",
        rule="100 when no open deal is stuck, falling evenly to 0 when 40% of open deals are stuck.",
        records=("Opportunity", OPEN_OPPS, cond),
        columns=(["Name", "LastStageChangeDate", "CreatedDate"] if "LastStageChangeDate" in cond else ["Name", "LastModifiedDate"])
        + ["StageName", "Amount", "CloseDate", "OwnerId"],
        order="LastStageChangeDate" if "LastStageChangeDate" in cond else "LastModifiedDate",
        criteria=[
            ("Records checked", f"{total:,} open Opportunities"),
            ("Fields checked", "Last Stage Change date (and Created date for deals that never changed stage)"
             if "LastStageChangeDate" in cond else "Last Modified date (this org doesn’t record stage-change dates)"),
            ("Stuck", f"No stage change in the last {days} days; a deal that never changed stage counts if it was created more than {days} days ago."
             if "LastStageChangeDate" in cond else f"Not edited in the last {days} days."),
            ("Stuck threshold", f"{days} days, from your assessment settings."),
            ("What's counted", f"{n:,} of {total:,} open deals ({pct(n, total):.0f}%) are stuck."),
            ("Records listed", "Every stuck open deal, longest without a change first."),
        ],
    )
    if n and not _has_report(ctx, r"stuck|stale|aging|ageing|idle|no activity|stalled"):
        _setting(
            ctx,
            "No report shows stuck deals",
            f"{n:,} open deals haven’t moved in {days}+ days, but no report or dashboard seems to track stuck or aging deals.",
            "Create a “Stuck deals” report (open, no stage change in X days, sorted by Amount) and add it to the pipeline dashboard.",
            severity="medium",
            obj="Opportunity",
        )


def overdue_visibility(ctx: Ctx) -> None:
    total = ctx.count("Opportunity", OPEN_OPPS)
    n = ctx.count("Opportunity", OPEN_OPPS, "CloseDate < TODAY") if total else 0
    ctx.metric(
        "Overdue deals", n, "count", "lower-better", rate_score(n / total, 0.3) if total else 100,
        how="We count open Opportunities whose Close Date is already in the past.",
        rule="100 when no open deal is overdue, falling evenly to 0 when 30% of open deals are overdue.",
        records=("Opportunity", OPEN_OPPS, "CloseDate < TODAY"),
        columns=["Name", "CloseDate", "StageName", "Amount", "OwnerId"],
        order="CloseDate",
        criteria=[
            ("Records checked", f"{total:,} open Opportunities"),
            ("Field checked", "Close Date"),
            ("Overdue", "The Close Date is before today and the deal is still open."),
            ("What's counted", f"{n:,} of {total:,} open deals ({pct(n, total):.0f}%) are overdue."),
            ("Records listed", "Every overdue open deal, most overdue first."),
        ],
    )
    if n and not _has_report(ctx, r"overdue|past due|close date|slipp"):
        _setting(
            ctx,
            "No report shows overdue deals",
            f"{n:,} open deals are past their close date, but no report or dashboard seems to track overdue or slipping deals.",
            "Create an “Overdue deals” report (open, Close Date before today, grouped by owner) for weekly pipeline reviews.",
            severity="medium",
            obj="Opportunity",
        )


_REGION = re.compile(r"\bregion|territor|\bgeo|country", re.I)


def regional_visibility(ctx: Ctx) -> None:
    def region_field(obj: str) -> str | None:
        try:
            fields = ctx.fields(obj)
        except Unavailable:
            return None
        picks = [f for f in fields.values() if f.get("filterable") and f.get("custom") and (_REGION.search(f["name"]) or _REGION.search(f.get("label") or ""))]
        picks.sort(key=lambda f: f.get("type") != "picklist")  # prefer picklists
        return picks[0]["name"] if picks else None

    opp_field = region_field("Opportunity")
    total = ctx.count("Opportunity", OPEN_OPPS)
    if opp_field:
        missing = ctx.count("Opportunity", OPEN_OPPS, f"{opp_field} = null") if total else 0
        missing_pct = pct(missing, total)
        score = rate_score(missing / total, 0.5) if total else 100
        ctx.metric(
            "Regional performance visibility", missing_pct, "%", "lower-better", score,
            how=f"The share of open Opportunities with no value in your region field ({ctx.fields('Opportunity')[opp_field].get('label') or opp_field}).",
            rule="100 when every open deal has a region, falling evenly to 0 when 50% have none.",
            records=("Opportunity", OPEN_OPPS, f"{opp_field} = null"),
            columns=[opp_field, "Name", "StageName", "Amount", "CloseDate", "OwnerId"],
            order="CloseDate",
            criteria=[
                ("Records checked", f"{total:,} open Opportunities"),
                ("Field checked", f"{ctx.fields('Opportunity')[opp_field].get('label') or opp_field} ({opp_field})"),
                ("How the field was chosen", "A custom, filterable Opportunity field whose name or label mentions region, territory, geo or country. Picklists are preferred."),
                ("What's counted", f"{missing:,} of {total:,} open deals ({missing_pct:.0f}%) have this field empty."),
                ("Records listed", "Every open deal with no region, soonest close date first."),
            ],
        )
        ctx.finding(
            name="Open deals with no region",
            records=("Opportunity", OPEN_OPPS, f"{opp_field} = null"),
            score=score,
            affected=missing,
            description=f"{missing:,} of {total:,} open Opportunities ({missing_pct:.0f}%) have no {ctx.fields('Opportunity')[opp_field].get('label') or opp_field}, so they’re missing from regional reports.",
            why="You can’t compare regions when many deals have no region.",
            impact="Wrong regional targets and coaching in the wrong places.",
            action=f"Fill in {opp_field} (a Flow can copy it from the Account), and make it required.",
            obj="Opportunity",
            url=ctx.list_url("Opportunity"),
        )
        return
    acct_field = region_field("Account")
    ctx.metric(
        "Regional performance visibility", 100.0 if not acct_field else 50.0, "%", "lower-better", 30 if not acct_field else 65,
        how="We looked for a custom region, territory, geo or country field on Opportunities and found none, so we checked Accounts instead. We show 50% if Accounts have such a field, or 100% if neither does.",
        rule="A fixed score: 65 when only Accounts have a region field, 30 when neither Opportunities nor Accounts do.",
        criteria=[
            ("What we looked for", "A custom, filterable field whose name or label mentions region, territory, geo or country."),
            ("On Opportunities", "None found."),
            ("On Accounts", f"Found: {ctx.fields('Account')[acct_field].get('label') or acct_field} ({acct_field}), but it isn’t on deals." if acct_field else "None found."),
            ("What's shown", "50%: deals can only be grouped by region through their Account." if acct_field else "100%: no deal can be reported by region."),
        ],
    )
    _setting(
        ctx,
        "Deals can’t be reported by region",
        "Opportunities have no region or territory field"
        + (f" (Accounts have “{ctx.fields('Account')[acct_field].get('label')}”, but it isn’t on deals)." if acct_field else ", and neither do Accounts."),
        "Add a Region picklist to Opportunity (copied from the Account by a Flow) so pipeline and wins can be compared by region.",
        severity="medium",
        obj="Opportunity",
    )


def closed_lost_trends(ctx: Ctx) -> None:
    fields = ctx.fields("Opportunity")
    reason = next((f["name"] for f in fields.values() if f.get("filterable") and (_LOST_REASON.search(f["name"]) or _LOST_REASON.search(f.get("label") or ""))), None)
    lost_conds = ("IsClosed = true", "IsWon = false", "CloseDate = LAST_N_DAYS:365")
    lost = ctx.count("Opportunity", *lost_conds, recent=False)
    no_reason = lost if reason is None else (ctx.count("Opportunity", *lost_conds, f"{reason} = null", recent=False) if lost else 0)
    missing_pct = pct(no_reason, lost)
    score = 100 if not lost else rate_score(no_reason / lost, 0.5)
    ctx.metric(
        "Closed Lost trends", missing_pct, "%", "lower-better", score,
        how="The share of Opportunities lost in the last 12 months that have no lost reason filled in. If there’s no lost-reason field at all, every lost deal counts as missing a reason.",
        rule="100 when every lost deal has a reason, falling evenly to 0 when 50% have none.",
        records=("Opportunity", *lost_conds, *([f"{reason} = null"] if reason else [])),
        recent=False,
        columns=([reason] if reason else []) + ["Name", "CloseDate", "Amount", "StageName", "OwnerId"],
        order="CloseDate",
        criteria=[
            ("Records checked", f"{lost:,} Opportunities closed as lost in the last 365 days (by Close Date)."),
            ("Field checked", f"{fields[reason].get('label') or reason} ({reason})" if reason else "None: no lost-reason field was found, so every lost deal counts as missing a reason."),
            ("How the field was chosen", "The first filterable Opportunity field whose name or label mentions both “lost” (or “loss”) and “reason”."),
            ("What's counted", f"{no_reason:,} of {lost:,} lost deals ({missing_pct:.0f}%) have no reason."),
            ("Records listed", "Every lost deal from the last year with no reason, oldest close date first."),
        ],
    )
    if lost and reason and no_reason < lost:
        groups = ctx.groups("Opportunity", reason, *lost_conds) if fields[reason].get("groupable") else []
        top = ", ".join(f"{v} ({c})" for v, c in groups[:3])
        if not _has_report(ctx, r"lost|win.?loss|loss reason"):
            _setting(
                ctx,
                "No report analyses why deals are lost",
                f"{lost:,} deals were lost in the last year" + (f" — top reasons: {top}" if top else "") + ", but no report or dashboard seems to analyse losses.",
                "Create a “Lost deals by reason” report (last 12 months, by reason and Amount) and review it monthly with sales and product.",
                severity="medium",
                obj="Opportunity",
            )
    elif lost and no_reason:
        ctx.finding(
            name="Lost deals in the last year have no reason",
            records=("Opportunity", *lost_conds, *([f"{reason} = null"] if reason else [])),
            recent=False,
            score=score,
            affected=no_reason,
            description=f"{no_reason:,} of {lost:,} deals lost in the last 12 months ({missing_pct:.0f}%) have no recorded reason, so loss trends can’t be analysed.",
            why="Patterns in why you lose (price, competitor, timing) are only visible if every loss is recorded.",
            impact="The same losses keep happening.",
            action="Require a lost reason on Closed Lost deals and backfill the biggest recent losses.",
            obj="Opportunity",
            url=ctx.list_url("Opportunity"),
        )


# ---------------------------------------------------------------- area 11: win-loss, competitors, products, upsell

def win_loss_gaps(ctx: Ctx) -> None:
    closed = ("IsClosed = true", "CloseDate = LAST_N_DAYS:365")
    won = ctx.count("Opportunity", *closed, "IsWon = true", recent=False)
    lost = ctx.count("Opportunity", *closed, "IsWon = false", recent=False)
    gaps = []
    if not _has_report(ctx, r"win.?rate|win.?loss|won.*lost|lost.*won"):
        gaps.append("no win-rate or win-loss report")
    reason = any(_LOST_REASON.search(f["name"]) or _LOST_REASON.search(f.get("label") or "") for f in ctx.fields("Opportunity").values())
    if not reason:
        gaps.append("no field for why deals are lost")
    ctx.metric(
        "Win-loss reporting gaps", len(gaps), "count", "lower-better", [100, 60, 30][len(gaps)],
        how="We check two things: whether any report or dashboard name suggests a win-rate or win-loss report, and whether Opportunities have a field for why deals are lost. We count how many are missing.",
        rule="100 when both are in place, 60 when one is missing, and 30 when both are missing.",
        criteria=[
            ("Win-loss report", "Found." if "no win-rate or win-loss report" not in gaps
             else "Missing: no report or dashboard name mentions “win rate”, “win-loss”, or “won” and “lost” together."),
            ("Lost-reason field", "Found." if reason else "Missing: no Opportunity field name or label mentions both “lost” (or “loss”) and “reason”."),
            ("What's counted", f"{len(gaps)} of 2 pieces are missing."),
            ("For context", f"Last 365 days: {won:,} won and {lost:,} lost, a {pct(won, won + lost):.0f}% win rate." if won + lost else ""),
        ],
    )
    if gaps:
        rate = f" Your win rate over the last year is {pct(won, won + lost):.0f}% ({won:,} won, {lost:,} lost)." if won + lost else ""
        _setting(
            ctx,
            "Win-loss can’t be analysed",
            f"Win-loss analysis is limited: {', and '.join(gaps)}.{rate}",
            "Create a win-rate report (won vs. lost by quarter, owner, and source) and capture a reason on every lost deal.",
            severity="medium",
            obj="Opportunity",
        )


def competitor_tracking(ctx: Ctx) -> None:
    closed = ("IsClosed = true", "CloseDate = LAST_N_DAYS:365")
    total = ctx.count("Opportunity", *closed, recent=False)
    custom = next((f["name"] for f in ctx.fields("Opportunity").values() if f.get("filterable") and re.search(r"competit", f["name"] + " " + (f.get("label") or ""), re.I)), None)
    tracked = 0
    if total and custom:
        tracked = total - ctx.count("Opportunity", *closed, f"{custom} = null", recent=False)
    elif total and ctx.has_object("OpportunityCompetitor"):
        tracked = ctx.count("Opportunity", *closed, "Id IN (SELECT OpportunityId FROM OpportunityCompetitor)", recent=False)
    missing = total - tracked
    score = rate_score(missing / total, 1.0) if total else 100
    ctx.metric(
        "Competitor tracking gaps", pct(missing, total), "%", "lower-better", score,
        how="The share of Opportunities closed in the last 12 months with no competitor recorded, either in a competitor field on the deal or in the Competitors related list.",
        rule="100 when every closed deal has a competitor, falling evenly to 0 when none do. A problem is raised when the score is below 80.",
        records=("Opportunity", *closed, *([f"{custom} = null"] if custom else ["Id NOT IN (SELECT OpportunityId FROM OpportunityCompetitor)"] if ctx.has_object("OpportunityCompetitor") else [])),
        recent=False,
        columns=([custom] if custom else []) + ["Name", "IsWon", "CloseDate", "Amount", "OwnerId"],
        order="CloseDate",
        criteria=[
            ("Records checked", f"{total:,} Opportunities closed (won or lost) in the last 365 days."),
            ("Where competitors are recorded", f"A competitor field on the deal: {custom}." if custom
             else "The Competitors related list on each deal." if ctx.has_object("OpportunityCompetitor")
             else "Nowhere: there’s no competitor field and the Competitors list can’t be read, so every deal counts as missing."),
            ("How the field was chosen", "The first filterable Opportunity field whose name or label contains “competit”." if custom else ""),
            ("What's counted", f"{missing:,} of {total:,} closed deals ({pct(missing, total):.0f}%) have no competitor; {tracked:,} have one."),
            ("Flagged when", "The score is below 80."),
            ("Records listed", "Every closed deal from the last year with no competitor, oldest close date first."),
        ],
    )
    ctx.finding(
        name="Competitors aren’t recorded on deals",
        records=("Opportunity", *closed, *([f"{custom} = null"] if custom else ["Id NOT IN (SELECT OpportunityId FROM OpportunityCompetitor)"] if ctx.has_object("OpportunityCompetitor") else [])),
        recent=False,
        score=score,
        affected=missing,
        description=f"{missing:,} of {total:,} deals closed in the last year ({pct(missing, total):.0f}%) have no competitor recorded, so you can’t see who you win and lose against.",
        why="Knowing your win rate against each competitor shows where to focus product, pricing, and battle cards.",
        impact="Repeated losses to the same competitor without a plan to fix them.",
        action="Add the Competitors related list (or a Competitor picklist) to Opportunities and ask reps to fill it in before closing.",
        obj="Opportunity",
        min_score=80,
    )


def product_visibility(ctx: Ctx) -> None:
    total = ctx.count("Opportunity", OPEN_OPPS, "Amount > 0") if ctx.has_field("Opportunity", "Amount") else 0
    if not ctx.has_field("Opportunity", "HasOpportunityLineItem", None):
        raise Unavailable("Products aren’t enabled on Opportunities.")
    n = ctx.count("Opportunity", OPEN_OPPS, "Amount > 0", "HasOpportunityLineItem = false") if total else 0
    score = rate_score(n / total, 0.8) if total else 100
    ctx.metric(
        "Product visibility issues", n, "count", "lower-better", score,
        how="We count open Opportunities that have an Amount but no products added.",
        rule="100 when every open deal with an Amount has products, falling evenly to 0 when 80% have none.",
        records=("Opportunity", OPEN_OPPS, "Amount > 0", "HasOpportunityLineItem = false"),
        columns=["Name", "HasOpportunityLineItem", "Amount", "StageName", "CloseDate", "OwnerId"],
        order="-Amount",
        criteria=[
            ("Records checked", f"{total:,} open Opportunities with an Amount above 0."),
            ("Field checked", "Has Products (whether any product line has been added)."),
            ("What's counted", f"{n:,} of {total:,} deals ({pct(n, total):.0f}%) have no products."),
            ("Records listed", "Every open deal with an Amount but no products, biggest Amount first."),
        ],
    )
    if n:
        value = ctx.amount("Opportunity", OPEN_OPPS, "Amount > 0", "HasOpportunityLineItem = false")
        ctx.finding(
            name="Open deals with no products",
            records=("Opportunity", OPEN_OPPS, "Amount > 0", "HasOpportunityLineItem = false"),
            value=value,
            score=score,
            affected=n,
            description=f"{n:,} of {total:,} open Opportunities with an Amount ({pct(n, total):.0f}%) have no products{_worth(value)}, so pipeline can’t be broken down by product.",
            why="Without products on deals you can’t forecast by product line or spot what sells.",
            impact="A “blind” forecast and no data for product or upsell decisions.",
            action="Ask reps to add products instead of typing the Amount, and consider a validation rule requiring at least one product before Closed Won.",
            obj="Opportunity",
            url=ctx.list_url("Opportunity"),
        )


def upsell_visibility(ctx: Ctx) -> None:
    if not ctx.has_object("OpportunityLineItem"):
        raise Unavailable("Opportunity products can’t be read.")
    try:
        recs = ctx.sf.query(
            "SELECT Opportunity.AccountId a, Product2.Family f, COUNT(Id) c FROM OpportunityLineItem "
            "WHERE Opportunity.IsWon = true AND Opportunity.CloseDate = LAST_N_DAYS:730 GROUP BY Opportunity.AccountId, Product2.Family LIMIT 2000"
        ).get("records", [])
    except Exception as exc:  # noqa: BLE001 — some orgs can't group by product family
        raise Unavailable(f"Product families couldn’t be read ({exc}).") from None
    families = {r.get("f") for r in recs if r.get("f")}
    accounts: dict[str, set] = {}
    for r in recs:
        if r.get("a"):
            accounts.setdefault(r["a"], set()).add(r.get("f"))
    if not accounts:
        ctx.metric(
            "Upsell opportunity visibility", 0, "count", "lower-better", 30,
            how="We look at the products on deals won in the last two years, grouped by customer and Product Family. None of those won deals have products, so there’s nothing to count.",
            rule="A fixed score of 30, because what customers bought can’t be seen without products on won deals.",
            criteria=[
                ("Records checked", "Product lines on Opportunities won in the last 730 days (two years), grouped by Account and Product Family."),
                ("What we found", "No won deal in that period has any products."),
                ("What's counted", "Nothing can be counted, so the measure shows 0."),
            ],
        )
        _setting(
            ctx,
            "No product data on won deals",
            "Won deals in the last two years have no products, so you can’t see what each customer bought or what to offer next.",
            "Add products to deals (at least when they close), with a Product Family, so a “customers by product” report shows upsell gaps.",
            severity="medium",
            obj="Opportunity",
        )
        return
    if len(families) < 2:
        ctx.metric(
            "Upsell opportunity visibility", 0, "count", "lower-better", 60,
            how=f"We look at the products on deals won in the last two years, grouped by customer and Product Family. {len(accounts):,} customers bought products, but fewer than 2 product families are used, so “bought A but not B” can’t be measured.",
            rule="A fixed score of 60, because upsell gaps can’t be seen until products are grouped into families.",
            criteria=[
                ("Records checked", f"Product lines on Opportunities won in the last 730 days (two years): {len(accounts):,} customers bought products."),
                ("Field checked", "Product Family on each product"),
                ("What we found", f"{len(families)} product famil{'y is' if len(families) == 1 else 'ies are'} used; at least 2 are needed to spot “bought A but not B”."),
                ("What's counted", "Nothing can be counted, so the measure shows 0."),
            ],
        )
        _setting(
            ctx,
            "Products have no families",
            f"{len(accounts):,} customers bought products, but products aren’t grouped into families, so “bought A but not B” (white space) can’t be reported.",
            "Set a Product Family on each product (e.g. Software, Services, Support) to make cross-sell and upsell gaps visible.",
            severity="low",
            obj="Product2",
        )
        return
    single = [a for a, fams in accounts.items() if len(fams - {None}) == 1]
    ctx.metric(
        "Upsell opportunity visibility", len(single), "count", "lower-better", 100,
        how=f"Of the {len(accounts):,} customers with products on deals won in the last two years, we count those who bought from only one of your {len(families)} product families. These are likely upsell candidates.",
        rule="A fixed score of 100: being able to see these customers is the goal, so the count is an opportunity, not a problem.",
        records=("Account", ctx.ids_in(single)),
        recent=False,
        columns=["Name", "Type", "Industry", "OwnerId"],
        order="Name",
        criteria=[
            ("Records checked", f"Product lines on Opportunities won in the last 730 days (two years): {len(accounts):,} customers across {len(families)} product families."),
            ("Field checked", "Product Family on each product bought"),
            ("One product line", "Every product the customer bought in that period belongs to the same Product Family (products with no family are ignored)."),
            ("What's counted", f"{len(single):,} of {len(accounts):,} customers ({pct(len(single), len(accounts)):.0f}%) bought from only one family."),
            ("Data limit", "Reads up to 2,000 customer and product-family combinations."),
            ("Records listed", "Every one-family customer, sorted by name (up to 200 Accounts)."),
        ],
    )
    if single:
        ctx.findings.append(FindingDraft(
            area_id=ctx.area_id,
            name="Customers who bought only one product line",
            records_object="Account",
            records_where=ctx.ids_in(single),
            severity="low",
            affected_records=len(single),
            description=f"{len(single):,} of {len(accounts):,} customers from the last two years bought from only one of your {len(families)} product families — likely upsell candidates.",
            why_it_matters="Selling more to existing customers is usually faster and cheaper than finding new ones.",
            business_impact="Untapped revenue from your current customer base.",
            recommended_action="Build a “customers by product family” report, share the list with account managers, and plan a cross-sell campaign.",
            sample_records_url=ctx.list_url("Account"),
            object_name="Account",
        ))


AREAS = {
    "area-8": [report_usage, unused_reports, unused_dashboards, reporting_organization, leadership_reporting],
    "area-9": [sales_activity_gaps, opps_without_open_tasks, handoff_visibility, pipeline_progression],
    "area-10": [stuck_visibility, overdue_visibility, regional_visibility, closed_lost_trends],
    "area-11": [win_loss_gaps, competitor_tracking, product_visibility, upsell_visibility],
}

STEP_LABELS = {
    report_usage: "Measuring how much each report and dashboard is used",
    unused_reports: "Finding reports nobody runs",
    unused_dashboards: "Finding dashboards nobody opens",
    reporting_organization: "Checking report folders and names",
    leadership_reporting: "Checking leadership reports",
    sales_activity_gaps: "Checking rep activity over 30 days",
    opps_without_open_tasks: "Finding deals with no open task",
    handoff_visibility: "Checking marketing-to-sales handoffs",
    pipeline_progression: "Checking pipeline progression",
    stuck_visibility: "Checking visibility of stuck deals",
    overdue_visibility: "Checking visibility of overdue deals",
    regional_visibility: "Checking regional reporting",
    closed_lost_trends: "Checking lost-deal trends",
    win_loss_gaps: "Checking win-loss reporting",
    competitor_tracking: "Checking competitor tracking",
    product_visibility: "Checking products on deals",
    upsell_visibility: "Looking for upsell opportunities",
}
