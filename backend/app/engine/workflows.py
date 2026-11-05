"""Category 2 — Workflows & Automation (areas 3 to 7).

Based on the Aquarient RevenueOps Consultant Guide v1.0. Indicator labels match
src/config/categories.ts exactly. Record checks use fixed read-only SOQL; setup
checks (validation rules, Path, flows…) read the Tooling API and are skipped with
a note when the connected user can't view setup.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote, unquote

from ..salesforce import assignment, queues
from ..salesforce.errors import SalesforceAuthExpired, SalesforceError
from .core import Ctx, FindingDraft, Unavailable, pct, rate_score
from .core import in_list as soql_in
from .core import soql_str
from .data_quality import accounts_without_contacts, no_recent_activity, stale_leads

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
    'Contacts can’t be related to multiple Accounts': '/lightning/setup/AccountSettings/home',
    'Contact Roles missing from Opportunity layouts': '/lightning/setup/ObjectManager/Opportunity/PageLayouts/view',
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


# ---------------------------------------------------------------- area 3: Leads in queues and Lead Assignment Rules

QUEUED = "Owner.Type = 'Queue'"


def _owner_history(ctx: Ctx) -> tuple[bool, str]:
    """Whether Lead Owner changes are tracked in Lead History (so the time a Lead entered its current queue is known)."""
    try:
        ctx.count("Lead", "Id IN (SELECT LeadId FROM LeadHistory WHERE Field = 'Owner')", recent=False)
        return True, "the last Lead Owner change in Lead History, when the Lead entered its current queue (or the Created Date, if the owner never changed)"
    except SalesforceAuthExpired:
        raise
    except SalesforceError:
        return False, "the Created Date (Lead Owner changes aren’t tracked in Lead History, so when a Lead entered its queue isn’t known)"


def stuck_queue_leads(ctx: Ctx) -> None:
    """Card 1 — Stuck Queue-Owned Leads: open Leads that have sat in their current queue for more than 3 days (5 and 7 can be
    picked on the card) without a sales user taking them. Leads already reassigned to a user aren't owned by a queue."""
    label = "Stuck Queue-Owned Leads"
    days = queues.DEFAULT_DAYS
    total = ctx.count("Lead", OPEN_LEADS)
    ctx.totals["Lead"] = total
    history, source = _owner_history(ctx)
    base = (OPEN_LEADS, QUEUED)
    queued = ctx.count("Lead", *base) if total else 0
    over = {d: ctx.count("Lead", *base, *queues.longer_than(d, history)) if queued else 0 for d in queues.DAYS}
    n = over[days]
    score = rate_score(n / total, 0.2) if total else 100
    severity = "critical" if over[7] else "high" if over[5] else "medium"
    m = ctx.metric(
        label, n, "count", "lower-better", score,
        how=f"Open Leads that have sat in their current queue for more than {days} days without a sales user taking them, out of {total:,} open Leads.",
        rule=f"100 when no open Lead has waited in a queue more than {days} days, falling evenly to 0 when 20% of open Leads have. "
        "Urgency comes from the longest wait: Critical after 7 days, High after 5, Medium after 3.",
        columns=["Name", "Company", "OwnerId", "CreatedDate"],
        order="CreatedDate",
        extra="days_in_queue",
        criteria=[
            ("Records checked", f"{total:,} open Leads (not converted); {queued:,} owned by a queue"),
            ("Owner", "The Lead Owner is a queue; Leads already reassigned to a user aren’t counted"),
            ("Time in queue", f"Counted from {source}"),
            ("Threshold", f"More than {days} days in the queue (pick 5 or 7 days on the records table)"),
            ("By days in queue", f"More than 3 days: {over[3]:,} (Medium) · more than 5: {over[5]:,} (High) · more than 7: {over[7]:,} (Critical)"),
            ("What's counted", f"{n:,} of {total:,} open Leads ({pct(n, total):.0f}%) have waited in a queue more than {days} days"),
            ("Records listed", "Each with its queue, days in the queue and urgency, longest waiting first"),
        ],
        records=("Lead", *base),
        recent=False,
    )
    if m.records:  # the table starts at the threshold; the person can pick another (or every Lead in a queue)
        m.records[0].update({"queue_days": days, "history": history, "routed_queues": _routed_queue_ids(ctx)})
    if n:
        stuck = ("Lead", *base, *queues.longer_than(days, history))
        top = ctx.by_owner(*stuck)
        ctx.finding(
            name="Leads stuck in a queue",
            records=stuck,
            recent=False,
            fix="/lightning/setup/LeadRules/home",
            score=score,
            min_score=101,  # raised for any stuck Lead; how urgent comes from how long they've waited
            severity=severity,
            affected=n,
            description=f"{n:,} open Leads have waited in a queue more than {days} days without anyone taking them"
            + (f", {over[7]:,} of them more than 7 days" if over[7] else f", {over[5]:,} of them more than 5 days" if over[5] else "") + "."
            + (f" Most are in: {_owners(top)}." if top else ""),
            why="Leads cool off fast. Nobody feels responsible for a lead that sits in a queue.",
            impact="Slower first contact and deals lost to faster competitors.",
            action="Have the queue members take these leads today, route leads to people with an active Lead Assignment Rule "
            "(round-robin or by territory), and alert managers when a lead sits in a queue for more than a day.",
            obj="Lead",
            url=ctx.list_url("Lead"),
        )


RULE_ROWS = 20000  # open Leads read to compare with the rules
RULE_LISTED = 500  # Leads listed under a card
QUEUE_REASONS = 5000  # Leads in inactive queues whose potential match is saved for the Inactive Lead Assignment Rules table


def _lead_rules(ctx: Ctx) -> list[assignment.Rule]:
    """Every Lead Assignment Rule with its entries (read once per check)."""
    if "lead_rules" not in ctx.memo:
        read = getattr(ctx.sf, "read_metadata", None)
        if read is None:
            raise Unavailable("Lead Assignment Rules can only be read from a connected Salesforce org.")
        try:
            ctx.memo["lead_rules"] = assignment.all_rules(read("AssignmentRules", ["Lead"]))
        except SalesforceAuthExpired:
            raise
        except (SalesforceError, ValueError) as exc:
            raise Unavailable(f"Couldn’t read the Lead Assignment Rules ({exc}). The connected user needs “View Setup and Configuration” "
                              "and “Modify Metadata Through Metadata API Functions” (or “Customize Application”).") from None
    return ctx.memo["lead_rules"]


def _rule_leads(ctx: Ctx, rules: list[assignment.Rule]) -> tuple[list[dict], dict[str, str], dict[str, str]]:
    """(open Leads with the fields the rules look at, field types, field labels), read once per check, newest first."""
    if "rule_leads" not in ctx.memo:
        fields = ctx.fields("Lead")
        used = [f for f in assignment.fields_used(*rules) if f in fields]
        cols = ", ".join(dict.fromkeys(["Id", "OwnerId", "Owner.Name", "CreatedById", "CreatedDate", *used]))
        leads = ctx.rows(f"SELECT {cols} FROM Lead WHERE {OPEN_LEADS} ORDER BY CreatedDate DESC", RULE_ROWS)
        types = {f: fields[f]["type"] for f in used}
        labels = {f: fields[f].get("label") or f for f in fields}
        ctx.memo["rule_leads"] = (leads, types, labels)
    return ctx.memo["rule_leads"]


def _owner_name(lead: dict) -> str:
    return (lead.get("Owner") or {}).get("Name") or "its owner"


def _entries(rule: assignment.Rule) -> str:
    return f"{len(rule.entries)} entr{'y' if len(rule.entries) == 1 else 'ies'}"


def _rule_ids(ctx: Ctx) -> dict[str, str]:
    """Lead Assignment Rule name -> id, for links to the rule in Setup (empty when they can't be read)."""
    if "lead_rule_ids" not in ctx.memo:
        try:
            ctx.memo["lead_rule_ids"] = {r["Name"]: r["Id"] for r in ctx.rows("SELECT Id, Name FROM AssignmentRule WHERE SobjectType = 'Lead'", 200)
                                         if r.get("Name") and r.get("Id")}
        except SalesforceAuthExpired:
            raise
        except SalesforceError:
            ctx.memo["lead_rule_ids"] = {}
    return ctx.memo["lead_rule_ids"]


def _rule_item(ctx: Ctx, rule: assignment.Rule, labels: dict[str, str], matched: int | None = None,
               per_entry: dict[int, int] | None = None) -> dict:
    """A rule for the card's list: its status, entries in words, potential matches, and a link to it in Setup."""
    rid = _rule_ids(ctx).get(rule.name)
    return {
        "name": rule.name,
        "active": rule.active,
        "url": ctx.setup_url(f"/lightning/setup/LeadRules/page?address=%2F{rid}" if rid else "/lightning/setup/LeadRules/home"),
        "matches": matched,
        "entries": [{"order": e.order, "criteria": assignment.criteria_text(e, labels), "assigned_to": assignment.target(e),
                     "matches": None if per_entry is None else per_entry.get(e.order, 0)} for e in rule.entries],
    }


def _lead_queues(ctx: Ctx) -> list[dict]:
    """Every queue that can own Leads (read once per check): [{"QueueId", "Queue": {"Name", "DeveloperName"}}]."""
    if "lead_queues" not in ctx.memo:
        try:
            ctx.memo["lead_queues"] = ctx.rows("SELECT QueueId, Queue.Name, Queue.DeveloperName FROM QueueSobject WHERE SobjectType = 'Lead'", 500)
        except SalesforceAuthExpired:
            raise
        except SalesforceError:
            ctx.memo["lead_queues"] = []
    return ctx.memo["lead_queues"]


