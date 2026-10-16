"""Category 3 — Reporting & Dashboards (areas 8 to 11).

Based on the Aquarient RevenueOps Consultant Guide v1.0. Indicator labels match
src/config/categories.ts exactly. Everything is read-only SOQL; a few checks look
at report and dashboard names to see whether key topics are covered at all.
"""
import re

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

def unused_reports(ctx: Ctx) -> None:
    _reports(ctx)
    total = ctx.count("Report", "NamespacePrefix = null", "CreatedDate < LAST_N_DAYS:30", recent=False)
    stale = (f"(LastRunDate < LAST_N_DAYS:{UNUSED_DAYS} OR LastRunDate = null)", "NamespacePrefix = null", "CreatedDate < LAST_N_DAYS:30")
    n = ctx.count("Report", *stale, recent=False) if total else 0
    ctx.totals["Report"] = total
    score = rate_score(n / total, 0.8) if total else 100
    ctx.metric("Unused reports", n, "count", "lower-better", score)
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
    ctx.metric("Unused dashboards", n, "count", "lower-better", score)
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
    ctx.metric("Reporting organization issues", issues, "count", "lower-better", score)
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
    ctx.metric("Leadership reporting gaps", len(missing), "count", "lower-better", 100 - 20 * len(missing))
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
    ctx.metric("Sales activity gaps", len(low), "count", "lower-better", score)
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
    ctx.metric("Opportunities without open Tasks", n, "count", "lower-better", score)
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
    if _history_tracked(ctx, "Lead", "Status") is False:
        score = min(score, 70)
        _setting(
            ctx,
            "Lead Status changes aren’t tracked",
            "Field History Tracking is off for Lead Status, so you can’t see how long leads spend in each step or where marketing-to-sales handoffs stall.",
            "Turn on Field History Tracking for Lead Status, and use the “Leads with Converted Lead Information” report type for the funnel.",
            obj="Lead",
        )
    ctx.metric("Marketing-to-sales handoff visibility", missing_pct, "%", "lower-better", score)
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
    ctx.metric("Pipeline progression gaps", n, "count", "lower-better", score)
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
    ctx.metric("Stuck Opportunities", n, "count", "lower-better", rate_score(n / total, 0.4) if total else 100)
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
    ctx.metric("Overdue deals", n, "count", "lower-better", rate_score(n / total, 0.3) if total else 100)
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
        ctx.metric("Regional performance visibility", missing_pct, "%", "lower-better", score)
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
    ctx.metric("Regional performance visibility", 100.0 if not acct_field else 50.0, "%", "lower-better", 30 if not acct_field else 65)
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
    ctx.metric("Closed Lost trends", missing_pct, "%", "lower-better", score)
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
    ctx.metric("Win-loss reporting gaps", len(gaps), "count", "lower-better", [100, 60, 30][len(gaps)])
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
    ctx.metric("Competitor tracking gaps", pct(missing, total), "%", "lower-better", score)
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
    ctx.metric("Product visibility issues", n, "count", "lower-better", score)
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
        ctx.metric("Upsell opportunity visibility", 0, "count", "lower-better", 30)
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
        ctx.metric("Upsell opportunity visibility", 0, "count", "lower-better", 60)
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
    ctx.metric("Upsell opportunity visibility", len(single), "count", "lower-better", 100)
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
    "area-8": [unused_reports, unused_dashboards, reporting_organization, leadership_reporting],
    "area-9": [sales_activity_gaps, opps_without_open_tasks, handoff_visibility, pipeline_progression],
    "area-10": [stuck_visibility, overdue_visibility, regional_visibility, closed_lost_trends],
    "area-11": [win_loss_gaps, competitor_tracking, product_visibility, upsell_visibility],
}

STEP_LABELS = {
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
