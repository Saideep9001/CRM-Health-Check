"""Deeper checks that look at outcomes, not just configuration.

- Empty fields weighted by what depends on them (area 2): a nearly-empty field matters more when
  reports, flows or code rely on it.
- Automation health (area 7): legacy Process Builders / Workflow Rules, objects automated by several
  tools at once, and flow interviews stuck for days.
- Report trust (area 8): reports filtering on retired picklist values or nearly-empty fields, reports that
  no longer run, and dashboards that run as people who have left.
- Forecast integrity (area 10): stages mapped to the wrong forecast category, and open deals counted
  as closed in the forecast.
- Sync health (area 20): integrations that stopped writing data, duplicates created by integrations,
  and failing background jobs, rolled into one 0–100 score.

All read-only. Setup reads are skipped with a note when the user can't view setup.
"""
import re
from datetime import datetime, timezone

from ..salesforce.errors import SalesforceAuthExpired, SalesforceError
from .core import DEFAULT_OBJECTS, Ctx, FindingDraft, Unavailable, pct, rate_score
from .integrations import INTEGRATION_USER

CORE = DEFAULT_OBJECTS


def _days_ago(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return None
    return max(0, (datetime.now(timezone.utc) - dt).days)


def _setting(ctx: Ctx, name: str, description: str, why: str, impact: str, action: str, severity: str,
             affected: int = 0, obj: str | None = None, fix: str | None = None) -> None:
    ctx.findings.append(FindingDraft(
        area_id=ctx.area_id, name=name, severity=severity,  # type: ignore[arg-type]
        affected_records=affected, description=description, why_it_matters=why, business_impact=impact,
        recommended_action=action, object_name=obj, fix_url=ctx.setup_url(fix) if fix else None,
    ))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


# ---------------------------------------------------------------- area 2: empty fields others depend on

DEPENDENT_TYPES = {"Report": "report", "Flow": "flow", "ApexClass": "Apex class", "ApexTrigger": "Apex trigger",
                   "ValidationRule": "validation rule", "WorkflowRule": "workflow rule", "EmailTemplate": "email template"}
NEARLY_EMPTY = 0.2


def empty_fields_that_matter(ctx: Ctx) -> None:
    objs = [o for o in ctx.selected(*CORE) if ctx.has_object(o)]
    ids = ctx.setup("SELECT Id, DeveloperName, TableEnumOrId, NamespacePrefix FROM CustomField WHERE TableEnumOrId IN ("
                    + ", ".join(f"'{o}'" for o in objs) + ")")
    field_id = {(r.get("TableEnumOrId"), f"{r.get('DeveloperName')}__c"): r["Id"] for r in ids if not r.get("NamespacePrefix")}
    empty: list[tuple[str, str, float, str]] = []  # (object, field, fill share, field id)
    for obj in objs:
        fields = ctx.fields(obj)
        names = [n for (o, n) in field_id if o == obj and n in fields and fields[n].get("filterable")
                 and fields[n].get("type") not in ("boolean", "textarea") and not fields[n].get("calculated")]
        total = ctx.count(obj, recent=False) if names else 0
        if total < 20:
            continue
        for name, filled in ctx.filled_counts(obj, names, recent=False).items():
            if filled / total < NEARLY_EMPTY:
                empty.append((obj, name, filled / total, field_id[(obj, name)]))
    deps: dict[str, dict[str, int]] = {}
    for i in range(0, len(empty), 100):
        chunk = ", ".join(f"'{e[3]}'" for e in empty[i:i + 100])
        for r in ctx.setup("SELECT MetadataComponentType, MetadataComponentName, RefMetadataComponentId FROM MetadataComponentDependency "
                           f"WHERE RefMetadataComponentId IN ({chunk})"):
            t = r.get("MetadataComponentType")
            if t in DEPENDENT_TYPES:
                d = deps.setdefault(r.get("RefMetadataComponentId"), {})
                d[t] = d.get(t, 0) + 1
    matter = sorted(((e, deps[e[3]]) for e in empty if deps.get(e[3])), key=lambda x: (-sum(x[1].values()), x[0][2]))
    score = rate_score(len(matter) / max(len(empty), 1), 0.5) if empty else 100
    ctx.metric(
        "Empty fields others depend on", len(matter), "count", "lower-better", score,
        how=f"Custom fields on Accounts, Contacts, Leads and Opportunities that are filled on fewer than {NEARLY_EMPTY:.0%} of all records "
        f"({len(empty)} found), and that a report, flow, Apex code, validation rule, workflow rule or email template still uses.",
        rule="Scores 100 when none of the nearly empty fields are relied on, falling evenly to 0 when half of them are.",
        criteria=[
            ("Fields checked", f"Custom fields built in your org (not from installed packages) on {', '.join(ctx.label(o) for o in objs) or 'no objects'}, "
             "across all records. Checkboxes, long text and formula fields are left out, and so are objects with fewer than 20 records."),
            ("Nearly empty", f"Filled on fewer than {NEARLY_EMPTY:.0%} of records: {len(empty)} fields."),
            ("Relied on", "At least one report, flow, Apex class, Apex trigger, validation rule, workflow rule or email template uses the field, "
             "according to Salesforce’s list of what depends on what."),
            ("What's counted", f"{len(matter)} of the {len(empty)} nearly empty fields are relied on"
             + (": " + ", ".join(f"{o}.{n} ({share:.0%} filled)" for (o, n, share, _), _ in matter[:5]) + (" …" if len(matter) > 5 else "") if matter else "") + "."),
            ("Flagged when", "Any nearly empty field is relied on."),
        ],
    )
    if not matter:
        return
    lines = [f"{o}.{n} ({share:.0%} filled) — used by " + ", ".join(_plural(c, DEPENDENT_TYPES[t]) for t, c in d.items())
             for (o, n, share, _), d in matter[:8]]
    _setting(
        ctx, "Nearly empty fields that reports and automation rely on",
        f"{len(matter)} custom fields are filled on less than {NEARLY_EMPTY:.0%} of records, yet reports, flows or code depend on them: "
        + "; ".join(lines) + (" …" if len(matter) > 8 else "") + ".",
        "A report grouped by an empty field, or a flow that branches on one, quietly gives wrong answers — and nobody can tell from the output.",
        "Reports and automations that look fine but are built on missing data.",
        "Fix these fields first: make them required at the right stage, backfill the most important records, or change the reports and flows that rely on them.",
        "high" if score < 40 else "medium", affected=len(matter),
        fix="/lightning/setup/ObjectManager/home",
    )


# ---------------------------------------------------------------- area 7: automation health

def automation_health(ctx: Ctx) -> None:
    flows = ctx.setup("SELECT ApiName, Label, ProcessType, TriggerType, TriggerObjectOrEventLabel, NamespacePrefix FROM FlowDefinitionView WHERE IsActive = true", tooling=False)
    flows = [f for f in flows if not f.get("NamespacePrefix")]  # packaged automation can't be changed by the org
    triggers = ctx.setup("SELECT Name, TableEnumOrId FROM ApexTrigger WHERE Status = 'Active' AND NamespacePrefix = null")
    try:
        rules = ctx.setup("SELECT Id, Name, TableEnumOrId FROM WorkflowRule WHERE NamespacePrefix = null")
    except Unavailable:
        rules = []
    label_to_obj = {ctx.label(o, plural=False): o for o in (*CORE, "Case", "Task", "Event", "Quote", "Order", "Contract", "Campaign")}

    tools: dict[str, dict[str, int]] = {}

    def add(obj: str | None, tool: str) -> None:
        if obj:
            tools.setdefault(obj, {})[tool] = tools.setdefault(obj, {}).get(tool, 0) + 1

    builders = [f for f in flows if f.get("ProcessType") == "Workflow"]
    for f in flows:
        obj = label_to_obj.get(f.get("TriggerObjectOrEventLabel") or "", f.get("TriggerObjectOrEventLabel"))
        if f.get("ProcessType") == "Workflow":
            add(obj, "Process Builder")
        elif str(f.get("TriggerType") or "").startswith("Record"):
            add(obj, "record-triggered flow")
    for t in triggers:
        add(t.get("TableEnumOrId"), "Apex trigger")
    for r in rules:
        add(r.get("TableEnumOrId"), "workflow rule")

    legacy = len(builders) + len(rules)
    ctx.metric(
        "Legacy automation to migrate", legacy, "count", "lower-better", max(0.0, 100 - 4 * legacy),
        how=f"Active Process Builders ({len(builders)}) plus Workflow Rules ({len(rules)}) built in your org, which Salesforce has retired in favour of Flow. Installed packages are left out.",
        rule="Starts at 100 and loses 4 points for each one, reaching 0 at 25.",
        criteria=[
            ("What we inspected", "Active flows of the Process Builder type, and every Workflow Rule (Salesforce doesn’t say through this API "
             "which workflow rules are active, so all are counted)."),
            ("Left out", "Automation from installed packages, which your org can’t change."),
            ("What's counted", f"{_plural(len(builders), 'Process Builder')} + {_plural(len(rules), 'workflow rule')} = {legacy}."),
            ("Flagged when", "There is at least one."),
        ],
    )
    if legacy:
        _setting(
            ctx, "Process Builders and Workflow Rules to move to Flow",
            f"{_plural(len(builders), 'active Process Builder')} and {_plural(len(rules), 'workflow rule')} still exist"
            + (" (Salesforce doesn’t report which workflow rules are active through this API)" if rules else "") + ". "
            + (f"Process Builders: {', '.join((b.get('Label') or b.get('ApiName') or '') for b in builders[:6])}." if builders else ""),
            "Salesforce has retired Process Builder and Workflow Rules in favour of Flow; they get no fixes or new features and are harder to debug.",
            "Automation that’s harder to maintain, slower record saves, and a growing migration backlog.",
            "Use Setup → Migrate to Flow to convert them, starting with the objects that have the most automation, and test each one in a sandbox.",
            "high" if legacy >= 15 else "medium" if legacy >= 5 else "low", affected=legacy, fix="/lightning/setup/MigrateToFlowTool/home",
        )

    crowded = {o: t for o, t in tools.items() if len(t) >= 2 or t.get("record-triggered flow", 0) >= 5}
    ctx.metric(
        "Overlapping automation", len(crowded), "count", "lower-better", max(0.0, 100 - 20 * len(crowded)),
        how="Objects automated by two or more kinds of tool at once (record-triggered flows, Process Builders, Apex triggers, workflow rules), "
        "or by five or more record-triggered flows.",
        rule="Starts at 100 and loses 20 points for each such object, reaching 0 at 5.",
        criteria=[
            ("What we inspected", "Every active record-triggered flow, Process Builder, Apex trigger and workflow rule built in your org, "
             "grouped by the object it runs on. Installed packages are left out."),
            ("Counts as overlapping", "An object automated by two or more of those kinds of tool, or by five or more record-triggered flows."),
            ("What's counted", (f"{_plural(len(crowded), 'object')}: " + "; ".join(
                f"{o} ({', '.join(_plural(n, k) for k, n in t.items())})" for o, t in sorted(crowded.items(), key=lambda kv: -sum(kv[1].values()))[:6])
                + (" …" if len(crowded) > 6 else "")) if crowded else f"None of the {len(tools)} automated objects overlap."),
            ("Flagged when", "There is at least one."),
        ],
    )
    if crowded:
        parts = [f"{o}: " + ", ".join(_plural(n, k) for k, n in t.items()) for o, t in sorted(crowded.items(), key=lambda kv: -sum(kv[1].values()))]
        _setting(
            ctx, "Objects automated by several tools at once",
            f"{_plural(len(crowded), 'object')} are automated by more than one tool (or by many flows), so the order things run in is hard to predict: "
            + "; ".join(parts[:6]) + ".",
            "When triggers, flows, Process Builders and workflow rules all fire on the same save, they can overwrite each other, loop, or hit limits.",
            "Records saved with the wrong values, intermittent errors for users, and slow saves.",
            "Pick one tool per object (usually Flow, plus Apex only where needed), consolidate into one before-save and one after-save flow, and set the trigger order.",
            "medium" if len(crowded) >= 2 else "low", affected=len(crowded), fix="/lightning/setup/Flows/home",
        )

    if ctx.has_object("FlowInterview"):
        stuck = ctx.count("FlowInterview", "CreatedDate < LAST_N_DAYS:7", recent=False)
        ctx.metric(
            "Stuck or failing automations", stuck, "count", "lower-better", rate_score(min(stuck, 100) / 100, 1.0),
            how="Flow interviews (running copies of a flow) that have been paused or waiting for more than 7 days.",
            rule="Starts at 100 and loses 1 point for each stuck flow, reaching 0 at 100. A problem is raised for any stuck flow.",
            records=("FlowInterview", "CreatedDate < LAST_N_DAYS:7"), recent=False,
            columns=["InterviewLabel", "InterviewStatus", "CurrentElement", "PauseLabel", "CreatedDate"],
            order="CreatedDate",
            criteria=[
                ("Records checked", "Flow interviews that are paused or waiting (Salesforce doesn’t keep finished ones)."),
                ("Counts as stuck", "Started more than 7 days ago and still waiting."),
                ("What's counted", f"{_plural(stuck, 'stuck flow interview')}. For the score, anything above 100 counts as 100."),
                ("Flagged when", "There is at least one."),
                ("Records listed", "Every stuck flow interview, oldest first."),
            ],
        )
        if stuck:
            ctx.finding(
                name="Flows stuck waiting for more than a week",
                obj=None, records=("FlowInterview", "CreatedDate < LAST_N_DAYS:7"), recent=False,
                score=rate_score(min(stuck, 100) / 100, 1.0), affected=stuck, min_score=101,
                description=f"{_plural(stuck, 'flow interview')} have been paused or waiting for over 7 days.",
                why="Paused flows often mean a step failed or is waiting on something that will never happen — the work it was meant to do isn’t getting done.",
                impact="Follow-ups, approvals or updates that silently never happen.",
                action="Open Setup → Paused and Failed Flow Interviews, resume or delete stuck ones, and fix the step they’re waiting on.",
                fix="/lightning/setup/Pausedflows/home",
            )


# ---------------------------------------------------------------- area 8: report trust

MAX_REPORTS = 40
_BROKEN = re.compile(r"column|field|no longer|doesn.t exist|does not exist|deleted|invalid report type|isn.t valid|is not valid", re.I)
_NO_ACCESS = re.compile(r"privilege|permission|access|not supported|unsupported", re.I)


def _report_field(ctx: Ctx, column: str) -> tuple[str, dict] | None:
    """Map a report filter column like "Opportunity.Region__c" to (object, field describe)."""
    if "." not in column:
        return None
    obj_part, field_part = column.rsplit(".", 1)
    obj_part = obj_part.split(".")[-1]
    for obj in (*CORE, "Case", "Campaign"):
        if obj.lower() == obj_part.lower() and ctx.has_object(obj):
            fields = ctx.fields(obj)
            f = next((v for k, v in fields.items() if k.lower() == field_part.lower()), None)
            return (obj, f) if f else None
    return None


def report_trust(ctx: Ctx) -> None:
    if not ctx.has_object("Report"):
        raise Unavailable("Reports can’t be read with this user.")
    reports = ctx.rows("SELECT Id, Name FROM Report WHERE NamespacePrefix = null AND LastRunDate = LAST_N_DAYS:90 ORDER BY LastRunDate DESC", MAX_REPORTS)
    ver = ctx.sf.settings.sf_api_version
    problems: list[str] = []
    broken: list[str] = []
    fill_cache: dict[tuple[str, str], float] = {}
    for r in reports:
        try:
            meta = (ctx.sf.get(f"/services/data/{ver}/analytics/reports/{r['Id']}/describe").get("reportMetadata") or {})
        except SalesforceAuthExpired:
            raise
        except SalesforceError as exc:
            # Only a missing field/column/report type means the report is broken; permission errors just mean we can't look.
            if _BROKEN.search(str(exc)) and not _NO_ACCESS.search(str(exc)):
                broken.append(r.get("Name") or r["Id"])
            continue
        issues = []
        for flt in meta.get("reportFilters") or []:
            mapped = _report_field(ctx, str(flt.get("column") or ""))
            if not mapped:
                continue
            obj, f = mapped
            if f.get("type") in ("picklist", "multipicklist") and flt.get("value"):
                active = {str(p.get("value")).lower() for p in f.get("picklistValues") or [] if p.get("active")}
                retired = [v.strip() for v in str(flt["value"]).split(",") if v.strip() and v.strip().lower() not in active]
                if active and retired:
                    issues.append(f"filters {f['name']} on retired value(s) {', '.join(retired[:3])}")
            if f.get("custom") and f.get("filterable"):
                key = (obj, f["name"])
                if key not in fill_cache:
                    total = ctx.count(obj, recent=False)
                    filled = ctx.filled_counts(obj, [f["name"]], recent=False).get(f["name"], total)
                    fill_cache[key] = filled / total if total else 1.0
                if fill_cache[key] < 0.05:
                    issues.append(f"filters on {f['name']}, which is filled on {fill_cache[key]:.0%} of {obj} records")
        if issues:
            problems.append(f"“{r.get('Name')}” " + "; ".join(issues[:2]))

    dash_bad: list[str] = []
    if ctx.has_object("Dashboard"):
        try:
            dash_bad = [d.get("Title") or d["Id"] for d in ctx.rows(
                "SELECT Id, Title FROM Dashboard WHERE NamespacePrefix = null AND Type = 'SpecifiedUser' AND RunningUser.IsActive = false", 500)]
        except SalesforceAuthExpired:
            raise
        except SalesforceError:
            dash_bad = []

    issues_n = len(problems) + len(broken) + len(dash_bad)
    checked = len(reports) + len(dash_bad)
    score = rate_score(issues_n / max(checked, 1), 0.3) if checked else 100
    ctx.metric(
        "Report trust issues", issues_n, "count", "lower-better", score,
        how=f"Of the {len(reports)} most recently run reports (run in the last 90 days, up to {MAX_REPORTS}), those that filter on a retired picklist value "
        "or on a custom field filled on fewer than 5% of records, or that error when opened; plus dashboards that run as a deactivated user.",
        rule="Scores 100 when nothing is wrong, falling evenly to 0 when 30% of the reports and dashboards checked have a problem.",
        criteria=[
            ("Reports checked", f"The {len(reports)} most recently run reports built in your org (run in the last 90 days, up to {MAX_REPORTS}). "
             "Reports from installed packages are left out."),
            ("Retired values", "A filter on a picklist uses a value that is no longer active on that field."),
            ("Empty fields", "A filter uses a custom field that is filled on fewer than 5% of that object’s records."),
            ("Broken reports", "Opening the report fails because a field, column or report type no longer exists. "
             "Errors caused by our user’s permissions are not counted."),
            ("Dashboards", "Dashboards set to run as a specific person who has been deactivated."),
            ("What's counted", f"{_plural(len(problems), 'report')} with risky filters, {_plural(len(broken), 'broken report')} and "
             f"{_plural(len(dash_bad), 'dashboard')} running as a leaver = {issues_n}, out of {checked} checked."),
            ("Flagged when", "Any one of these is found."),
        ],
    )
    if problems:
        _setting(ctx, "Reports filtering on retired values or empty fields",
                 f"{_plural(len(problems), 'recently used report')} can’t be trusted as they stand: " + "; ".join(problems[:5]) + (" …" if len(problems) > 5 else "") + ".",
                 "A filter on a retired picklist value or a field nobody fills in silently drops records, so the totals look plausible but are wrong.",
                 "Decisions made on numbers that leave out part of the business.",
                 "Update each filter to current picklist values, or fix the field’s data before relying on the report.",
                 "medium", affected=len(problems), obj="Report", fix="/lightning/o/Report/home")
    if broken:
        _setting(ctx, "Reports that no longer run",
                 f"{_plural(len(broken), 'recently used report')} returned an error when opened: {', '.join(broken[:6])}.",
                 "Usually a field or object they use was deleted or permissions changed — the people who rely on them get errors or blank results.",
                 "Missing information in meetings and lost trust in Salesforce reporting.",
                 "Open each report, remove or replace the missing fields, and save; delete the ones nobody needs.",
                 "medium", affected=len(broken), obj="Report", fix="/lightning/o/Report/home")
    if dash_bad:
        _setting(ctx, "Dashboards running as people who have left",
                 f"{_plural(len(dash_bad), 'dashboard')} run as an inactive user: {', '.join(dash_bad[:6])}.",
                 "A dashboard shows data as its running user sees it; when that user is deactivated it stops refreshing or shows stale numbers.",
                 "Leaders looking at out-of-date numbers without knowing it.",
                 "Change each dashboard’s running user to an active person (or ‘the dashboard viewer’), and include this in your leaver checklist.",
                 "medium", affected=len(dash_bad), obj="Dashboard", fix="/lightning/o/Dashboard/home")


# ---------------------------------------------------------------- area 10: forecast integrity

def forecast_setup(ctx: Ctx) -> None:
    stages = ctx.setup("SELECT MasterLabel, IsClosed, IsWon, ForecastCategoryName, DefaultProbability FROM OpportunityStage WHERE IsActive = true", tooling=False)
    wrong = []
    for s in stages:
        cat, name = s.get("ForecastCategoryName"), s.get("MasterLabel")
        if s.get("IsWon") and cat != "Closed":
            wrong.append(f"won stage “{name}” is in “{cat}”")
        elif s.get("IsClosed") and not s.get("IsWon") and cat not in ("Omitted", None):
            wrong.append(f"lost stage “{name}” is in “{cat}”")
        elif not s.get("IsClosed") and cat == "Closed":
            wrong.append(f"open stage “{name}” is in “Closed”")
        elif not s.get("IsClosed") and (s.get("DefaultProbability") or 0) >= 100:
            wrong.append(f"open stage “{name}” has a 100% probability")
    misfiled = 0
    if ctx.has_field("Opportunity", "ForecastCategoryName"):
        misfiled = ctx.count("Opportunity", "IsClosed = false", "ForecastCategoryName = 'Closed'", recent=False)
    issues = len(wrong) + (1 if misfiled else 0)
    ctx.metric(
        "Forecast setup issues", issues, "count", "lower-better", max(0.0, 100 - 25 * issues),
        how="Active sales stages that feed the forecast wrongly (a won stage not in “Closed”, a lost stage not in “Omitted”, an open stage in “Closed” "
        "or with a 100% probability). Open Opportunities marked “Closed” in the forecast add one more issue.",
        rule="Starts at 100 and loses 25 points for each issue, reaching 0 at 4.",
        records=("Opportunity", "IsClosed = false", "ForecastCategoryName = 'Closed'") if misfiled else None, recent=False,
        columns=["Name", "StageName", "ForecastCategoryName", "Probability", "Amount", "CloseDate", "OwnerId"],
        order="CloseDate",
        criteria=[
            ("Stages checked", f"{len(stages)} active Opportunity stages"),
            ("Wrong mapping", "A won stage not in the “Closed” forecast category; a lost stage in anything other than “Omitted”; "
             "an open stage in “Closed”; or an open stage with a 100% probability."),
            ("Open deals", "Open Opportunities (any date) whose forecast category is “Closed”. However many there are, they count as one issue."),
            ("What's counted", f"{_plural(len(wrong), 'stage')} mapped wrongly"
             + (": " + "; ".join(wrong[:4]) + (" …" if len(wrong) > 4 else "") if wrong else "")
             + f", plus {_plural(misfiled, 'open deal')} marked “Closed” = {issues}."),
            ("Flagged when", "Any stage is mapped wrongly, or any open deal is marked “Closed”."),
            ("Records listed", "Open Opportunities marked “Closed” in the forecast, sorted by close date." if misfiled else ""),
        ],
    )
    if wrong:
        _setting(ctx, "Sales stages mapped to the wrong forecast category",
                 "Some stages feed the forecast incorrectly: " + "; ".join(wrong[:6]) + ".",
                 "Forecast categories decide which deals count as Commit, Best Case or Closed — a wrong mapping skews every forecast.",
                 "Forecasts that over- or under-state what will close.",
                 "In Setup → Object Manager → Opportunity → Stage picklist, set each stage’s forecast category and probability to match your process.",
                 "high" if any("open stage" in w and "Closed" in w for w in wrong) else "medium", affected=len(wrong), obj="Opportunity",
                 fix="/lightning/setup/ObjectManager/Opportunity/FieldsAndRelationships/StageName/view")
    if misfiled:
        value = ctx.amount("Opportunity", "IsClosed = false", "ForecastCategoryName = 'Closed'")
        ctx.finding(
            name="Open deals counted as closed in the forecast",
            obj="Opportunity", records=("Opportunity", "IsClosed = false", "ForecastCategoryName = 'Closed'"), recent=False,
            score=40, affected=misfiled, value=value,
            description=f"{_plural(misfiled, 'open deal')} have the forecast category “Closed”" + (f", worth {value:,.0f}" if value else "") + ", so the forecast treats them as already won.",
            why="Revenue that hasn’t been won yet shows up as closed, inflating the forecast.",
            impact="An over-stated forecast and surprises at quarter end.",
            action="Move these deals to the right forecast category (Pipeline, Best Case or Commit) and stop reps from overriding it to Closed.",
        )


# ---------------------------------------------------------------- area 20: sync health score

def sync_health(ctx: Ctx) -> None:
    users = ctx.rows("SELECT Id, Name, Profile.Name FROM User WHERE IsActive = true LIMIT 2000", 2000)
    integ = {u["Id"]: u.get("Name") or u["Id"] for u in users
             if INTEGRATION_USER.search(f"{u.get('Name')} {(u.get('Profile') or {}).get('Name') or ''}")}
    if not integ:
        raise Unavailable("No integration users were found, so there’s no sync to measure.")
    ids = ", ".join(f"'{i}'" for i in list(integ)[:100])
    last: dict[str, int] = {}
    writes: dict[str, int] = {}
    for obj in CORE:
        if not ctx.has_object(obj):
            continue
        for r in ctx.sf.query(f"SELECT LastModifiedById u, MAX(LastModifiedDate) m, COUNT(Id) c FROM {obj} "
                              f"WHERE LastModifiedById IN ({ids}) AND LastModifiedDate = LAST_N_DAYS:90 GROUP BY LastModifiedById").get("records", []):
            uid, d = r.get("u"), _days_ago(r.get("m"))
            writes[uid] = writes.get(uid, 0) + int(r.get("c") or 0)
            if d is not None:
                last[uid] = min(last.get(uid, d), d)
    stalled = [f"{integ[u]} (last wrote {last[u]} days ago)" for u in integ if writes.get(u, 0) >= 20 and last.get(u, 0) > 7]

    created = dupes = 0
    for obj in ("Contact", "Lead"):
        if not ctx.has_field(obj, "Email"):
            continue
        created += ctx.count(obj, f"CreatedById IN ({ids})", "CreatedDate = LAST_N_DAYS:90", recent=False)
        for r in ctx.sf.query(f"SELECT Email v, COUNT(Id) c FROM {obj} WHERE CreatedById IN ({ids}) AND CreatedDate = LAST_N_DAYS:90 "
                              "AND Email != null GROUP BY Email HAVING COUNT(Id) > 1 LIMIT 2000").get("records", []):
            dupes += int(r.get("c") or 0) - 1
    dup_rate = dupes / created if created else 0.0

    fail_rate = 0.0
    if ctx.has_object("AsyncApexJob"):
        total = ctx.count("AsyncApexJob", "CreatedDate = LAST_N_DAYS:7", recent=False)
        failed = ctx.count("AsyncApexJob", "Status = 'Failed'", "CreatedDate = LAST_N_DAYS:7", recent=False) if total else 0
        fail_rate = failed / total if total else 0.0

    score = max(0.0, 100 - (40 if stalled else 0) - min(30.0, 100 * dup_rate) - min(30.0, 150 * fail_rate))
    ctx.metric(
        "Sync health score", score, "%", "higher-better", score,
        how=f"How cleanly your {_plural(len(integ), 'integration user')} keep data in sync: whether any stopped writing to Accounts, Contacts, Leads or Opportunities, "
        "how many Contacts and Leads they created in the last 90 days share an email, and how many background jobs failed in the last 7 days.",
        rule="Starts at 100. Loses 40 points if any integration that wrote at least 20 records in 90 days has written nothing for over 7 days; "
        "loses 1 point per 1% of duplicates it created (up to 30); and loses 1.5 points per 1% of failed background jobs (up to 30).",
        criteria=[
            ("Integration users", f"{_plural(len(integ), 'active user')} whose name or profile mentions integration, API, sync, connector "
             "or a known tool (MuleSoft, Boomi, HubSpot, Pardot, Marketo, Zapier, Workato)."),
            ("Stopped syncing", "An integration user that changed at least 20 Accounts, Contacts, Leads or Opportunities in the last 90 days, "
             "but none in the last 7 days" + (": " + ", ".join(stalled[:4]) if stalled else ". None found") + "."),
            ("Duplicates created", "Contacts and Leads created by integration users in the last 90 days that share an email with another one they created: "
             f"{dupes:,} extra copies out of {created:,} ({pct(dupes, created):.0f}%)."),
            ("Failed jobs", f"Background (Apex) jobs from the last 7 days with status Failed: {fail_rate:.0%}."),
            ("Flagged when", "The score is below 80."),
        ],
    )
    parts = []
    if stalled:
        parts.append("integrations that stopped writing data: " + ", ".join(stalled[:4]))
    if dupes:
        parts.append(f"{dupes} duplicate contacts/leads created by integration users in 90 days ({pct(dupes, created):.0f}% of what they created)")
    if fail_rate:
        parts.append(f"{fail_rate:.0%} of background jobs failed in the last 7 days")
    if score < 80 and parts:
        _setting(ctx, "Integrations aren’t syncing cleanly",
                 f"Sync health score {score:.0f}/100 across {_plural(len(integ), 'integration user')}: " + "; ".join(parts) + ".",
                 "A sync that stops or creates duplicates goes unnoticed for weeks — until someone acts on missing or doubled data.",
                 "Out-of-date records, duplicate customers, and connected systems that disagree with Salesforce.",
                 "Check the stalled integrations’ logs and credentials first, add duplicate matching on the integration’s upsert key (email or external ID), and set up failure alerts.",
                 "high" if stalled else "medium", affected=len(stalled) + dupes, obj="User", fix="/lightning/setup/ConnectedApplication/home")


STEP_LABELS = {
    empty_fields_that_matter: "Finding empty fields that reports and flows rely on",
    automation_health: "Checking automation health",
    report_trust: "Checking whether key reports can be trusted",
    forecast_setup: "Checking forecast setup",
    sync_health: "Scoring integration sync health",
}