def _inactive_queues(ctx: Ctx, active: assignment.Rule | None) -> list[dict]:
    """Lead queues the active Lead Assignment Rule never assigns to (every Lead queue when no rule is active): [{"id", "name"}].
    Salesforce has no on/off switch for a queue, so a queue out of the active routing counts as inactive."""
    routed = {e.assigned_to for e in (active.entries if active else []) if e.assigned_to and (e.assigned_type or "").lower() == "queue"}
    out = {r["QueueId"]: (r.get("Queue") or {}).get("Name") or r["QueueId"] for r in _lead_queues(ctx)
           if r.get("QueueId") and (r.get("Queue") or {}).get("DeveloperName") not in routed}
    return sorted(({"id": i, "name": n} for i, n in out.items()), key=lambda q: q["name"].lower())


def _routed_queue_ids(ctx: Ctx) -> list[str] | None:
    """Ids of the Lead queues the active Lead Assignment Rule assigns to (shown green on the queue chips; the others red),
    or None when the rules can't be read."""
    try:
        rules = _lead_rules(ctx)
    except Unavailable:
        return None
    active = next((r for r in rules if r.active), None)
    routed = {e.assigned_to for e in (active.entries if active else []) if e.assigned_to and (e.assigned_type or "").lower() == "queue"}
    return sorted(r["QueueId"] for r in _lead_queues(ctx) if r.get("QueueId") and (r.get("Queue") or {}).get("DeveloperName") in routed)


def _rule_targets(ctx: Ctx, rules: list[assignment.Rule]) -> list[dict]:
    """Who each rule assigns to (its entries' queues and users), by id: [{"name", "targets": [{"id", "name", "type"}]}].
    Queues are found by API name, users by username; one we can't find (deleted, or no access) is left out."""
    queues = {(r.get("Queue") or {}).get("DeveloperName"): {"id": r["QueueId"], "name": (r.get("Queue") or {}).get("Name") or r["QueueId"], "type": "Queue"}
              for r in _lead_queues(ctx) if r.get("QueueId")}
    names = sorted({e.assigned_to for r in rules for e in r.entries if e.assigned_to and (e.assigned_type or "").lower() != "queue"})
    users: dict[str, dict] = {}
    if names:
        try:
            for u in ctx.rows(f"SELECT Id, Name, Username FROM User WHERE {soql_in('Username', list(names), 200)}", 200):
                if u.get("Id") and u.get("Username"):
                    users[u["Username"].lower()] = {"id": u["Id"], "name": u.get("Name") or u["Username"], "type": "User"}
        except SalesforceAuthExpired:
            raise
        except SalesforceError:
            pass
    out = []
    for rule in rules:
        found: dict[str, dict] = {}
        for e in rule.entries:
            if not e.assigned_to:
                continue
            t = queues.get(e.assigned_to) if (e.assigned_type or "").lower() == "queue" else users.get(e.assigned_to.lower())
            if t:
                found.setdefault(t["id"], t)
        out.append({"name": rule.name, "targets": sorted(found.values(), key=lambda t: t["name"].lower())})
    return out


def inactive_rules(ctx: Ctx) -> None:
    """Card 2 — Inactive Lead Assignment Rules: each inactive rule's entries checked against the open Leads, to show how many
    Leads each would match if it were active. These are potential matches only: an inactive rule assigns nothing, so they
    don't mean those Leads are wrongly assigned."""
    label = "Inactive Lead Assignment Rules"
    rules = _lead_rules(ctx)
    inactive = [r for r in rules if not r.active]
    total = ctx.count("Lead", OPEN_LEADS)
    leads, types, labels = _rule_leads(ctx, rules) if total else ([], {}, {})
    if not labels:
        labels = {f: d.get("label") or f for f, d in ctx.fields("Lead").items()}
    reasons: dict[str, list[str]] = {}
    rows: list[tuple[str, str]] = []
    summary: list[str] = []
    listing: list[dict] = []
    for rule in inactive:
        per_entry = {e.order: 0 for e in rule.entries}
        unsure = 0
        for lead in leads:
            hit = assignment.first_match(rule, lead, types)
            if hit:
                per_entry[hit.order] += 1
                reasons.setdefault(lead["Id"], []).append(f"“{rule.name}” entry {hit.order} → {assignment.target(hit)}")
            elif any(assignment.matches(e, lead, types) is None for e in rule.entries):
                unsure += 1
        matched = sum(per_entry.values())
        listing.append(_rule_item(ctx, rule, labels, matched, per_entry))
        summary.append(f"“{rule.name}” ({matched:,})")
        rows.append((f"“{rule.name}” (inactive)",
                     f"{_entries(rule)}; {matched:,} open Leads would potentially match"
                     + (f" ({unsure:,} more only an entry that can’t be checked here might match)" if unsure else "") + " — "
                     + " · ".join(f"{assignment.describe(e, labels)}: {per_entry[e.order]:,}" for e in rule.entries)))
    potential = [ld for ld in leads if ld["Id"] in reasons]
    with_matches = sum(1 for s in summary if not s.endswith("(0)"))
    active = next((r for r in rules if r.active), None)
    listed = ("Lead", ctx.ids_in([ld["Id"] for ld in potential], RULE_LISTED)) if potential else None
    idle = _inactive_queues(ctx, active)
    in_idle = ("Lead", OPEN_LEADS, f"OwnerId IN ({_ids_in([q['id'] for q in idle])})") if total and idle else None
    waiting = ctx.count(*in_idle, recent=False) if in_idle else 0
    m = ctx.metric(
        label, waiting, "count", "lower-better", None,
        how="Open Leads sitting in inactive Lead queues (queues the active Lead Assignment Rule never assigns to), with the Lead "
        "Assignment Rules that are turned off: each entry’s criteria are checked against the open Leads to show how many Leads it "
        "would match if the rule were active. These are potential matches: an inactive rule assigns nothing, so they don’t mean "
        "those Leads are wrongly assigned.",
        rule="Shown for review, not scored: rules that would match many Leads may be worth reactivating, the others reviewing or deleting.",
        columns=["Name", "Company", "OwnerId", "CreatedDate"],
        order="-CreatedDate",
        extra="rule_match",
        criteria=[
            ("Rules read", f"{len(rules)} Lead Assignment Rules in Setup; active: " + (f"“{active.name}”" if active else "none")),
            ("Records checked", f"{len(leads):,} open Leads (not converted)" + (f", the newest {RULE_ROWS:,} of {total:,}" if total > len(leads) else "")),
            ("Potential match", "The first entry of an inactive rule whose criteria the Lead meets, the way Salesforce would pick it"),
            *rows,
            ("What's counted", f"{waiting:,} open Leads in inactive Lead queues; {len(inactive)} inactive rule{'' if len(inactive) == 1 else 's'}, "
             f"{with_matches} of them matching open Leads ({len(potential):,} open Leads would potentially match one)"),
            ("Inactive Lead queues", "Lead queues the active rule never assigns to: "
             + (", ".join(q["name"] for q in idle) if idle else "none, the active rule routes to every Lead queue")),
            ("Records listed", "The open Leads in the inactive Lead queues (pick a queue above the table), newest first, each with the "
             "inactive rule entry that would match it, if any"),
        ],
        records=in_idle,
        recent=False,
    )
    m.rule_list = sorted(listing, key=lambda r: -(r["matches"] or 0)) + ([_rule_item(ctx, active, labels)] if active else [])
    if m.records:  # the table: the Leads in the inactive Lead queues, or those a picked rule or assignee owns, with their potential match
        targets = _rule_targets(ctx, inactive)
        ids = {q["id"] for q in idle} | {t["id"] for r in targets for t in r["targets"]}
        mine = [ld for ld in potential if ld.get("OwnerId") in ids][:QUEUE_REASONS]
        m.records[0].update({
            "reasons": {ld["Id"]: "Potential match: " + "; ".join(reasons[ld["Id"]]) for ld in mine},
            "reason": "No inactive rule entry matches this Lead",
            "inactive_queues": idle,
            "rule_targets": targets,  # each inactive rule's queues and users, for the chips above the table
            "open_where": OPEN_LEADS,  # the open Leads, before narrowing to the inactive queues
        })
    if with_matches:
        ctx.finding(
            name="Inactive Lead Assignment Rules match existing Leads",
            records=listed,
            recent=False,
            fix="/lightning/setup/LeadRules/home",
            score=90,
            min_score=101,  # raised for review whenever an inactive rule would match Leads
            severity="low",
            affected=len(potential),
            description=f"{with_matches} inactive Lead Assignment Rule{'' if with_matches == 1 else 's'} would match open Leads if active: "
            + ", ".join(s for s in summary if not s.endswith("(0)")) + ". These are potential matches, not wrongly assigned Leads.",
            why="An inactive rule may be the routing your team meant to use, or an outdated one that confuses whoever maintains Setup.",
            impact="Leads that a rule was built to route may be waiting for manual assignment instead.",
            action="Review each inactive rule: reactivate the one that should route Leads (only one rule can be active), update its entries "
            "if needed, and delete rules that are no longer used.",
            obj="Lead",
            url=ctx.list_url("Lead"),
        )


def _assigned_by_hand(ctx: Ctx, leads: list[dict]) -> set[str]:
    """Leads whose owner was changed after they were created (assigned by a person or another process), from Lead History;
    when Lead Owner changes aren't tracked, the Leads now owned by someone other than their creator."""
    ids = [ld["Id"] for ld in leads]
    out: set[str] = set()
    for i in range(0, len(ids), 300):
        try:
            out |= {r["LeadId"] for r in ctx.rows(f"SELECT LeadId FROM LeadHistory WHERE Field = 'Owner' AND LeadId IN ({_ids_in(ids[i:i + 300])})", 50000)}
        except SalesforceAuthExpired:
            raise
        except SalesforceError:
            return {ld["Id"] for ld in leads if ld.get("OwnerId") != ld.get("CreatedById")}
    return out


