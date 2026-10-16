"""Built-in fix playbooks and effort estimates.

Everything here is fixed rules written by consultants — the platform doesn't use AI services.
"""
import math
import re

from .models import FindingRow


# ---------------------------------------------------------------- built-in playbooks

# Extra steps for common problems (matched on the problem name). Everything else gets the generic plan.
PLAYBOOKS: list[tuple[str, list[tuple[str, str]]]] = [
    (r"^Duplicate", [
        ("Agree the matching rule", "Decide what makes two records the same (e.g. normalised company name + website, or email) and which record wins."),
        ("Merge the existing copies", "Use the record list here to merge in batches, starting with records that have open deals or recent activity."),
        ("Block new duplicates", "Turn on a Duplicate Rule with an Alert or Block action for the same matching rule, including for imports and integrations."),
    ]),
    (r"without (an )?email|Missing Email|no email", [
        ("Find the source", "Check where these records were created (web form, import, integration, manual) — the export shows Created By."),
        ("Backfill the important ones", "Prioritise records with open deals or recent activity; use enrichment if you have it."),
        ("Make it required where it matters", "Require email on the web form and at the stage where you first email the person."),
    ]),
    (r"Reps whose pipeline|stale|Stuck|stuck", [
        ("Review with each owner", "Go through the list in the next 1:1: close dead deals as lost (with a reason) and set a real next step and close date on live ones."),
        ("Set a weekly habit", "Give reps a list view of deals not updated in 30 days and review it in the weekly pipeline meeting."),
        ("Automate a nudge", "Add a scheduled flow that emails the owner when a deal hasn’t changed in 21 days."),
    ]),
    (r"Paid licenses|licen", [
        ("Confirm who still needs access", "Send the list to team leads; freeze leavers immediately (Freeze keeps their data)."),
        ("Reassign their records", "Move open leads, deals and tasks to active owners before deactivating."),
        ("Reclaim or downgrade", "Deactivate unneeded users and talk to your Salesforce account executive about reducing licences at renewal."),
    ]),
    (r"discount|approval", [
        ("Agree discount guardrails", "Set maximum discounts by product family and deal size with sales leadership and finance."),
        ("Enforce them", "Add an approval process (or CPQ Advanced Approvals) for anything above the guardrail and lock price fields once approved."),
        ("Report monthly", "Track discount % by rep and product; review outliers in the monthly business review."),
    ]),
    (r"Process Builder|Workflow Rules|automated by several", [
        ("Inventory per object", "List every automation on each object (flows, triggers, Process Builders, workflow rules) and what it does."),
        ("Migrate with the tool", "Use Setup → Migrate to Flow, one object at a time, and consolidate into one before-save and one after-save flow."),
        ("Test and switch over", "Test in a sandbox with real scenarios, deploy, then deactivate the old automation."),
    ]),
    (r"CPQ", [
        ("Inventory and prune", "Export price rules, product rules, scripts and approval rules; retire anything unused."),
        ("Size the move", "Map what remains to Revenue Cloud capabilities and estimate effort with your implementation partner."),
        ("Plan around renewal", "Agree timeline and budget before your next Salesforce renewal so you aren’t forced into a rushed migration."),
    ]),
]


def _generic(f: FindingRow) -> list[tuple[str, str]]:
    steps = []
    if f.records_object:
        steps.append(("See exactly what’s affected", f"Open “Affected records” on this problem (or download the CSV) — {f.affected_records:,} records are listed with links into Salesforce."))
    if f.fix_url:
        steps.append(("Make the change in Salesforce", "Use “Fix it in Salesforce” to open the right setup page."))
    steps.append(("Fix the cause", f.recommended_action))
    steps.append(("Check it worked", "Run this area again; the problem shows as Better or moves to “Fixed since last check”."))
    return steps


def playbook(f: FindingRow) -> dict:
    extra = next((s for pattern, s in PLAYBOOKS if re.search(pattern, f.name, re.I)), [])
    steps = _generic(f)
    if extra:
        steps = steps[:1] + extra + steps[-1:]
    return {
        "summary": f"{f.description} {f.why_it_matters}",
        "steps": [{"title": t, "detail": d} for t, d in steps],
        "risks": "Change data in small batches and keep the CSV export as a backup before bulk updates or merges.",
        "effortHours": estimate_hours(f),
    }


def estimate_hours(f: FindingRow) -> float:
    """Rough consultant effort to fix a problem (used for proposals; meant to be adjusted)."""
    sev = {"critical": 6, "high": 4, "medium": 3, "low": 2}.get(f.severity, 3)
    name = f.name
    n = f.affected_records or 0
    if re.search(r"CPQ", name):
        return 40.0
    if re.search(r"Process Builders and Workflow Rules", name):
        return float(min(120, 3 * max(n, 1)))
    if re.search(r"Nearly empty fields", name):
        return float(min(60, 1.5 * max(n, 1)))
    if re.search(r"Permission sets nobody uses|help text|list views", name, re.I):
        return float(min(16, 2 + 0.1 * n))
    if not f.records_object:  # a setting or design change
        return float({"critical": 8, "high": 6, "medium": 4, "low": 2}.get(f.severity, 4))
    return round(min(40.0, sev + 3 * math.log10(n + 1)), 1)
