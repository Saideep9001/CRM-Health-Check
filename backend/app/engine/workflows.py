"""Category 2 — Workflows & Automation (areas 3 to 7).

Based on the Aquarient RevenueOps Consultant Guide v1.0. Indicator labels match
src/config/categories.ts exactly. Record checks use fixed read-only SOQL; setup
checks (validation rules, Path, flows…) read the Tooling API and are skipped with
a note when the connected user can't view setup.
"""
import re
from datetime import datetime, timezone

from .core import Ctx, FindingDraft, Unavailable, pct, rate_score

OPEN_LEADS = "IsConverted = false"
OPEN_OPPS = "IsClosed = false"


def _money(v: float | None) -> str:
    return f"{v:,.0f}" if v else ""


def _worth(v: float | None) -> str:
    return f", worth {_money(v)} in total" if v else ""


def _owners(rows: list[tuple[str, int, float]], n: int = 3) -> str:
    return ", ".join(f"{name} ({c})" for name, c, _ in rows[:n])


def _days_since(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return None
    return max(0, (datetime.now(timezone.utc) - dt).days)


# Where in Salesforce each setup problem is fixed.
SETTING_FIX = {
    'No active Lead Assignment Rule': '/lightning/setup/LeadRules/home',
    'No automation or escalation on Leads': '/lightning/setup/Flows/home',
    'No rules guide how deals move through stages': '/lightning/setup/ObjectManager/Opportunity/ValidationRules/view',
    'Contacts can’t be related to multiple Accounts': '/lightning/setup/AccountSettings/home',
    'Sales Path isn’t turned on for Opportunities': '/lightning/setup/PathAssistantSetupHome/home',
    'Sales stages without guidance': '/lightning/setup/PathAssistantSetupHome/home',
    'No field for why deals are lost': '/lightning/setup/ObjectManager/Opportunity/FieldsAndRelationships/view',
    'No leads from the website': '/lightning/setup/LeadWebtoleads/home',
    'Few email templates for the sales team': '/lightning/o/EmailTemplate/home',
    'Key objects with no validation rules': '/lightning/setup/ObjectManager/home',
    'Unclear validation error messages': '/lightning/setup/ObjectManager/home',
    'Important fields that are optional and often empty': '/lightning/setup/ObjectManager/home',
    'Crowded or fragmented page layouts': '/lightning/setup/ObjectManager/home',
}


def _setting(ctx: Ctx, name: str, description: str, action: str, severity: str = "medium", obj: str | None = None) -> None:
    """A problem with how Salesforce is set up (not tied to a count of records)."""
    ctx.findings.append(FindingDraft(
        area_id=ctx.area_id,
        name=name,
        severity=severity,  # type: ignore[arg-type]
        affected_records=0,
        description=description,
        why_it_matters="The right settings make good habits automatic, so problems don’t keep coming back.",
        business_impact="More manual work for reps and managers, and problems that return after every cleanup.",
        recommended_action=action,
        object_name=obj,
        fix_url=ctx.setup_url(SETTING_FIX[name]) if name in SETTING_FIX else None,
    ))


# ---------------------------------------------------------------- area 3: lead assignment, escalation, progression

def unassigned_leads(ctx: Ctx) -> None:
    total = ctx.count("Lead", OPEN_LEADS)
    ctx.totals["Lead"] = total
    n = ctx.count("Lead", OPEN_LEADS, "Owner.Type = 'Queue'") if total else 0
    score = rate_score(n / total, 0.2) if total else 100
    ctx.metric("Unassigned Leads", n, "count", "lower-better", score)
    if n:
        oldest = ctx.rows("SELECT Name, Company, CreatedDate FROM Lead WHERE IsConverted = false AND Owner.Type = 'Queue' ORDER BY CreatedDate ASC LIMIT 3", 3)
        waits = [f"{r.get('Name')} ({d} days)" for r in oldest if (d := _days_since(r.get("CreatedDate"))) is not None]
        ctx.finding(
            name="Leads waiting in a queue",
            records=("Lead", OPEN_LEADS, "Owner.Type = 'Queue'"),
            fix="/lightning/setup/LeadRules/home",
            score=score,
            affected=n,
            description=f"{n:,} of {total:,} open Leads ({pct(n, total):.0f}%) are still owned by a queue, not a person."
            + (f" Longest waiting: {', '.join(waits)}." if waits else ""),
            why="Leads cool off fast. Nobody feels responsible for a lead that sits in a queue.",
            impact="Slower first contact and lost deals to faster competitors.",
            action="Turn on an active Lead Assignment Rule that routes leads to people (round-robin or by territory), and alert managers when a lead sits in a queue for more than a few hours.",
            obj="Lead",
            url=ctx.list_url("Lead"),
        )


def stale_leads(ctx: Ctx) -> None:
    days = int(ctx.scope.stale_lead_days)
    total = ctx.count("Lead", OPEN_LEADS)
    conds = (OPEN_LEADS, f"LastModifiedDate < LAST_N_DAYS:{days}", f"(LastActivityDate = null OR LastActivityDate < LAST_N_DAYS:{days})")
    n = ctx.count("Lead", *conds) if total else 0
    score = rate_score(n / total, 0.5) if total else 100
    ctx.metric("Stale Leads", n, "count", "lower-better", score)
    owners = ctx.by_owner("Lead", *conds) if n else []
    ctx.finding(
        name="Stale open Leads",
        records=("Lead", *conds),
        score=score,
        affected=n,
        description=f"{n:,} of {total:,} open Leads ({pct(n, total):.0f}%) haven’t been touched in {days}+ days."
        + (f" Most belong to: {_owners(owners)}." if owners else ""),
        why="Old, untouched leads hide the ones worth working and make the pipeline look bigger than it is.",
        impact="Missed follow-ups and misleading lead reports.",
        action="Ask owners to work or disqualify these leads. Add a reminder or escalation (e.g. a scheduled Flow) for leads untouched after a few days.",
        obj="Lead",
        url=ctx.list_url("Lead"),
    )


def overdue_opportunities(ctx: Ctx) -> None:
    total = ctx.count("Opportunity", OPEN_OPPS)
    ctx.totals["Opportunity"] = total
    n = ctx.count("Opportunity", OPEN_OPPS, "CloseDate < TODAY") if total else 0
    score = rate_score(n / total, 0.3) if total else 100
    ctx.metric("Overdue Opportunities", n, "count", "lower-better", score)
    if n:
        value = ctx.amount("Opportunity", OPEN_OPPS, "CloseDate < TODAY")
        owners = ctx.by_owner("Opportunity", OPEN_OPPS, "CloseDate < TODAY")
        ctx.finding(
            name="Open deals past their close date",
            records=("Opportunity", OPEN_OPPS, "CloseDate < TODAY"),
            value=value,
            score=score,
            affected=n,
            description=f"{n:,} of {total:,} open Opportunities ({pct(n, total):.0f}%) have a close date in the past{_worth(value)}."
            + (f" Most belong to: {_owners(owners)}." if owners else ""),
            why="Past-due close dates make the forecast wrong and hide deals that are really stalled or lost.",
            impact="Forecasts you can’t trust and pipeline reviews that miss real risk.",
            action="Have owners update each deal’s close date and stage, or close it as lost. Review overdue deals in every pipeline meeting.",
            obj="Opportunity",
            url=ctx.list_url("Opportunity"),
        )


def escalation_processes(ctx: Ctx) -> None:
    missing: list[str] = []
    rules = ctx.setup("SELECT Id, Name, Active FROM AssignmentRule WHERE SobjectType = 'Lead'", tooling=False)
    if not any(r.get("Active") for r in rules):
        missing.append("lead assignment rule")
        _setting(
            ctx,
            "No active Lead Assignment Rule",
            "New leads aren’t routed to anyone automatically" + (f" ({len(rules)} rule(s) exist but none is active)." if rules else "."),
            "In Setup → Lead Assignment Rules, create and activate a rule that sends leads to the right person or queue.",
            severity="high",
            obj="Lead",
        )
    try:
        flows = ctx.setup("SELECT ApiName, Label, ProcessType, TriggerType, TriggerObjectOrEventLabel FROM FlowDefinitionView WHERE IsActive = true", tooling=False)
        on_lead = [f for f in flows if (f.get("TriggerObjectOrEventLabel") or "") in ("Lead", "Leads")]
        if not on_lead:
            missing.append("lead automation")
            _setting(
                ctx,
                "No automation or escalation on Leads",
                "There are no active Flows or Processes that run on Leads, so nothing reminds or escalates when a lead isn’t worked.",
                "Add a record-triggered Flow with a scheduled path that alerts the owner (and then their manager) when a new lead isn’t touched in time.",
                obj="Lead",
            )
    except Unavailable:
        pass  # older orgs or limited access: assignment rules alone still tell us something
    ctx.metric("Missing escalation processes", len(missing), "count", "lower-better", [100, 50, 15][min(len(missing), 2)])


def sales_progression(ctx: Ctx) -> None:
    total = ctx.count("Opportunity", OPEN_OPPS)
    no_amount = ctx.count("Opportunity", OPEN_OPPS, "Amount = null") if total and ctx.has_field("Opportunity", "Amount") else 0
    score = rate_score(no_amount / total, 0.3) if total else 100
    try:
        rules = ctx.setup("SELECT Id, ValidationName, Active, ErrorMessage FROM ValidationRule WHERE EntityDefinition.QualifiedApiName = 'Opportunity'")
        if not any(r.get("Active") for r in rules):
            score = min(score, 70)
            _setting(
                ctx,
                "No rules guide how deals move through stages",
                "Opportunities have no active validation rules, so deals can jump to late stages without key details like Amount or Next Step.",
                "Add validation rules for stage gates, e.g. “Amount is required from Proposal onward”, with clear, friendly error messages.",
                obj="Opportunity",
            )
    except Unavailable:
        pass
    ctx.metric("Sales progression issues", no_amount, "count", "lower-better", score)
    ctx.finding(
        name="Open deals with no Amount",
        records=("Opportunity", OPEN_OPPS, "Amount = null"),
        score=rate_score(no_amount / total, 0.3) if total else 100,
        affected=no_amount,
        description=f"{no_amount:,} of {total:,} open Opportunities ({pct(no_amount, total):.0f}%) have no Amount.",
        why="Deals without an amount can’t be forecast or prioritised.",
        impact="Pipeline value is understated and managers can’t see what matters most.",
        action="Fill in amounts (or add products), and require Amount once a deal reaches a qualified stage.",
        obj="Opportunity",
        url=ctx.list_url("Opportunity"),
    )


# ---------------------------------------------------------------- area 4: account hierarchies & contact relationships

def account_relationships(ctx: Ctx) -> None:
    total = ctx.total("Account")
    empty = ctx.count(
        "Account",
        "Id NOT IN (SELECT AccountId FROM Contact WHERE AccountId != null)",
        "Id NOT IN (SELECT AccountId FROM Opportunity WHERE AccountId != null)",
    ) if total else 0
    score = rate_score(empty / total, 0.5) if total else 100
    ctx.metric("Missing Account relationships", empty, "count", "lower-better", score)
    ctx.finding(
        name="Accounts with no people and no deals",
        records=("Account", "Id NOT IN (SELECT AccountId FROM Contact WHERE AccountId != null)", "Id NOT IN (SELECT AccountId FROM Opportunity WHERE AccountId != null)"),
        score=score,
        affected=empty,
        description=f"{empty:,} of {total:,} Accounts ({pct(empty, total):.0f}%) have no Contacts and no Opportunities.",
        why="Empty accounts clutter searches and reports, and often turn out to be duplicates or old imports.",
        impact="Wasted time and an inflated account count.",
        action="Review these Accounts: add the key people, link them to their parent company, merge duplicates, or archive them.",
        obj="Account",
        url=ctx.list_url("Account"),
    )


def orphaned_contacts(ctx: Ctx) -> None:
    total = ctx.total("Contact")
    n = ctx.count("Contact", "AccountId = null") if total else 0
    score = rate_score(n / total, 0.2) if total else 100
    ctx.metric("Orphaned Contacts", n, "count", "lower-better", score)
    ctx.finding(
        name="Contacts not linked to any Account",
        records=("Contact", "AccountId = null"),
        score=score,
        affected=n,
        description=f"{n:,} of {total:,} Contacts ({pct(n, total):.0f}%) aren’t linked to an Account.",
        why="Unlinked contacts are invisible on the company record and are private to their owner by default.",
        impact="Lost relationships and an incomplete view of each customer.",
        action="Link each Contact to its company. Consider making Account required for new Contacts.",
        obj="Contact",
        url=ctx.list_url("Contact"),
    )


def missing_contact_roles(ctx: Ctx) -> None:
    total = ctx.count("Opportunity", OPEN_OPPS)
    cond = "Id NOT IN (SELECT OpportunityId FROM OpportunityContactRole)"
    n = ctx.count("Opportunity", OPEN_OPPS, cond) if total else 0
    score = rate_score(n / total, 0.6) if total else 100
    ctx.metric("Missing Contact Roles", n, "count", "lower-better", score)
    if n:
        value = ctx.amount("Opportunity", OPEN_OPPS, cond)
        owners = ctx.by_owner("Opportunity", OPEN_OPPS, cond)
        ctx.finding(
            name="Open deals with no contact roles",
            records=("Opportunity", OPEN_OPPS, cond),
            value=value,
            score=score,
            affected=n,
            description=f"{n:,} of {total:,} open Opportunities ({pct(n, total):.0f}%) have no contact roles{_worth(value)}."
            + (f" Most belong to: {_owners(owners)}." if owners else ""),
            why="Without contact roles you don’t know who decides, who influences, and who signs.",
            impact="Single-threaded deals that stall when one contact goes quiet, and no data on buying groups.",
            action="Add the decision maker and key influencers to each open deal. Make the Contact Roles list prominent on the Opportunity page.",
            obj="Opportunity",
            url=ctx.list_url("Opportunity"),
        )


def account_hierarchy(ctx: Ctx) -> None:
    total = ctx.total("Account")
    issues = 0
    if total and ctx.has_field("Account", "ParentId"):
        with_parent = ctx.count("Account", "ParentId != null")
        if total >= 50 and with_parent == 0:
            issues += 1
            _setting(
                ctx,
                "Account hierarchies aren’t used",
                f"None of your {total:,} Accounts has a Parent Account, so related companies and divisions aren’t connected.",
                "Link subsidiaries and divisions to their parent Account, and add the View Hierarchy button to the Account page.",
                severity="low",
                obj="Account",
            )
    if not ctx.has_object("AccountContactRelation"):
        issues += 1
        _setting(
            ctx,
            "Contacts can’t be related to multiple Accounts",
            "The “Contacts to Multiple Accounts” feature is off, so a person who works with several companies can only be linked to one.",
            "In Setup → Account Settings, turn on “Allow users to relate a contact to multiple accounts” and add the Related Accounts list to Contacts.",
            severity="low",
            obj="Contact",
        )
    ctx.metric("Account hierarchy issues", issues, "count", "lower-better", [100, 75, 50][issues])


# ---------------------------------------------------------------- area 5: sales path, playbooks, feedback loops

def stuck_opportunities(ctx: Ctx) -> None:
    days = int(ctx.scope.stuck_opportunity_days)
    total = ctx.count("Opportunity", OPEN_OPPS)
    if ctx.has_field("Opportunity", "LastStageChangeDate"):
        cond = f"(LastStageChangeDate < LAST_N_DAYS:{days} OR (LastStageChangeDate = null AND CreatedDate < LAST_N_DAYS:{days}))"
        how = f"haven’t changed stage in {days}+ days"
    else:
        cond = f"LastModifiedDate < LAST_N_DAYS:{days}"
        how = f"haven’t been updated in {days}+ days"
    n = ctx.count("Opportunity", OPEN_OPPS, cond) if total else 0
    score = rate_score(n / total, 0.4) if total else 100
    ctx.metric("Stuck Opportunities", n, "count", "lower-better", score)
    if n:
        value = ctx.amount("Opportunity", OPEN_OPPS, cond)
        amount = ", Amount" if ctx.has_field("Opportunity", "Amount") else ""
        order = "Amount DESC NULLS LAST" if amount else "CreatedDate ASC"
        top = ctx.rows(f"SELECT Name, StageName{amount} FROM Opportunity WHERE {OPEN_OPPS} AND {cond} ORDER BY {order} LIMIT 3", 3)
        biggest = ", ".join(f"“{r.get('Name')}” ({r.get('StageName')}{', ' + _money(r.get('Amount')) if r.get('Amount') else ''})" for r in top)
        ctx.finding(
            name="Stuck deals",
            records=("Opportunity", OPEN_OPPS, cond),
            value=value,
            score=score,
            affected=n,
            description=f"{n:,} of {total:,} open Opportunities ({pct(n, total):.0f}%) {how}{_worth(value)}." + (f" Biggest: {biggest}." if biggest else ""),
            why="Deals that sit still rarely close. They also make the pipeline look healthier than it is.",
            impact="Wasted forecast attention and revenue that never arrives.",
            action="Review stuck deals with each owner: set a clear next step and date, or close them as lost. Add a weekly stuck-deal report to pipeline reviews.",
            obj="Opportunity",
            url=ctx.list_url("Opportunity"),
        )


def missing_next_steps(ctx: Ctx) -> None:
    total = ctx.count("Opportunity", OPEN_OPPS)
    if not ctx.has_field("Opportunity", "NextStep"):
        raise Unavailable("Opportunities have no Next Step field.")
    n = ctx.count("Opportunity", OPEN_OPPS, "NextStep = null") if total else 0
    score = rate_score(n / total, 0.6) if total else 100
    ctx.metric("Missing Next Steps", n, "count", "lower-better", score)
    owners = ctx.by_owner("Opportunity", OPEN_OPPS, "NextStep = null") if n else []
    ctx.finding(
        name="Open deals with no next step",
        records=("Opportunity", OPEN_OPPS, "NextStep = null"),
        score=score,
        affected=n,
        description=f"{n:,} of {total:,} open Opportunities ({pct(n, total):.0f}%) have no Next Step."
        + (f" Most belong to: {_owners(owners)}." if owners else ""),
        why="A deal without a next step is a deal without a plan. Managers can’t coach what they can’t see.",
        impact="Slower deals and weaker pipeline reviews.",
        action="Ask reps to keep Next Step current (what happens next, and when). Show it on the Opportunity page and in pipeline list views.",
        obj="Opportunity",
        url=ctx.list_url("Opportunity"),
    )


_LOST_REASON = re.compile(r"(lost|loss).*(reason)|reason.*(lost|loss)", re.I)


def closed_lost_reasons(ctx: Ctx) -> None:
    fields = ctx.fields("Opportunity")
    reason = next(
        (f["name"] for f in fields.values() if f.get("filterable") and (_LOST_REASON.search(f["name"]) or _LOST_REASON.search(f.get("label") or ""))),
        None,
    )
    lost_conds = ("IsClosed = true", "IsWon = false", "CloseDate = LAST_N_DAYS:90")
    lost = ctx.count("Opportunity", *lost_conds)
    if reason is None:
        ctx.metric("Missing Closed Lost reasons", lost, "count", "lower-better", 40 if lost else 70)
        _setting(
            ctx,
            "No field for why deals are lost",
            f"Opportunities have no “Closed Lost Reason” field, so the reasons behind {lost:,} lost deals in the last 90 days weren’t captured.",
            "Add a required picklist (e.g. Price, Competitor, No decision, Timing) that must be filled in when a deal is Closed Lost.",
            severity="high" if lost else "medium",
            obj="Opportunity",
        )
        return
    n = ctx.count("Opportunity", *lost_conds, f"{reason} = null") if lost else 0
    score = rate_score(n / lost, 0.5) if lost else 100
    ctx.metric("Missing Closed Lost reasons", n, "count", "lower-better", score)
    ctx.finding(
        name="Lost deals with no reason",
        records=("Opportunity", *lost_conds, f"{reason} = null"),
        fix="/lightning/setup/ObjectManager/Opportunity/ValidationRules/view",
        score=score,
        affected=n,
        description=f"{n:,} of {lost:,} deals lost in the last 90 days ({pct(n, lost):.0f}%) have no {fields[reason].get('label') or reason}.",
        why="You can’t fix why you lose if you don’t record it.",
        impact="Repeat losses to the same competitors or objections, with no data to act on.",
        action=f"Make {fields[reason].get('label') or reason} required when a deal is Closed Lost (a validation rule), and review the reasons monthly.",
        obj="Opportunity",
        url=ctx.list_url("Opportunity"),
    )


def stage_guidance(ctx: Ctx) -> None:
    stages = [s for s in ctx.setup("SELECT Id, MasterLabel, ApiName, IsActive, IsClosed FROM OpportunityStage WHERE IsActive = true", tooling=False) if not s.get("IsClosed")]
    paths = [p for p in ctx.setup("SELECT Id, MasterLabel, SobjectType, IsActive FROM PathAssistant") if p.get("SobjectType") == "Opportunity" and p.get("IsActive")]
    if not paths:
        ctx.metric("Sales stage guidance gaps", len(stages), "count", "lower-better", 30 if stages else 100)
        if stages:
            _setting(
                ctx,
                "Sales Path isn’t turned on for Opportunities",
                f"Reps get no on-screen guidance for your {len(stages)} open sales stages.",
                "Set up Path for Opportunities: add key fields and “Guidance for Success” (what to do, what to ask, templates) for each stage.",
                obj="Opportunity",
            )
        return
    # Step names look like "X123_<stage id>_<record type id|null>_Opportunity_StageName"; the 2nd part is the OpportunityStage Id.
    steps = ctx.setup("SELECT DeveloperName, Info FROM PathAssistantStepInfo")
    guided = {
        parts[1][:15]
        for st in steps
        if (parts := str(st.get("DeveloperName") or "").split("_")) and len(parts) >= 5
        and parts[-2] == "Opportunity" and parts[-1] == "StageName"
        and re.sub(r"<[^>]+>|&nbsp;|\s", "", st.get("Info") or "")
    }
    gaps = [s.get("MasterLabel") or s.get("ApiName") for s in stages if str(s.get("Id") or "")[:15] not in guided]
    score = rate_score(len(gaps) / len(stages), 1.0) if stages else 100
    ctx.metric("Sales stage guidance gaps", len(gaps), "count", "lower-better", score)
    if gaps:
        _setting(
            ctx,
            "Sales stages without guidance",
            f"{len(gaps)} of {len(stages)} open stages have no “Guidance for Success” text on the Path: {', '.join(map(str, gaps[:6]))}.",
            "Add short guidance for each stage on the Opportunity Path: the goal, what to confirm, and links to battle cards or templates.",
            severity="low",
            obj="Opportunity",
        )


# ---------------------------------------------------------------- area 6: activity capture, web-to-lead, templates

def _ids_in(ids: list[str]) -> str:
    return ", ".join(f"'{i}'" for i in ids if re.fullmatch(r"[A-Za-z0-9]{15,18}", i))


# Automated users (by name) and non-selling licences (by profile) aren't reps.
_BOT_NAME = re.compile(r"integration|automated|einstein|agentforce|\bbot\b", re.I)
_NON_REP_PROFILE = re.compile(r"integration|api only|automated process|chatter", re.I)


def sales_reps(ctx: Ctx) -> dict[str, str]:
    """Active people (id -> name) who own open deals or leads. Bots and integration users are left out."""
    if "reps" in ctx.memo:
        return ctx.memo["reps"]
    owners: set[str] = set()
    for obj, cond in (("Opportunity", OPEN_OPPS), ("Lead", OPEN_LEADS)):
        if ctx.has_object(obj):
            for r in ctx.sf.query(f"SELECT OwnerId o, COUNT(Id) c FROM {obj} WHERE {cond} GROUP BY OwnerId LIMIT 2000").get("records", []):
                if str(r.get("o") or "").startswith("005"):  # users, not queues
                    owners.add(r["o"])
    reps: dict[str, str] = {}
    ids = sorted(owners)
    for i in range(0, len(ids), 200):
        for u in ctx.rows(f"SELECT Id, Name, UserType, Profile.Name FROM User WHERE IsActive = true AND Id IN ({_ids_in(ids[i:i + 200])})"):
            profile = (u.get("Profile") or {}).get("Name") or ""
            if u.get("UserType", "Standard") == "Standard" and not _BOT_NAME.search(u.get("Name") or "") and not _NON_REP_PROFILE.search(profile):
                reps[u["Id"]] = u.get("Name") or u["Id"]
    ctx.memo["reps"] = reps
    return reps


def activity_by_owner(ctx: Ctx, days: int) -> dict[str, int]:
    """Tasks + events created per owner in the last `days` days."""
    key = f"activity:{days}"
    if key not in ctx.memo:
        counts: dict[str, int] = {}
        for obj in ("Task", "Event"):
            if ctx.has_object(obj):
                for r in ctx.sf.query(f"SELECT OwnerId o, COUNT(Id) c FROM {obj} WHERE CreatedDate = LAST_N_DAYS:{days} GROUP BY OwnerId LIMIT 2000").get("records", []):
                    counts[str(r.get("o"))] = counts.get(str(r.get("o")), 0) + int(r.get("c") or 0)
        ctx.memo[key] = counts
    return ctx.memo[key]


def missing_sales_activities(ctx: Ctx) -> None:
    """Active people who own open deals or leads but logged no tasks or events in 14 days."""
    reps = sales_reps(ctx)
    active = set(activity_by_owner(ctx, 14))
    quiet = sorted(name for uid, name in reps.items() if uid not in active)
    quiet_ids = [uid for uid in reps if uid not in active]
    ctx.totals["User"] = len(reps)
    score = rate_score(len(quiet) / len(reps), 0.5) if reps else 100
    ctx.metric("Missing sales activities", len(quiet), "count", "lower-better", score)
    ctx.finding(
        name="Reps with no logged activity",
        records=("User", ctx.ids_in(quiet_ids)),
        recent=False,
        score=score,
        affected=len(quiet),
        description=f"{len(quiet)} of {len(reps)} people who own open deals or leads logged no tasks or events in the last 14 days: "
        + ", ".join(quiet[:8]) + (" …" if len(quiet) > 8 else "") + ".",
        why="If calls, emails, and meetings aren’t in Salesforce, managers can’t see what’s happening on deals.",
        impact="Blind spots in coaching and forecasting, and lost history when people leave.",
        action="Turn on Einstein Activity Capture (or the Outlook/Gmail integration) so emails and meetings log automatically, and check activity in weekly 1:1s.",
        obj="User",
    )


def web_to_lead(ctx: Ctx) -> None:
    src = ctx.fields("Lead").get("LeadSource")
    values = [v.get("value") for v in (src or {}).get("picklistValues") or [] if v.get("active") and "web" in str(v.get("value")).lower()]
    if not values:
        values = ["Web"]
    in_list = ", ".join("'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'" for v in values[:10])
    recent = ctx.count("Lead", f"LeadSource IN ({in_list})", "CreatedDate = LAST_N_DAYS:14", recent=False)
    before = ctx.count("Lead", f"LeadSource IN ({in_list})", "CreatedDate = LAST_N_DAYS:90", "CreatedDate < LAST_N_DAYS:14", recent=False)
    if recent == 0 and before > 0:
        issues, score = 1, 25
        ctx.finding(
            name="Website leads have stopped arriving",
            records=("Lead", f"LeadSource IN ({in_list})", "CreatedDate = LAST_N_DAYS:90"),
            recent=False,
            fix="/lightning/setup/LeadWebtoleads/home",
            score=score,
            affected=before,
            description=f"No leads from the website ({', '.join(values[:3])}) in the last 14 days, but {before:,} arrived in the 11 weeks before. The web form may be broken.",
            why="A broken web form silently loses every inbound lead.",
            impact="Lost inbound demand — often your warmest prospects.",
            action="Submit a test lead through your website form now. Check the Web-to-Lead settings, the form’s Salesforce ID, and any spam filter or reCAPTCHA changes.",
            obj="Lead",
            url=ctx.list_url("Lead"),
            min_score=100,
        )
    elif recent == 0 and before == 0:
        issues, score = 1, 70
        _setting(
            ctx,
            "No leads from the website",
            f"No Leads with a web source ({', '.join(values[:3])}) in the last 90 days. If your website has a contact form, it may not be connected to Salesforce.",
            "If you collect leads on your website, set up Web-to-Lead (or your marketing tool’s form sync) and set Lead Source to Web.",
            severity="low",
            obj="Lead",
        )
    else:
        issues, score = 0, 100
    ctx.metric("Web-to-Lead issues", issues, "count", "lower-better", score)


def email_templates(ctx: Ctx) -> None:
    if not ctx.has_object("EmailTemplate"):
        raise Unavailable("Email templates can’t be read with this user.")
    n = ctx.count("EmailTemplate", "IsActive = true", recent=False)
    score = 100 if n >= 5 else 70 if n else 30
    ctx.metric("Email template availability", n, "count", "higher-better", score)
    if n < 5:
        _setting(
            ctx,
            "Few email templates for the sales team",
            f"Only {n} active email template{'s' if n != 1 else ''} found, so reps write the same intro and follow-up emails again and again.",
            "Create Lightning Email Templates for common emails (intro, follow-up, proposal, meeting recap) and organise them in shared folders.",
            severity="low" if n else "medium",
        )


def activity_capture(ctx: Ctx) -> None:
    total = ctx.count("Opportunity", OPEN_OPPS)
    cond = "(LastActivityDate = null OR LastActivityDate < LAST_N_DAYS:30)"
    n = ctx.count("Opportunity", OPEN_OPPS, cond) if total else 0
    score = rate_score(n / total, 0.6) if total else 100
    ctx.metric("Activity capture gaps", n, "count", "lower-better", score)
    if n:
        value = ctx.amount("Opportunity", OPEN_OPPS, cond)
        ctx.finding(
            name="Open deals with no recent activity",
            records=("Opportunity", OPEN_OPPS, cond),
            value=value,
            score=score,
            affected=n,
            description=f"{n:,} of {total:,} open Opportunities ({pct(n, total):.0f}%) have no logged activity in the last 30 days{_worth(value)}.",
            why="Either the deals are going cold, or emails and meetings aren’t being captured. Both hide risk.",
            impact="Deals slip without warning and the forecast looks safer than it is.",
            action="Turn on automatic activity capture, and review deals with no recent activity in pipeline meetings.",
            obj="Opportunity",
            url=ctx.list_url("Opportunity"),
        )


# ---------------------------------------------------------------- area 7: layouts, validation rules, required fields

CORE = ("Account", "Contact", "Lead", "Opportunity")
_VAGUE = re.compile(r"^(error|invalid|not allowed|required|please fix|check (the )?fields?)\.?$", re.I)


def validation_rules(ctx: Ctx) -> None:
    missing, vague = [], []
    for obj in CORE:
        if not ctx.has_object(obj):
            continue
        rules = [r for r in ctx.setup(f"SELECT Id, ValidationName, Active, ErrorMessage FROM ValidationRule WHERE EntityDefinition.QualifiedApiName = '{obj}'") if r.get("Active")]
        if not rules:
            missing.append(obj)
        vague += [f"{obj}: {r.get('ValidationName')}" for r in rules if len((r.get("ErrorMessage") or "").strip()) < 20 or _VAGUE.match((r.get("ErrorMessage") or "").strip())]
    ctx.metric("Missing validation rules", len(missing), "count", "lower-better", 100 - 20 * len(missing))
    if missing:
        _setting(
            ctx,
            "Key objects with no validation rules",
            f"{', '.join(missing)} {'has' if len(missing) == 1 else 'have'} no active validation rules, so incomplete or inconsistent records can be saved.",
            "Add a few targeted validation rules (e.g. Amount required after Qualification, Lost Reason required on Closed Lost) with clear error messages.",
            severity="low",
        )
    if vague:
        _setting(
            ctx,
            "Unclear validation error messages",
            f"{len(vague)} validation rule(s) show short or vague errors, so people don’t know how to fix the record: {', '.join(vague[:5])}.",
            "Rewrite each message to say what to fill in and why, e.g. “Please add an Amount before moving to Proposal.”",
            severity="low",
        )


REQUIRED_CANDIDATES = {
    "Opportunity": ("Amount", "NextStep", "LeadSource", "Type"),
    "Lead": ("Email", "Phone", "LeadSource"),
    "Contact": ("Email", "AccountId"),
    "Account": ("Industry", "Phone", "Type"),
}
BASE = {"Lead": (OPEN_LEADS,), "Opportunity": (OPEN_OPPS,)}


def required_field_gaps(ctx: Ctx) -> None:
    gaps: list[str] = []
    checked = 0
    for obj, names in REQUIRED_CANDIDATES.items():
        if not ctx.has_object(obj):
            continue
        fields = ctx.fields(obj)
        total = ctx.count(obj, *BASE.get(obj, ()))
        if not total:
            continue
        for name in names:
            f = fields.get(name)
            if not f or not f.get("filterable") or not f.get("nillable", True):
                continue  # missing, or already required
            checked += 1
            filled = 100 - pct(ctx.count(obj, *BASE.get(obj, ()), f"{name} = null"), total)
            if filled < 80:
                gaps.append(f"{obj}.{f.get('label') or name} ({filled:.0f}% filled)")
    score = rate_score(len(gaps) / checked, 0.6) if checked else 100
    ctx.metric("Required field gaps", len(gaps), "count", "lower-better", score)
    if gaps:
        _setting(
            ctx,
            "Important fields that are optional and often empty",
            f"{len(gaps)} key fields aren’t required and are often left blank: {', '.join(gaps[:8])}.",
            "Make the most important ones required — on the page layout, with Dynamic Forms, or with a validation rule at the right stage — so they get filled in as work happens.",
            severity="medium" if len(gaps) >= 3 else "low",
        )


_JUNK = {"test", "testing", "na", "n/a", "tbd", "tba", "none", "-", "--", ".", "..", "...", "x", "xx", "xxx", "asdf", "abc", "123",
         "null", "nil", "?", "unknown", "[not provided]", "not provided", "dummy", "sample", "temp", "aaa", "zzz"}


def _is_junk(v: object) -> bool:
    return isinstance(v, str) and v.strip().lower() in _JUNK


def junk_data(ctx: Ctx) -> None:
    found: list[str] = []
    checked = 0
    total_junk = 0
    if ctx.has_object("Opportunity"):
        fields = ctx.fields("Opportunity")
        cols = [c for c in ("NextStep", "Description") if c in fields]
        if cols:
            recs = ctx.rows(f"SELECT Id, {', '.join(cols)} FROM Opportunity WHERE {OPEN_OPPS} ORDER BY LastModifiedDate DESC LIMIT 2000")
            checked += len(recs)
            bad = [r for r in recs if any(_is_junk(r.get(c)) for c in cols)]
            total_junk += len(bad)
            if bad:
                found.append(f"{len(bad):,} open Opportunities (Next Step / Description)")
    for obj, fld, conds in (("Lead", "Company", (OPEN_LEADS,)), ("Contact", "LastName", ()), ("Account", "Name", ())):
        if ctx.has_field(obj, fld, "groupable"):
            groups = ctx.groups(obj, fld, *conds)
            bad = [(v, c) for v, c in groups if _is_junk(v)]
            n = sum(c for _, c in bad)
            checked += sum(c for _, c in groups)
            total_junk += n
            if n:
                found.append(f"{n:,} {('open ' if obj == 'Lead' else '')}{obj}s ({fld} like {', '.join(f'“{v}”' for v, _ in bad[:3])})")
    score = rate_score(total_junk / checked, 0.1) if checked else 100
    ctx.metric("Potential junk data", total_junk, "count", "lower-better", score)
    ctx.finding(
        name="Placeholder or junk values",
        score=score,
        affected=total_junk,
        description=f"{total_junk:,} records contain placeholder values like “test”, “na”, or “tbd”: " + "; ".join(found) + ".",
        why="Junk values usually mean a required field is getting in people’s way, and they make reports and searches unreliable.",
        impact="Misleading reports and wasted time cleaning up.",
        action="Clean these values up, then ask users which required fields they fill with junk — and fix the rule or layout behind it.",
        obj=None,  # spans several objects
        min_score=95,
    )


def layout_usability(ctx: Ctx) -> None:
    concerns: list[str] = []
    for obj in CORE:
        if not ctx.has_object(obj):
            continue
        fields = ctx.fields(obj)
        custom = sum(1 for f in fields.values() if f.get("custom"))
        if custom > 100:
            concerns.append(f"{obj} has {custom} custom fields")
        layouts = ctx.setup(f"SELECT Id, Name FROM Layout WHERE TableEnumOrId = '{obj}'")
        if len(layouts) > 5:
            concerns.append(f"{obj} has {len(layouts)} page layouts")
    ctx.metric("Layout usability concerns", len(concerns), "count", "lower-better", 100 - 15 * min(len(concerns), 6))
    if concerns:
        _setting(
            ctx,
            "Crowded or fragmented page layouts",
            "Some pages are likely hard to use: " + "; ".join(concerns) + ".",
            "Simplify with Dynamic Forms (show fields only when relevant), group fields into tabs, and consolidate similar layouts.",
            severity="low",
        )


AREAS = {
    "area-3": [unassigned_leads, stale_leads, overdue_opportunities, escalation_processes, sales_progression],
    "area-4": [account_relationships, orphaned_contacts, missing_contact_roles, account_hierarchy],
    "area-5": [stuck_opportunities, missing_next_steps, closed_lost_reasons, stage_guidance],
    "area-6": [missing_sales_activities, web_to_lead, email_templates, activity_capture],
    "area-7": [validation_rules, required_field_gaps, junk_data, layout_usability],
}

STEP_LABELS = {
    unassigned_leads: "Finding Leads waiting in queues",
    stale_leads: "Finding stale Leads",
    overdue_opportunities: "Finding overdue deals",
    escalation_processes: "Checking lead assignment and escalation",
    sales_progression: "Checking how deals move through stages",
    account_relationships: "Checking Account relationships",
    orphaned_contacts: "Finding Contacts without an Account",
    missing_contact_roles: "Checking contact roles on deals",
    account_hierarchy: "Checking Account hierarchies",
    stuck_opportunities: "Finding stuck deals",
    missing_next_steps: "Checking next steps on deals",
    closed_lost_reasons: "Checking why deals were lost",
    stage_guidance: "Checking sales stage guidance",
    missing_sales_activities: "Checking rep activity",
    web_to_lead: "Checking website leads",
    email_templates: "Checking email templates",
    activity_capture: "Checking activity on open deals",
    validation_rules: "Reading validation rules",
    required_field_gaps: "Checking required fields",
    junk_data: "Looking for junk values",
    layout_usability: "Reviewing page layouts",
}