def criteria_mismatches(ctx: Ctx) -> None:
    """Card 3 — Lead Assignment Criteria Mismatches: open Leads checked against the active Lead Assignment Rule's entries; the
    ones that match no entry have no automatic routing path. Each is shown with its current owner and why no entry matches,
    and split into those already assigned by hand and those still waiting. Inactive rules play no part: they can't route."""
    label = "Lead Assignment Criteria Mismatches"
    rules = _lead_rules(ctx)
    rule = next((r for r in rules if r.active), None)
    total = ctx.count("Lead", OPEN_LEADS)
    leads, types, labels = _rule_leads(ctx, rules) if total else ([], {}, {})
    unsure = 0
    if rule is None:
        _setting(ctx, "No active Lead Assignment Rule",
                 "New Leads aren’t routed to anyone automatically: each one stays with whoever creates it, or goes to the default lead owner.",
                 "In Setup → Lead Assignment Rules, activate the rule that should route Leads (or create one) so new Leads get an owner automatically.",
                 severity="high", obj="Lead")
        mismatched = list(leads)
        why = {ld["Id"]: "no Lead Assignment Rule is active" for ld in leads}
    else:
        mismatched, why = [], {}
        for lead in leads:
            results = [assignment.matches(e, lead, types) for e in rule.entries]
            if all(r is False for r in results):
                mismatched.append(lead)
                why[lead["Id"]] = "; ".join(assignment.miss(e, lead, types, labels) for e in rule.entries)
            elif not any(results):  # no entry surely matched, but one couldn't be checked
                unsure += 1
    by_hand = _assigned_by_hand(ctx, mismatched) if mismatched else set()
    waiting = [ld for ld in mismatched if ld["Id"] not in by_hand]
    n = len(mismatched)
    score = rate_score(len(waiting) / total, 0.2) if total else 100
    shown = sorted(mismatched, key=lambda ld: ld["Id"] in by_hand)[:RULE_LISTED]  # still waiting first
    reasons = {ld["Id"]: (f"Assigned by hand to {_owner_name(ld)}" if ld["Id"] in by_hand else f"No assignment path: still with {_owner_name(ld)}")
               + f" — no active rule entry matches: {why[ld['Id']]}" for ld in shown}
    listed = ("Lead", ctx.ids_in([ld["Id"] for ld in shown], RULE_LISTED)) if shown else None
    m = ctx.metric(
        label, n, "count", "lower-better", score,
        how="Open Leads checked against the entries of the active Lead Assignment Rule: the ones that match no entry have no automatic "
        "routing path. Each is shown with its current owner and why no entry matches, and whether it has already been assigned by hand.",
        rule="100 when every open Lead matches an active rule entry or has been assigned by hand, falling evenly to 0 when 20% of open "
        "Leads have neither. Inactive rules aren’t used: they can’t route a Lead (see the Inactive Lead Assignment Rules card).",
        columns=["Name", "Company", "OwnerId", "CreatedDate"],
        order="-CreatedDate",
        extra="assignment_gap",
        criteria=[
            ("Records checked", f"{len(leads):,} open Leads (not converted)" + (f", the newest {RULE_ROWS:,} of {total:,}" if total > len(leads) else "")),
            ("Active rule", f"“{rule.name}”, {_entries(rule)}, read from Setup" if rule else "None is active, so no Lead has an automatic routing path"),
            *([("Active rule entries", " · ".join(assignment.describe(e, labels) for e in rule.entries))] if rule else []),
            ("Mismatch", "The Lead meets the criteria of none of the active rule’s entries (each entry’s filter logic included)"
             + (f"; {unsure:,} that only an entry that can’t be checked here might match aren’t counted" if unsure else "")
             if rule else "Every open Lead, as there’s no active rule"),
            ("Assigned by hand", "The Lead’s owner was changed after it was created (Lead History): someone has already given it to a user or queue"),
            ("What's counted", f"{n:,} of {total:,} open Leads ({pct(n, total):.0f}%) match no active rule entry: {len(waiting):,} with no "
             f"assignment path, {len(by_hand):,} already assigned by hand"),
            ("Records listed", "Each with its current owner and why no entry matches, the ones with no assignment path first"
             + (f" (the first {RULE_LISTED:,})" if n > RULE_LISTED else "")),
        ],
        records=listed,
        recent=False,
    )
    if m.records:
        m.records[0]["reasons"] = reasons
    if waiting:
        owners: dict[str, int] = {}
        for ld in waiting:
            owners[_owner_name(ld)] = owners.get(_owner_name(ld), 0) + 1
        top = sorted(owners.items(), key=lambda kv: -kv[1])[:3]
        ctx.finding(
            name="Leads with no assignment path",
            records=("Lead", ctx.ids_in([ld["Id"] for ld in waiting], RULE_LISTED)),
            recent=False,
            fix="/lightning/setup/LeadRules/home",
            score=score,
            affected=len(waiting),
            description=f"{len(waiting):,} open Leads match no " + (f"entry of the active Lead Assignment Rule “{rule.name}”" if rule else "Lead Assignment Rule, as none is active")
            + " and haven’t been assigned by hand" + (f"; {len(by_hand):,} more were assigned by hand" if by_hand else "") + "."
            + (f" Most are with: {', '.join(f'{o} ({c})' for o, c in top)}." if top else ""),
            why="A Lead no rule entry catches stays with the default lead owner or its creator, where nobody is expecting it.",
            impact="Leads wait for someone to notice and assign them by hand, so first contact is slow or never happens.",
            action="Assign these Leads now, then make the active rule catch them: add or widen entries (for example a last entry with no "
            "criteria that sends everything else to a triage queue), and check the entries’ criteria for missing values.",
            obj="Lead",
            url=ctx.list_url("Lead"),
        )


def lead_no_activity(ctx: Ctx) -> None:
    """No Activity in 6 Months (Leads): open Leads with no task, event, call or email logged in 6 months (moved here from Area 1)."""
    no_recent_activity(ctx, "Lead")


# ---------------------------------------------------------------- area 4: account hierarchies & contact relationships

NO_ROLES = "Id NOT IN (SELECT OpportunityId FROM OpportunityContactRole)"
ROLE_ROWS = 20000  # open-deal contact roles read for Multi-Deal Contacts
ROLE_LISTED = 500  # Contacts listed (with their roles) on Multi-Deal Contacts


def _layouts_without(ctx: Ctx, obj: str, needle: str) -> tuple[list[str], list[str]] | None:
    """(every page layout of `obj`, those whose related lists have none containing `needle`), read through the Metadata API;
    None when the layouts can't be read."""
    read = getattr(ctx.sf, "read_metadata", None)
    if read is None:
        return None
    try:
        rows = ctx.setup(f"SELECT Name, NamespacePrefix FROM Layout WHERE TableEnumOrId = '{obj}'")
    except Unavailable:
        return None
    names = sorted({f"{obj}-" + (f"{r['NamespacePrefix']}__" if r.get("NamespacePrefix") else "") + r["Name"] for r in rows if r.get("Name")})
    missing: list[str] = []
    try:
        for i in range(0, len(names), 10):  # readMetadata takes up to 10 names
            chunk = names[i:i + 10]
            xml = read("Layout", [quote(n, safe=" -_.") for n in chunk])
            for rec in ET.fromstring(xml).iter(f"{{{assignment.NS['m']}}}records"):
                full = unquote(rec.findtext("m:fullName", "", assignment.NS))
                lists = [el.text or "" for el in rec.iter(f"{{{assignment.NS['m']}}}relatedList")]
                if full and not any(needle.lower() in t.lower() for t in lists):
                    missing.append(full.removeprefix(f"{obj}-"))
    except SalesforceAuthExpired:
        raise
    except (SalesforceError, ET.ParseError):
        return None
    return [n.removeprefix(f"{obj}-") for n in names], sorted(missing)


def contact_roles(ctx: Ctx) -> None:
    """Opportunities Without Contact Roles: open deals with nobody named on them, by owner with their value, and whether the
    Contact Roles related list is on the Opportunity page layouts."""
    label = "Opportunities Without Contact Roles"
    total = ctx.count("Opportunity", OPEN_OPPS)
    n = ctx.count("Opportunity", OPEN_OPPS, NO_ROLES) if total else 0
    score = rate_score(n / total, 0.6) if total else 100
    owners = ctx.by_owner("Opportunity", OPEN_OPPS, NO_ROLES, amount=True, limit=10) if n else []
    value = ctx.amount("Opportunity", OPEN_OPPS, NO_ROLES) if n else None
    layouts = _layouts_without(ctx, "Opportunity", "ContactRole")
    if layouts is None:
        on_layout = "Couldn’t read the Opportunity page layouts (needs “View Setup and Configuration” and Metadata API access)"
    elif not layouts[0]:
        on_layout = "No Opportunity page layouts found"
    elif layouts[1]:
        on_layout = f"Missing from {len(layouts[1])} of {len(layouts[0])} Opportunity layouts: " + ", ".join(layouts[1])
    else:
        on_layout = f"On all {len(layouts[0])} Opportunity layouts"
    ctx.metric(
        label, n, "count", "lower-better", score,
        how="Open Opportunities with no Contact Roles (no Contact named as decision maker, influencer and so on), grouped by "
        "owner with the deals’ total Amount. We also check that the Contact Roles related list is on the Opportunity page layouts.",
        rule="100 when every open deal has a Contact Role, falling evenly to 0 when 60% of open deals have none.",
        columns=["Name", "AccountId", "StageName", "Amount", "CloseDate", "OwnerId"],
        order="CloseDate",
        criteria=[
            ("Records checked", f"{total:,} open Opportunities (not Closed Won or Closed Lost)"),
            ("Missing", "No Opportunity Contact Role on the deal"),
            ("What's counted", f"{n:,} of {total:,} open Opportunities ({pct(n, total):.0f}%) have no Contact Roles" + _worth(value)),
            ("By owner", "; ".join(f"{o}: {c:,}" + (f" ({_money(a)})" if a else "") for o, c, a in owners) if owners else "—"),
            ("Contact Roles on the page", on_layout),
            ("Records listed", "Every open Opportunity with no Contact Roles, by close date"),
        ],
        records=("Opportunity", OPEN_OPPS, NO_ROLES),
    )
    if n:
        ctx.finding(
            name="Open deals with no contact roles",
            records=("Opportunity", OPEN_OPPS, NO_ROLES),
            value=value,
            score=score,
            affected=n,
            description=f"{n:,} of {total:,} open Opportunities ({pct(n, total):.0f}%) have no Contact Roles{_worth(value)}."
            + (f" Most belong to: {_owners(owners)}." if owners else ""),
            why="Without Contact Roles you don’t know who decides, who influences, and who signs.",
            impact="Single-threaded deals that stall when one contact goes quiet, and no data on buying groups.",
            action="Add the decision maker and key influencers to each open deal. Make the Contact Roles list prominent on the Opportunity page.",
            obj="Opportunity",
            url=ctx.list_url("Opportunity"),
            measure=label,
        )
    if layouts and layouts[1]:
        _setting(
            ctx,
            "Contact Roles missing from Opportunity layouts",
            f"The Contact Roles related list isn’t on {len(layouts[1])} of {len(layouts[0])} Opportunity page layouts ({', '.join(layouts[1][:5])}"
            + (", …" if len(layouts[1]) > 5 else "") + "), so reps using them can’t see or add the people on a deal.",
            "In Setup → Object Manager → Opportunity → Page Layouts, add the Contact Roles related list to each layout.",
            severity="medium",
            obj="Opportunity",
        )


def orphaned_contacts(ctx: Ctx) -> None:
    total = ctx.total("Contact")
    n = ctx.count("Contact", "AccountId = null") if total else 0
    score = rate_score(n / total, 0.2) if total else 100
    ctx.metric(
        "Orphaned Contacts", n, "count", "lower-better", score,
        how="Contacts that aren’t linked to any Account.",
        rule="100 when every Contact has an Account, falling evenly to 0 when 20% of Contacts have none.",
        columns=["Name", "AccountId", "Email", "OwnerId", "CreatedDate"],
        order="CreatedDate",
        criteria=[
            ("Records checked", f"{total:,} Contacts"),
            ("Field checked", "Account Name"),
            ("Orphaned", "Account Name is empty"),
            ("What's counted", f"{n:,} of {total:,} Contacts ({pct(n, total):.0f}%) have no Account"),
            ("Records listed", "Every Contact with no Account, oldest first"),
        ],
        records=("Contact", "AccountId = null"),
    )
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


MULTI = "Id IN (SELECT ContactId FROM AccountContactRelation WHERE IsDirect = false)"


def multiple_accounts(ctx: Ctx) -> None:
    """Contacts to Multiple Accounts: whether the feature is on, and how many Contacts are related to more than one Account."""
    label = "Contacts to Multiple Accounts"
    total = ctx.total("Contact")
    if not ctx.has_object("AccountContactRelation"):
        ctx.metric(
            label, 0, "count", "higher-better", 50,
            how="Whether “Contacts to Multiple Accounts” is turned on, and how many Contacts are related to more than one Account.",
            rule="100 when the feature is on; 50 when it’s off.",
            criteria=[
                ("Feature", "Off: the Account Contact Relationship object isn’t available"),
                ("What's counted", "No Contact can be related to more than its own Account"),
            ],
        )
        _setting(
            ctx,
            "Contacts can’t be related to multiple Accounts",
            "The “Contacts to Multiple Accounts” feature is off, so a person who works with several companies can only be linked to one.",
            "In Setup → Account Settings, turn on “Allow users to relate a contact to multiple accounts” and add the Related Accounts list to Contacts.",
            severity="low",
            obj="Contact",
        )
        return
    n = ctx.count("Contact", MULTI, recent=False) if total else 0
    links = ctx.count("AccountContactRelation", "IsDirect = false", recent=False) if total else 0
    ctx.metric(
        label, n, "count", "higher-better", 100,
        how="Whether “Contacts to Multiple Accounts” is turned on, and how many Contacts are related to more than one Account "
        "(an indirect relationship besides their own Account).",
        rule="100 when the feature is on; 50 when it’s off. How many Contacts use it is shown for review, not scored.",
        columns=["Name", "Email", "Title", "OwnerId"],
        order="Name",
        extra="related_accounts",
        criteria=[
            ("Feature", "On: Contacts can be related to more than one Account"),
            ("Records checked", f"{total:,} Contacts"),
            ("Related to more than one Account", "The Contact has at least one indirect Account Contact Relationship"),
            ("What's counted", f"{n:,} Contacts ({pct(n, total):.0f}%) are related to more than one Account, through {links:,} indirect relationships"),
            ("Records listed", "Every Contact related to more than one Account, by name, with every Account it’s related to "
             "(its own Account first)"),
        ],
        records=("Contact", MULTI),
        recent=False,
    )


def multi_deal_contacts(ctx: Ctx) -> None:
    """Multi-Deal Contacts: Contacts with a Contact Role on more than one open Opportunity, with their roles (shown, not scored)."""
    label = "Multi-Deal Contacts"
    try:
        rows = ctx.rows("SELECT ContactId, Role, Opportunity.Name FROM OpportunityContactRole "
                        "WHERE Opportunity.IsClosed = false AND ContactId != null ORDER BY ContactId", ROLE_ROWS)
    except SalesforceAuthExpired:
        raise
    except SalesforceError as exc:
        raise Unavailable(f"Couldn’t read the Opportunity Contact Roles ({exc}).") from None
    deals: dict[str, list[str]] = {}
    for r in rows:
        deals.setdefault(r["ContactId"], []).append(f"{r.get('Role') or 'No role'} on {(r.get('Opportunity') or {}).get('Name') or 'a deal'}")
    multi = {c: d for c, d in deals.items() if len(d) > 1}
    ids = sorted(multi, key=lambda c: -len(multi[c]))
    roles: dict[str, int] = {}
    for d in multi.values():
        for s in d:
            role = s.split(" on ", 1)[0]
            roles[role] = roles.get(role, 0) + 1
    m = ctx.metric(
        label, len(multi), "count", "higher-better", None,
        how="Contacts with a Contact Role on more than one open Opportunity (an influencer or decision maker across several deals), "
        "with their role on each deal.",
        rule="Shown for review, not scored: these are the people to keep close, since several deals depend on them.",
        columns=["Name", "AccountId", "Title", "OwnerId"],
        criteria=[
            ("Records checked", f"{len(rows):,} Contact Roles on open Opportunities" + (f" (the first {ROLE_ROWS:,})" if len(rows) >= ROLE_ROWS else "")),
            ("Multi-deal", "The Contact has a Contact Role on two or more open Opportunities"),
            ("What's counted", f"{len(multi):,} of {len(deals):,} Contacts with a role on an open deal are on more than one"),
            ("Their roles", "; ".join(f"{r}: {c:,}" for r, c in sorted(roles.items(), key=lambda x: -x[1])) if roles else "—"),
            ("Records listed", f"The Contacts on the most open deals first (up to {ROLE_LISTED:,}), each with their roles"),
        ],
        records=("Contact", ctx.ids_in(ids, ROLE_LISTED)) if ids else None,
        recent=False,
        extra="deal_roles",
    )
    if m.records:
        m.records[0]["reasons"] = {c: "\n".join(multi[c]) for c in ids[:ROLE_LISTED]}  # one "Role on Deal" per line


LOOP_ROWS = 200000  # Accounts with a Parent Account read to follow their hierarchies


def _loops(parent: dict[str, str]) -> list[list[str]]:
    """Every loop in the parent links (each Account → its Parent Account), once each, in the order the links go:
    A's parent B, B's parent C, C's parent A gives [A, B, C]; an Account that is its own parent gives [A]."""
    done: set[str] = set()
    loops: list[list[str]] = []
    for start in parent:
        if start in done:
            continue
        path: list[str] = []
        at: dict[str, int] = {}
        node = start
        while node in parent and node not in done and node not in at:
            at[node] = len(path)
            path.append(node)
            node = parent[node]
        if node in at:  # came back to an Account on this path: the rest of the path from there is a loop
            loops.append(path[at[node]:])
        done.update(path)
    return loops


CHAIN_LISTED = 200  # parent Accounts listed (one page), by batch
CHAIN_SAVED = 20000  # Accounts whose place in their hierarchy is saved for the table


def hierarchy_chains(ctx: Ctx) -> None:
    """Account Hierarchy Chains: how Accounts link up through Parent Account (A is the parent of B, B of C: A → B → C).
    Every Account with a parent is read and its chain followed up to its top Account; each Account gets its top Account,
    level and the Accounts below it. Shown for review, not scored; a chain that loops back on itself raises a problem."""
    label = "Account Hierarchy Chains"
    if not ctx.has_field("Account", "ParentId"):
        raise Unavailable("Accounts in this org have no Parent Account field, so there are no hierarchies to check.")
    total = ctx.count("Account", recent=False)
    rows = _parent_links(ctx) if total else []
    parent = {r["Id"]: r["ParentId"] for r in rows if r.get("Id") and r.get("ParentId")}
    names = {r["Id"]: r.get("Name") or r["Id"] for r in rows if r.get("Id")}
    tops = sorted({p for p in parent.values() if p not in parent})  # parents with no parent of their own
    for i in range(0, len(tops), 200):  # their names (they aren't in the rows above)
        try:
            for r in ctx.rows(f"SELECT Id, Name FROM Account WHERE {ctx.ids_in(tops[i:i + 200], 200)}", 200):
                names[r["Id"]] = r.get("Name") or r["Id"]
        except SalesforceAuthExpired:
            raise
        except SalesforceError:
            break
    loops = _loops(parent)
    in_loop = {a for loop in loops for a in loop}

    # each Account's chain from its top Account down to it (for a loop: round the loop, ending at the Account)
    chain: dict[str, list[str]] = {t: [t] for t in tops}
    for loop in loops:
        for a in loop:  # walk up from a until back at a, then read it top-down
            up, node = [a], parent[a]
            while node != a:
                up.append(node)
                node = parent[node]
            chain[a] = up[::-1]
    for a in parent:
        seen: list[str] = []
        node = a
        while node not in chain and node in parent:
            seen.append(node)
            node = parent[node]
        base = chain.get(node, [node])
        for s in reversed(seen):
            base = [*base, s]
            chain[s] = base
    members = sorted(set(tops) | set(parent), key=lambda a: (names.get(a) or a).lower())
    looped = {a for a in members if chain[a][0] in in_loop or a in in_loop}  # in a loop, or under one

    def top_of(a: str) -> str | None:
        return None if a in looped else chain[a][0]

    def path_of(a: str) -> str:
        text = " → ".join(names.get(x, x) for x in chain[a])
        if a in looped:
            # in a loop: the last Account is the parent of the first, so the chain goes round; under a loop: no top Account
            return text + f" ↻ back to {names.get(chain[a][0], chain[a][0])}" if a in in_loop else f"↻ (loop) {text}"
        return text

    families: dict[str, list[str]] = {}
    for a in members:
        if top_of(a):
            families.setdefault(top_of(a), []).append(a)
    biggest = sorted(families, key=lambda t: (-len(families[t]), (names.get(t) or t).lower()))
    # Batches: each hierarchy (its top Account and everything under it), largest first, then each loop with the Accounts under it.
    loop_rep = {x: loop[0] for loop in loops for x in loop}
    batch_key = {a: (top_of(a) or loop_rep[chain[a][0]]) for a in members}
    order = [*biggest, *(loop[0] for loop in loops)]
    batch_no = {k: n for n, k in enumerate(order, 1)}
    kids: dict[str, list[str]] = {}
    for child, p in parent.items():
        kids.setdefault(p, []).append(child)
    # the rows: the parent Accounts (those with a child), by batch, then level (top first), then name
    parents = sorted((a for a in members if a in kids),
                     key=lambda a: (batch_no[batch_key[a]], 0 if a in looped else len(chain[a]), (names.get(a) or a).lower()))
    deepest = max((a for a in members if a not in looped), key=lambda a: len(chain[a]), default=None)
    loop_text = "; ".join(path_of(loop[0]) for loop in loops[:5]) + (f"; and {len(loops) - 5:,} more" if len(loops) > 5 else "")
    m = ctx.metric(
        label, len(members), "count", "lower-better", None,
        how="How Accounts link up through Parent Account: Account A is the parent of B, B of C, so their chain is A → B → C. "
        "We read every Account that has a Parent Account and follow it up to its top Account (the one with no parent); "
        "an Account is in a hierarchy when it has a parent or at least one child.",
        rule="Shown for review, not scored: hierarchies are neither good nor bad. A chain that loops back on itself "
        "(A → B → C → A) has no top Account and raises a problem.",
        columns=["Name", "Phone", "Industry", "OwnerId"],
        order="Name",
        criteria=[
            ("Records checked", f"{len(rows):,} Accounts with a Parent Account, of {total:,} Accounts"
             + (f" (the first {LOOP_ROWS:,})" if len(rows) >= LOOP_ROWS else "")),
            ("In a hierarchy", "The Account has a Parent Account or is the Parent Account of another Account"),
            ("What's counted", f"{len(members):,} of {total:,} Accounts ({pct(len(members), total):.0f}%) are in a hierarchy, "
             f"across {len(families):,} hierarch{'y' if len(families) == 1 else 'ies'}"),
            ("Deepest chain", f"{len(chain[deepest])} levels: {path_of(deepest)}" if deepest else "None"),
            ("Largest hierarchy", f"{names.get(biggest[0], biggest[0])} ({len(families[biggest[0]]):,} Accounts)" if biggest else "None"),
            ("Loops", f"{len(in_loop):,} Accounts in {len(loops):,} loop{'' if len(loops) == 1 else 's'}: {loop_text}" if loops else "None"),
            ("Batches", f"Each hierarchy is a batch (its top Account and every Account under it), largest first"
             + (", then each loop" if loops else "") + f": {len(order):,} batch{'' if len(order) == 1 else 'es'}"),
            ("Records listed", f"The parent Accounts (those with a child Account), grouped by batch and top Account first, each with "
             f"its Child Accounts (up to {CHAIN_LISTED:,}, the largest batches first)"),
        ],
        records=("Account", ctx.ids_in(parents, CHAIN_LISTED)) if parents else None,
        recent=False,
        extra="hierarchy",
    )
    m.out_of, m.out_of_label = total, "Accounts"
    if m.records:
        m.records[0].update({
            # each parent Account's batch, level (0 in a loop, to sort by) and Child Accounts (their names, one per line)
            "reasons": {a: {"batch": batch_no[batch_key[a]], "level": 0 if a in looped else len(chain[a]),
                            "children": "\n".join(sorted((names.get(k) or k for k in kids[a]), key=str.lower))} for a in parents[:CHAIN_SAVED]},
        })
    if loops:
        members_in = sorted(in_loop)
        ctx.finding(
            name="Account hierarchies that loop back on themselves",
            records=("Account", ctx.ids_in(members_in, CHAIN_LISTED)),
            recent=False,
            score=50,
            min_score=101,  # raised for any loop
            severity="high",
            affected=len(in_loop),
            description=f"{len(in_loop):,} Accounts are in {len(loops):,} Parent Account loop{'' if len(loops) == 1 else 's'}, e.g. {path_of(loops[0][0])}.",
            why="A hierarchy that goes round in a circle has no top Account, so the hierarchy view, roll-up reports and anything "
            "that walks up to the parent company can’t work it out.",
            impact="Wrong or missing totals for the parent company, and Accounts that can’t be placed in their real company structure.",
            action="Open one Account in each loop and correct or clear its Parent Account so the chain ends at the real top company.",
            obj="Account",
            url=ctx.list_url("Account"),
            measure=label,
        )


def _parent_links(ctx: Ctx) -> list[dict]:
    """Every Account that has a Parent Account (Id, Name, ParentId), read once per check for the hierarchy cards."""
    if "parent_links" not in ctx.memo:
        ctx.memo["parent_links"] = ctx.rows("SELECT Id, Name, ParentId FROM Account WHERE ParentId != null", LOOP_ROWS)
    return ctx.memo["parent_links"]


GUESS_ROWS = 50000  # Accounts read to look for a missing Parent Account
GUESS_CONTACTS = 50000  # Contacts read for their email domains
GUESS_LISTED = 200  # Accounts listed (one page, most likely first)

# Words dropped before names are compared ("Acme Corp - West (UK)" → "acme"), and words too common to match on alone.
_LEGAL = {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "plc", "gmbh", "ag", "sa", "sarl",
          "bv", "nv", "pty", "pvt", "lp", "llp", "group", "holdings", "holding", "the"}
_PLACE = {"east", "west", "north", "south", "central", "northeast", "northwest", "southeast", "southwest", "region", "regional",
          "division", "branch", "office", "hq", "headquarters", "subsidiary", "unit", "dept", "department", "europe", "emea", "apac",
          "americas", "asia", "uk", "us", "usa", "india", "global", "international", "intl"}
_COMMON = {"abc", "test", "sample", "services", "service", "solutions", "systems", "enterprises", "partners", "consulting",
           "technologies", "technology", "tech", "industries", "trading", "new", "first", "united", "american", "national",
           "general", "best", "my", "and", "of", "account", "individual", "customer", "zz", "do", "not", "use", "media", "labs"}
_PERSONAL = {"gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "icloud.com", "me.com", "aol.com",
             "msn.com", "mail.com", "gmx.com", "yandex.com", "zoho.com", "protonmail.com", "proton.me", "example.com", "example.org",
             "test.com", "salesforce.com", "force.com"}
_STRENGTH = {"sibling": 3, "duns": 3, "domain": 2, "contacts": 2, "name": 2, "phone": 1, "address": 1}


def _clean_name(name: str) -> list[str]:
    """A name's words without punctuation, (brackets), " - suffixes", legal words or places: "Acme Corp - West (UK)" → ["acme"]."""
    base = re.split(r"\s[-–—|]\s", re.sub(r"\([^)]*\)", " ", name or ""))[0]
    words = re.findall(r"[a-z0-9]+", base.lower().replace("&", " and "))
    return [w for w in words if w not in _LEGAL and w not in _PLACE]


def _domain(value: str | None) -> str | None:
    """The company's own web domain from a website or email ("https://uk.acme.co.uk/x" → "acme.co.uk"); None for personal ones."""
    if not value:
        return None
    host = value.strip().lower().split("@")[-1]
    host = re.sub(r"^[a-z]+://", "", host).split("/")[0].split(":")[0].removeprefix("www.")
    labels = [x for x in host.split(".") if x]
    if len(labels) < 2:
        return None
    keep = 3 if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in ("co", "com", "org", "net", "ac", "gov", "ltd") else 2
    d = ".".join(labels[-keep:])
    return None if d in _PERSONAL else d


def _phone(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if len(digits) >= 7 else None


def missing_parents(ctx: Ctx) -> None:
    """Possible Missing Parent Accounts: Accounts with no Parent Account that probably belong under another Account, guessed
    from clues in the data (Ownership = Subsidiary, a sibling that already has a parent, the same website or Contact email
    domain, a name that contains another Account's name, the same phone or billing address, D&B parent DUNS). Suggestions
    only, for someone to confirm in Salesforce: shown for review, not scored."""
    label = "Possible Missing Parent Accounts"
    if not ctx.has_field("Account", "ParentId"):
        raise Unavailable("Accounts in this org have no Parent Account field, so there are no parent Accounts to suggest.")
    fields = ctx.fields("Account")
    want = ["Website", "Phone", "BillingStreet", "BillingPostalCode", "Ownership", "DunsNumber", "CreatedDate"]
    have = [f for f in want if f in fields]
    duns_parent = "DandbCompanyId" in fields and "DunsNumber" in fields
    cols = ["Id", "Name", "ParentId", *have] + (["DandbCompany.ParentOrHqDunsNumber"] if duns_parent else [])
    try:
        rows = ctx.rows(f"SELECT {', '.join(cols)} FROM Account ORDER BY CreatedDate", GUESS_ROWS)
    except SalesforceError:
        if not duns_parent:
            raise
        duns_parent = False  # no access to D&B companies: go without
        rows = ctx.rows(f"SELECT {', '.join(cols[:-1])} FROM Account ORDER BY CreatedDate", GUESS_ROWS)
    acc = {r["Id"]: r for r in rows if r.get("Id")}
    parent = {i: r["ParentId"] for i, r in acc.items() if r.get("ParentId")}
    children: dict[str, int] = {}
    for p in parent.values():
        children[p] = children.get(p, 0) + 1
    name = {i: r.get("Name") or i for i, r in acc.items()}
    clean = {i: _clean_name(name[i]) for i in acc}
    order = {i: n for n, i in enumerate(acc)}  # oldest first

    def rank(i: str) -> tuple:  # the likely parent of a group: has children, then the shortest name, then the oldest
        return (-children.get(i, 0), len(" ".join(clean[i])) or 99, len(name[i]), order[i])

    def under(a: str, b: str) -> bool:  # is b somewhere under a (so it can't be a's parent)?
        seen, node = set(), b
        while node in parent and node not in seen:
            seen.add(node)
            node = parent[node]
            if node == a:
                return True
        return False

    clues: dict[str, dict[str, list[tuple[str, str]]]] = {}  # Account → suggested parent → [(clue, in words)]

    def add(a: str, p: str | None, kind: str, text: str) -> int:
        """Note a clue that p is a's parent; 1 when it's a new one (counted), 0 when it doesn't apply."""
        if a in parent or not p or p == a or p not in acc or under(a, p):
            return 0
        clues.setdefault(a, {}).setdefault(p, [])
        if any(k == kind for k, _ in clues[a][p]):
            return 0
        clues[a][p].append((kind, text))
        return 1

    def groups(key: dict[str, str | None], kind: str, text) -> int:
        by: dict[str, list[str]] = {}
        for i, k in key.items():
            if k:
                by.setdefault(k, []).append(i)
        found = 0
        for k, ids in by.items():
            if len(ids) < 2 or len(ids) > 200:  # one Account, or a value shared too widely to mean anything
                continue
            head = min(ids, key=rank)
            for i in ids:
                if i != head:
                    found += add(i, head, kind, text(k))
        return found

    counts: dict[str, int] = {}
    # 1. the same website domain, or the same domain as the Account's Contacts' email
    web = {i: _domain(r.get("Website")) for i, r in acc.items()}
    counts["domain"] = groups(web, "domain", lambda d: f"Same website domain {d}")
    mail: dict[str, str] = {}
    try:
        tally: dict[str, dict[str, int]] = {}
        for c in ctx.rows("SELECT AccountId, Email FROM Contact WHERE AccountId != null AND Email != null", GUESS_CONTACTS):
            d = _domain(c.get("Email"))
            if d and c.get("AccountId") in acc:
                tally.setdefault(c["AccountId"], {})[d] = tally.get(c["AccountId"], {}).get(d, 0) + 1
        mail = {a: max(t, key=t.get) for a, t in tally.items()}
    except SalesforceAuthExpired:
        raise
    except (SalesforceError, Unavailable):
        pass
    # an Account's Contacts' domain, with the Accounts whose website is on one of those domains
    used = set(mail.values())
    by_mail = {**{i: d for i, d in web.items() if d in used}, **mail}
    counts["contacts"] = groups(by_mail, "contacts", lambda d: f"Contacts’ email domain {d} matches")
    # 2. the same name once legal words, places and suffixes are dropped, or a name that contains another Account's name
    by_clean: dict[str, list[str]] = {}
    for i, words in clean.items():
        if words and any(w not in _COMMON for w in words) and len(" ".join(words)) >= 4:
            by_clean.setdefault(" ".join(words), []).append(i)
    counts["name"] = groups({i: " ".join(w) for i, w in clean.items() if " ".join(w) in by_clean}, "name",
                            lambda k: f"Same name once Inc, Corp, places and suffixes are dropped (“{k}”)")
    for i, words in clean.items():
        if i in parent:
            continue
        for size in range(len(words) - 1, 0, -1):
            for start in range(0, len(words) - size + 1):
                for p in by_clean.get(" ".join(words[start:start + size]), []):
                    counts["name"] += add(i, p, "name", f"Name contains “{name[p]}”")
    # 3. a sibling (the same first word) that already has a parent
    brand = {i: w[0] for i, w in clean.items() if w and w[0] not in _COMMON and len(w[0]) >= 3}
    taken: dict[str, dict[str, int]] = {}
    for i, b in brand.items():
        if i in parent:
            taken.setdefault(b, {})[parent[i]] = taken.get(b, {}).get(parent[i], 0) + 1
    counts["sibling"] = 0
    for i, b in brand.items():
        if i not in parent and b in taken:
            p = max(taken[b], key=lambda x: (taken[b][x], -order.get(x, 0)))
            sib = next(s for s, bb in brand.items() if bb == b and parent.get(s) == p)
            counts["sibling"] += add(i, p, "sibling", f"Sibling “{name[sib]}” already has “{name.get(p, p)}” as parent")
    # 4. the same main phone, or the same billing street and postal code
    counts["phone"] = groups({i: _phone(r.get("Phone")) for i, r in acc.items()}, "phone", lambda p: f"Same phone ({p})")
    street = {i: (re.sub(r"\W+", " ", (r.get("BillingStreet") or "").lower()).strip(), (r.get("BillingPostalCode") or "").strip().lower())
              for i, r in acc.items()}
    counts["address"] = groups({i: f"{s}|{z}" if s and z else None for i, (s, z) in street.items()}, "address",
                               lambda k: f"Same billing address ({k.replace('|', ', ')})")
    # 5. D&B: the parent or HQ DUNS is another Account's DUNS
    counts["duns"] = 0
    if duns_parent:
        by_duns = {r["DunsNumber"]: i for i, r in acc.items() if r.get("DunsNumber")}
        for i, r in acc.items():
            pd = (r.get("DandbCompany") or {}).get("ParentOrHqDunsNumber")
            if pd and by_duns.get(pd) not in (None, i):
                counts["duns"] += add(i, by_duns[pd], "duns", f"D&B parent DUNS {pd} is “{name[by_duns[pd]]}”")
    # 6. Ownership = Subsidiary with no Parent Account
    subsidiary = [i for i, r in acc.items() if i not in parent and (r.get("Ownership") or "").strip().lower() == "subsidiary"]

    guesses: dict[str, dict] = {}
    for a in set(clues) | set(subsidiary):
        best, why = None, []
        if clues.get(a):
            best = min(clues[a], key=lambda p: (-sum(_STRENGTH[k] for k, _ in clues[a][p]), rank(p)))  # most clues, then the likeliest parent
            why = clues[a][best]
        kinds = {k for k, _ in why}
        sub = a in subsidiary
        strong = len(kinds & {"domain", "contacts", "name"})
        level = ("High" if sub or kinds & {"sibling", "duns"} or strong >= 2 else "Low" if kinds <= {"phone", "address"} and not strong
                 else "Medium")
        texts = (["Ownership is Subsidiary, but Parent Account is empty"] if sub else []) + [t for _, t in why]
        guesses[a] = {"parent": name.get(best) if best else None, "why": "\n".join(texts), "confidence": level,
                      "rank": {"High": 0, "Medium": 1, "Low": 2}[level]}
    ids = sorted(guesses, key=lambda a: (guesses[a]["rank"], name[a].lower()))
    by_level = {lv: sum(1 for g in guesses.values() if g["confidence"] == lv) for lv in ("High", "Medium", "Low")}
    m = ctx.metric(
        label, len(ids), "count", "lower-better", None,
        how="Accounts with no Parent Account that probably belong under another Account, guessed from clues in the data: "
        "Ownership is Subsidiary; a sibling (the same first word) already has a parent; the same website domain or Contact email "
        "domain; a name that contains another Account’s name (after dropping Inc, Corp, places like West or UK, and “- …” suffixes); "
        "the same main phone or billing address; or a D&B parent DUNS. The suggested parent is the Account with children, "
        "then the shortest name, then the oldest.",
        rule="Shown for review, not scored: these are suggestions. High = Subsidiary, a sibling’s parent, D&B, or two strong clues "
        "agree; Medium = one domain or name clue; Low = only the phone or address matches.",
        columns=["Name", "Website", "Phone", "Ownership", "OwnerId"],
        order="Name",
        extra="parent_guess",
        criteria=[
            ("Records checked", f"{len(acc):,} Accounts" + (f" (the first {GUESS_ROWS:,})" if len(rows) >= GUESS_ROWS else "")
             + f", {len(acc) - len(parent):,} of them with no Parent Account"),
            ("Clues found", f"Subsidiary {len(subsidiary):,} · sibling {counts['sibling']:,} · website domain {counts['domain']:,} · "
             f"Contact email domain {counts['contacts']:,} · name {counts['name']:,} · phone {counts['phone']:,} · "
             f"address {counts['address']:,}" + (f" · D&B {counts['duns']:,}" if duns_parent else "")),
            ("Ignored", "Personal email and website domains (gmail.com, outlook.com, example.com…), very common words "
             "(Global, Services, Solutions…) and values shared by more than 200 Accounts"),
            ("What's counted", f"{len(ids):,} Accounts may be missing their Parent Account: High {by_level['High']:,}, "
             f"Medium {by_level['Medium']:,}, Low {by_level['Low']:,}"),
            ("Records listed", f"The most likely first (up to {GUESS_LISTED:,}), each with its suggested parent, why and how sure"),
        ],
        records=("Account", ctx.ids_in(ids, GUESS_LISTED)) if ids else None,
        recent=False,
    )
    if m.records:
        m.records[0]["reasons"] = {a: guesses[a] for a in ids[:GUESS_LISTED]}
    if by_level["High"]:
        ctx.finding(
            name="Accounts that may be missing their Parent Account",
            records=("Account", ctx.ids_in([a for a in ids if guesses[a]["confidence"] == "High"], GUESS_LISTED)),
            recent=False,
            score=90,
            min_score=101,  # raised for review whenever there's a likely one
            severity="low",
            affected=by_level["High"],
            description=f"{by_level['High']:,} Accounts with no Parent Account very likely belong under another Account "
            f"({len(ids):,} possible in all).",
            why="An Account left out of its company hierarchy isn’t counted in its parent’s totals, account plans or territory, "
            "and the team working the parent can’t see it.",
            impact="Parent company revenue, pipeline and activity that look smaller than they are.",
            action="Check each suggestion and set the Parent Account in Salesforce where it’s right.",
            obj="Account",
            url=ctx.list_url("Account"),
            measure=label,
        )


# Signs an Account is inactive: a yes/no "Active" field set to No, a status field set to an inactive value, or its name.
INACTIVE_VALUES = ("No", "False", "N", "Inactive", "Closed", "Defunct", "Dormant", "Obsolete", "Out of Business", "Dissolved",
                   "Former Customer", "Do Not Use")
INACTIVE_NAMES = ("Inactive", "Defunct", "Closed", "Obsolete", "Dormant", "Do Not Use", "Out of Business", "Dissolved")


def _inactive_parent(ctx: Ctx) -> tuple[str, list[str]]:
    """(SOQL condition on Account.Parent, the signs it uses in words): the Parent Account is inactive."""
    fields = ctx.fields("Account")
    conds: list[str] = []
    signs: list[str] = []
    for name, f in fields.items():
        low, label = name.lower(), (f.get("label") or name).lower()
        if not f.get("filterable", True):
            continue
        if low in ("active__c", "isactive__c", "is_active__c", "account_active__c") or label in ("active", "is active", "account active"):
            if f.get("type") == "boolean":
                conds.append(f"Parent.{name} = false")
                signs.append(f"{f.get('label') or name} is unticked")
            elif f.get("type") in ("picklist", "string"):
                conds.append(f"Parent.{name} IN ('No', 'False', 'N', 'Inactive')")
                signs.append(f"{f.get('label') or name} is No")
        elif f.get("type") == "picklist" and "status" in low:
            hits = [v["value"] for v in f.get("picklistValues") or [] if v.get("value") and v["value"].strip().lower() in {x.lower() for x in INACTIVE_VALUES}]
            if hits:
                conds.append(f"Parent.{name} IN ({', '.join(soql_str(v) for v in hits)})")
                signs.append(f"{f.get('label') or name} is " + " or ".join(hits))
    conds += [f"Parent.Name LIKE '%{w}%'" for w in INACTIVE_NAMES]
    signs.append("its name says " + ", ".join(f"“{w}”" for w in INACTIVE_NAMES))
    return f"({' OR '.join(conds)})", signs


def inactive_parents(ctx: Ctx) -> None:
    """Child Accounts Under Inactive Parents: Accounts whose Parent Account is inactive (an Active field set to No, an
    inactive status, or a name such as “Defunct” or “Closed”), so they roll up to a company that no longer trades."""
    label = "Child Accounts Under Inactive Parents"
    if not ctx.has_field("Account", "ParentId"):
        raise Unavailable("Accounts in this org have no Parent Account field, so there are no parent Accounts to check.")
    cond, signs = _inactive_parent(ctx)
    children = ctx.count("Account", "ParentId != null", recent=False)
    n = ctx.count("Account", "ParentId != null", cond, recent=False) if children else 0
    score = rate_score(n / children, 0.2) if children else 100
    ctx.metric(
        label, n, "count", "lower-better", score,
        how="Child Accounts whose Parent Account is inactive, so they roll up to a company that no longer trades or shouldn’t be "
        "used. A Parent Account counts as inactive when " + "; or ".join(signs) + ".",
        rule="100 when no child Account sits under an inactive parent, falling evenly to 0 when 20% of child Accounts do.",
        columns=["ParentId", "Name", "Industry", "Type", "OwnerId"],
        order="Parent.Name",  # grouped by the inactive parent
        extra="inactive_parent",
        criteria=[
            ("Records checked", f"{children:,} Accounts with a Parent Account"),
            ("Inactive parent", "The Parent Account " + "; or ".join(signs)),
            ("What's counted", f"{n:,} of {children:,} child Accounts ({pct(n, children):.0f}%) are under an inactive Parent Account"),
            ("Records listed", "Every child Account under an inactive parent, with that parent first"),
        ],
        records=("Account", "ParentId != null", cond),
        recent=False,
    )
    if n:
        ctx.finding(
            name="Child Accounts under inactive parent Accounts",
            records=("Account", "ParentId != null", cond),
            recent=False,
            score=score,
            affected=n,
            description=f"{n:,} of {children:,} child Accounts ({pct(n, children):.0f}%) have an inactive Parent Account.",
            why="A child Account under a closed or defunct parent rolls up to the wrong company, so hierarchy reports and "
            "account plans show business under a company that no longer exists.",
            impact="Revenue and activity credited to the wrong parent, and live customers hidden under inactive ones.",
            action="Move each child Account to its current parent (or clear Parent Account), or reactivate the parent if it’s still in business.",
            obj="Account",
            url=ctx.list_url("Account"),
            measure=label,
        )


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
    ctx.metric(
        "Stuck Opportunities", n, "count", "lower-better", score,
        how=f"Open Opportunities that {how}.",
        rule="100 when no open deals are stuck, falling evenly to 0 when 40% of open deals are.",
        columns=["Name", "StageName", "LastStageChangeDate", "LastModifiedDate", "Amount", "CloseDate", "OwnerId"],
        order="CloseDate",
        criteria=[
            ("Records checked", f"{total:,} open Opportunities"),
            ("Field checked", "Last Stage Change Date (or Created Date if the stage never changed)" if "LastStageChangeDate" in cond
             else "Last Modified Date (this org has no Last Stage Change Date)"),
            ("Stuck", f"The deal {how}"),
            ("What's counted", f"{n:,} of {total:,} open Opportunities ({pct(n, total):.0f}%) are stuck"),
            ("Records listed", "Every stuck open Opportunity, earliest close date first"),
        ],
        records=("Opportunity", OPEN_OPPS, cond),
    )
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
    ctx.metric(
        "Missing Next Steps", n, "count", "lower-better", score,
        how="Open Opportunities with an empty Next Step field.",
        rule="100 when every open deal has a next step, falling evenly to 0 when 60% of open deals have none.",
        columns=["Name", "NextStep", "StageName", "CloseDate", "Amount", "OwnerId"],
        order="CloseDate",
        criteria=[
            ("Records checked", f"{total:,} open Opportunities"),
            ("Field checked", "Next Step"),
            ("Missing", "Next Step is empty"),
            ("What's counted", f"{n:,} of {total:,} open Opportunities ({pct(n, total):.0f}%) have no next step"),
            ("Records listed", "Every open Opportunity with no next step, by close date"),
        ],
        records=("Opportunity", OPEN_OPPS, "NextStep = null"),
    )
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
        ctx.metric(
            "Missing Closed Lost reasons", lost, "count", "lower-better", 40 if lost else 70,
            how="Opportunities have no field for why a deal was lost, so we count every deal lost (closed and not won) with a close date in the last 90 days: none of them can have a reason.",
            rule="A fixed score: 40 if any deals were lost in the last 90 days, 70 if none were.",
            columns=["Name", "StageName", "CloseDate", "Amount", "OwnerId"],
            order="CloseDate",
            criteria=[
                ("Records checked", "Opportunities that are Closed Lost (closed and not won) with a close date in the last 90 days"),
                ("Field checked", "A lost-reason field (a field whose name or label mentions lost/loss and reason): none exists"),
                ("What's counted", f"All {lost:,} lost deals, since none can have a reason recorded"),
                ("Records listed", "Every deal lost in the last 90 days, by close date"),
            ],
            records=("Opportunity", *lost_conds),
        )
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
    ctx.metric(
        "Missing Closed Lost reasons", n, "count", "lower-better", score,
        how=f"Deals lost (closed and not won) with a close date in the last 90 days where {fields[reason].get('label') or reason} is empty.",
        rule="100 when every lost deal has a reason, falling evenly to 0 when 50% of lost deals have none.",
        columns=[reason, "Name", "StageName", "CloseDate", "Amount", "OwnerId"],
        order="CloseDate",
        criteria=[
            ("Records checked", f"{lost:,} Opportunities that are Closed Lost with a close date in the last 90 days"),
            ("Field checked", f"{fields[reason].get('label') or reason}"),
            ("Missing", f"{fields[reason].get('label') or reason} is empty"),
            ("What's counted", f"{n:,} of {lost:,} lost deals ({pct(n, lost):.0f}%) have no reason"),
            ("Records listed", "Every lost deal with no reason, by close date"),
        ],
        records=("Opportunity", *lost_conds, f"{reason} = null"),
    )
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
        ctx.metric(
            "Sales stage guidance gaps", len(stages), "count", "lower-better", 30 if stages else 100,
            how="Sales Path isn’t turned on for Opportunities, so every open (not closed) sales stage counts as having no on-screen guidance.",
            rule="A fixed score: 30 when there are open sales stages but no active Path, 100 when there are no open stages.",
            criteria=[
                ("Checked", "Active Sales Paths in Setup for Opportunities: none found"),
                ("Stages", f"{len(stages)} active, open (not closed) sales stages"),
                ("What's counted", f"All {len(stages)} open stages, since without a Path none has on-screen guidance"),
            ],
        )
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
    ctx.metric(
        "Sales stage guidance gaps", len(gaps), "count", "lower-better", score,
        how=f"Of your {len(stages)} open (not closed) sales stages, the ones with no “Guidance for Success” text on the Opportunity Path.",
        rule="100 when every open stage has guidance, falling evenly to 0 when none of them do (100%).",
        criteria=[
            ("Checked", f"{len(paths)} active Opportunity Path(s) and their “Guidance for Success” text"),
            ("Stages", f"{len(stages)} active, open (not closed) sales stages"),
            ("Gap", "A stage with no guidance text on any Path (empty or only spaces counts as none)"),
            ("What's counted", f"{len(gaps)} of {len(stages)} open stages have no guidance" + (f": {', '.join(map(str, gaps[:6]))}" if gaps else "")),
        ],
    )
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
    ctx.metric(
        "Missing sales activities", len(quiet), "count", "lower-better", score,
        how="Active people who own open Opportunities or Leads (bots and integration users left out) who logged no tasks or events in the last 14 days.",
        rule="100 when everyone logged activity, falling evenly to 0 when 50% of these people logged none.",
        columns=["Name", "Username", "LastLoginDate"],
        order="Name",
        criteria=[
            ("People checked", f"{len(reps)} active users who own at least one open Opportunity or open Lead"),
            ("Left out", "Queues, non-standard users, names with integration/automated/Einstein/Agentforce/bot, and integration, API-only, automated or Chatter profiles"),
            ("Activity checked", "Tasks and Events they own, created in the last 14 days"),
            ("What's counted", f"{len(quiet)} of {len(reps)} people logged none"),
            ("Records listed", "Each of those people, by name (up to 200)"),
        ],
        records=("User", ctx.ids_in(quiet_ids)),
        recent=False,
    )
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
    ctx.metric(
        "Web-to-Lead issues", issues, "count", "lower-better", score,
        how=f"Leads with a website lead source ({', '.join(values[:3])}) created in the last 14 days, compared with the 11 weeks before. The number is 1 when website leads have stopped or never arrived.",
        rule="100 when website leads are still arriving, 25 when they stopped in the last 14 days after arriving before, and 70 when none arrived in the last 90 days. A problem is raised whenever website leads have stopped arriving.",
        columns=["Name", "Company", "LeadSource", "CreatedDate", "Status", "OwnerId"],
        order="CreatedDate",
        criteria=[
            ("Records checked", "All Leads (open or converted) created in the last 90 days"),
            ("Website sources", f"Lead Source is one of: {', '.join(map(str, values[:10]))}"),
            ("Last 14 days", f"{recent:,} website leads"),
            ("11 weeks before", f"{before:,} website leads"),
            ("Flagged when", "None in the last 14 days but some before (the web form may be broken), or none at all in 90 days"),
            ("Records listed", "Website leads created in the last 90 days, newest last"),
        ],
        records=("Lead", f"LeadSource IN ({in_list})", "CreatedDate = LAST_N_DAYS:90"),
        recent=False,
    )


def email_templates(ctx: Ctx) -> None:
    if not ctx.has_object("EmailTemplate"):
        raise Unavailable("Email templates can’t be read with this user.")
    n = ctx.count("EmailTemplate", "IsActive = true", recent=False)
    score = 100 if n >= 5 else 70 if n else 30
    ctx.metric(
        "Email template availability", n, "count", "higher-better", score,
        how="Active email templates your team can use.",
        rule="100 with 5 or more active templates, 70 with 1 to 4, and 30 with none.",
        columns=["Name", "FolderName", "IsActive"],
        order="Name",
        criteria=[
            ("Records checked", "Email templates (all types and folders)"),
            ("Counted", "Templates marked Active"),
            ("What's counted", f"{n:,} active templates"),
            ("Flagged when", "Fewer than 5 active templates"),
            ("Records listed", "Every active email template, by name"),
        ],
        records=("EmailTemplate", "IsActive = true"),
        recent=False,
    )
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
    ctx.metric(
        "Activity capture gaps", n, "count", "lower-better", score,
        how="Open Opportunities with no logged activity (tasks, calls, meetings) in the last 30 days.",
        rule="100 when every open deal has recent activity, falling evenly to 0 when 60% of open deals have none.",
        columns=["Name", "LastActivityDate", "StageName", "CloseDate", "Amount", "OwnerId"],
        order="LastActivityDate",
        criteria=[
            ("Records checked", f"{total:,} open Opportunities"),
            ("Field checked", "Last Activity Date (the latest task or event logged on the deal)"),
            ("Gap", "No activity ever, or none in the last 30 days"),
            ("What's counted", f"{n:,} of {total:,} open Opportunities ({pct(n, total):.0f}%) have no recent activity"),
            ("Records listed", "Every such open Opportunity, oldest activity first (deals with no activity ever come last)"),
        ],
        records=("Opportunity", OPEN_OPPS, cond),
    )
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
    ctx.metric(
        "Missing validation rules", len(missing), "count", "lower-better", 100 - 20 * len(missing),
        how="Of Accounts, Contacts, Leads and Opportunities, how many have no active validation rules.",
        rule="Starts at 100 and drops 20 points for each of these objects with no active validation rules.",
        criteria=[
            ("Objects checked", ", ".join(CORE) + " (those this user can see)"),
            ("Checked", "Active validation rules on each object in Setup"),
            ("What's counted", f"{len(missing)} object(s) with none" + (f": {', '.join(missing)}" if missing else "")),
            ("Vague messages", f"{len(vague)} active rule(s) have an error message under 20 characters or a generic one like “Error” or “Invalid”. Reported, but not scored"),
        ],
    )
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
    ctx.metric(
        "Required field gaps", len(gaps), "count", "lower-better", score,
        how=f"Key fields that aren’t required (like Amount and Next Step on open Opportunities, Email and Phone on open Leads, Email and Account on Contacts, Industry and Type on Accounts) and are filled in on less than 80% of records. We checked {checked} fields.",
        rule="100 when none of the checked fields are under 80% filled, falling evenly to 0 when 60% of them are.",
        criteria=[
            ("Fields checked", "Opportunity: Amount, Next Step, Lead Source, Type (open deals). Lead: Email, Phone, Lead Source (open Leads). "
             "Contact: Email, Account. Account: Industry, Phone, Type"),
            ("Skipped", "Fields that are missing, can't be filtered, or are already required"),
            ("Gap", "The field is filled in on less than 80% of records"),
            ("What's counted", f"{len(gaps)} of {checked} fields checked" + (f": {', '.join(gaps[:8])}" if gaps else "")),
        ],
    )
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
    ctx.metric(
        "Potential junk data", total_junk, "count", "lower-better", score,
        how="Records with placeholder values like “test”, “na” or “tbd”: in Next Step or Description on the 2,000 most recently changed open Opportunities, Company on open Leads, Last Name on Contacts, and Name on Accounts.",
        rule="100 when no checked records hold placeholder values, falling evenly to 0 when 10% of them do.",
        criteria=[
            ("Records checked", f"{checked:,} records: the 2,000 most recently changed open Opportunities, plus open Leads, Contacts and Accounts"),
            ("Fields checked", "Opportunity Next Step and Description, Lead Company, Contact Last Name, Account Name"),
            ("Junk value", "The whole value (ignoring case and spaces) is a placeholder like test, na, n/a, tbd, none, -, x, asdf, 123, unknown, dummy, sample, temp"),
            ("What's counted", f"{total_junk:,} records with a placeholder" + (f": {'; '.join(found)}" if found else "")),
        ],
    )
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
    ctx.metric(
        "Layout usability concerns", len(concerns), "count", "lower-better", 100 - 15 * min(len(concerns), 6),
        how="For Accounts, Contacts, Leads and Opportunities, we flag each object with more than 100 custom fields or more than 5 page layouts.",
        rule="Starts at 100 and drops 15 points for each concern, down to 10 after 6 or more concerns.",
        criteria=[
            ("Objects checked", ", ".join(CORE)),
            ("Too many fields", "More than 100 custom fields on the object"),
            ("Too many layouts", "More than 5 page layouts on the object"),
            ("What's counted", f"{len(concerns)} concern(s)" + (f": {'; '.join(concerns)}" if concerns else "")),
        ],
    )
    if concerns:
        _setting(
            ctx,
            "Crowded or fragmented page layouts",
            "Some pages are likely hard to use: " + "; ".join(concerns) + ".",
            "Simplify with Dynamic Forms (show fields only when relevant), group fields into tabs, and consolidate similar layouts.",
            severity="low",
        )


AREAS = {
    "area-3": [stuck_queue_leads, inactive_rules, criteria_mismatches, lead_no_activity, stale_leads],
    "area-4": [accounts_without_contacts, hierarchy_chains, inactive_parents, missing_parents,  # Accounts first, then Contacts
               contact_roles, orphaned_contacts, multiple_accounts, multi_deal_contacts],
    "area-5": [stuck_opportunities, missing_next_steps, closed_lost_reasons, stage_guidance],
    "area-6": [missing_sales_activities, web_to_lead, email_templates, activity_capture],
    "area-7": [validation_rules, required_field_gaps, junk_data, layout_usability],
}

STEP_LABELS = {
    stuck_queue_leads: "Finding Leads stuck in queues",
    inactive_rules: "Checking inactive Lead Assignment Rules",
    criteria_mismatches: "Checking Leads against the active assignment rule",
    lead_no_activity: "Finding Leads with no activity in 6 months",
    stale_leads: "Finding stale Leads",
    contact_roles: "Checking contact roles on deals",
    orphaned_contacts: "Finding Contacts without an Account",
    multiple_accounts: "Checking Contacts to Multiple Accounts",
    multi_deal_contacts: "Finding Contacts on several deals",
    accounts_without_contacts: "Finding Accounts without Contacts",
    hierarchy_chains: "Following Account hierarchies",
    inactive_parents: "Finding Accounts under inactive parents",
    missing_parents: "Looking for missing Parent Accounts",
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
