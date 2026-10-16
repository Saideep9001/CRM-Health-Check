"""Fixed, read-only Salesforce lookups for the help assistant ("Ask Aqua").

The browser sends only a question id; every SOQL string lives here and is never built
from user text. Queries run with the connected user's token, so Salesforce sharing rules
and field-level security still apply. Ids must match src/config/crmQuestions.ts.
"""
from collections.abc import Callable
from datetime import date, datetime, timezone

from .client import SalesforceClient

LIST_LIMIT = 10
Row = dict


def n(v) -> str:
    try:
        return f"{round(float(v or 0)):,}"
    except (TypeError, ValueError):
        return "0"


def d(v) -> str:
    if not v:
        return "—"
    try:
        dt = date.fromisoformat(str(v)[:10])
        return f"{dt.strftime('%b')} {dt.day}, {dt.year}"
    except ValueError:
        return str(v)


def s(v, fallback: str = "—") -> str:
    return fallback if v in (None, "") else str(v)


def rel(r: dict, key: str, fallback: str) -> str:
    """Name of a related record, e.g. Owner.Name."""
    obj = r.get(key)
    return s(obj.get("Name") if isinstance(obj, dict) else None, fallback)


def plural(count: int, one: str, many: str | None = None) -> str:
    return f"{n(count)} {one if count == 1 else (many or one + 's')}"


class Lookup:
    def __init__(self, sf: SalesforceClient):
        self.sf = sf
        self.base = sf.base

    def record_url(self, obj: str, rid) -> str:
        return f"{self.base}/lightning/r/{obj}/{rid}/view"

    def list_url(self, obj: str) -> str:
        return f"{self.base}/lightning/o/{obj}/list"

    def count(self, soql: str) -> int:
        return int(self.sf.query(soql).get("totalSize", 0))

    def records(self, soql: str) -> list[dict]:
        return self.sf.query(soql).get("records", [])

    def count_and_list(self, obj: str, fields: str, where: str, order: str, row: Callable[[dict], Row]) -> dict:
        total = self.count(f"SELECT COUNT() FROM {obj} WHERE {where}")
        recs = self.records(f"SELECT Id, {fields} FROM {obj} WHERE {where} ORDER BY {order} LIMIT {LIST_LIMIT}")
        return {
            "total": total,
            "rows": [{**row(r), "url": self.record_url(obj, r.get("Id"))} for r in recs],
            "salesforce_url": self.list_url(obj),
        }


# ---------------------------------------------------------------------------
# Lookups — one function per question id.
# ---------------------------------------------------------------------------


def leads_open(q: Lookup) -> dict:
    total = q.count("SELECT COUNT() FROM Lead WHERE IsConverted = false")
    return {"title": "Open leads", "summary": f"You have **{plural(total, 'open lead')}** (not yet converted).", "total": total, "rows": [], "salesforce_url": q.list_url("Lead")}


def leads_new(q: Lookup) -> dict:
    x = q.count_and_list(
        "Lead", "Name, Company, LeadSource, CreatedDate", "CreatedDate = THIS_MONTH", "CreatedDate DESC",
        lambda r: {"label": s(r.get("Name")), "detail": f"{s(r.get('Company'), 'No company')} · {s(r.get('LeadSource'), 'No source')} · {d(r.get('CreatedDate'))}"},
    )
    return {"title": "New leads this month", "summary": f"**{plural(x['total'], 'new lead')}** so far this month.", **x}


def leads_unassigned(q: Lookup) -> dict:
    x = q.count_and_list(
        "Lead", "Name, Company, Owner.Name, CreatedDate", "IsConverted = false AND Owner.Type = 'Queue'", "CreatedDate ASC",
        lambda r: {"label": s(r.get("Name")), "detail": f"{s(r.get('Company'), 'No company')} · waiting in {rel(r, 'Owner', 'a queue')} since {d(r.get('CreatedDate'))}"},
    )
    t = x["total"]
    summary = f"**{plural(t, 'lead')}** {'is' if t == 1 else 'are'} sitting in a queue with no salesperson. Oldest first:" if t else "Every open lead has a salesperson. Nice!"
    return {"title": "Unassigned leads", "summary": summary, **x}


def leads_stale(q: Lookup) -> dict:
    x = q.count_and_list(
        "Lead", "Name, Company, Owner.Name, LastModifiedDate", "IsConverted = false AND LastModifiedDate < LAST_N_DAYS:30", "LastModifiedDate ASC",
        lambda r: {"label": s(r.get("Name")), "detail": f"{s(r.get('Company'), 'No company')} · {rel(r, 'Owner', 'No owner')} · last updated {d(r.get('LastModifiedDate'))}"},
    )
    t = x["total"]
    summary = f"**{plural(t, 'open lead')}** haven’t been updated in over 30 days. Oldest first:" if t else "No open leads have gone quiet. Great!"
    return {"title": "Quiet leads (30+ days)", "summary": summary, **x}


def leads_by_source(q: Lookup) -> dict:
    recs = q.records("SELECT LeadSource, COUNT(Id) total FROM Lead WHERE CreatedDate = LAST_N_DAYS:90 GROUP BY LeadSource ORDER BY COUNT(Id) DESC LIMIT 10")
    total = sum(int(r.get("total") or 0) for r in recs)
    rows = [{"label": s(r.get("LeadSource"), "No source recorded"), "detail": f"{n(r.get('total'))} ({round(int(r.get('total') or 0) / total * 100) if total else 0}%)"} for r in recs]
    summary = f"**{plural(total, 'lead')}** in the last 90 days:" if total else "No leads were created in the last 90 days."
    return {"title": "Where leads came from (last 90 days)", "summary": summary, "total": total, "rows": rows, "salesforce_url": q.list_url("Lead")}


def opps_open(q: Lookup) -> dict:
    r = (q.records("SELECT COUNT(Id) deals, SUM(Amount) amount FROM Opportunity WHERE IsClosed = false") or [{}])[0]
    deals = int(r.get("deals") or 0)
    return {"title": "Open pipeline", "summary": f"You have **{plural(deals, 'open deal')}** worth **{n(r.get('amount'))}** in total.", "total": deals, "rows": [], "salesforce_url": q.list_url("Opportunity")}


def _deal_row(prefix: str) -> Callable[[dict], Row]:
    return lambda r: {"label": s(r.get("Name")), "detail": f"{n(r.get('Amount'))} · {s(r.get('StageName'))} · {prefix} {d(r.get('CloseDate'))} · {rel(r, 'Owner', 'No owner')}"}


def opps_closing_this_month(q: Lookup) -> dict:
    x = q.count_and_list("Opportunity", "Name, Amount, StageName, CloseDate, Owner.Name", "IsClosed = false AND CloseDate = THIS_MONTH", "CloseDate ASC", _deal_row("closes"))
    t = x["total"]
    summary = f"**{plural(t, 'open deal')}** {'is' if t == 1 else 'are'} due to close this month:" if t else "No open deals are due to close this month."
    return {"title": "Deals closing this month", "summary": summary, **x}


def opps_overdue(q: Lookup) -> dict:
    x = q.count_and_list("Opportunity", "Name, Amount, StageName, CloseDate, Owner.Name", "IsClosed = false AND CloseDate < TODAY", "CloseDate ASC", _deal_row("was due"))
    t = x["total"]
    summary = (
        f"**{plural(t, 'deal')}** {'is' if t == 1 else 'are'} still open past {'its' if t == 1 else 'their'} close date. Most overdue first:"
        if t else "No overdue deals. Your close dates are up to date!"
    )
    return {"title": "Overdue deals", "summary": summary, **x}


def opps_by_stage(q: Lookup) -> dict:
    recs = q.records("SELECT StageName, COUNT(Id) deals, SUM(Amount) amount FROM Opportunity WHERE IsClosed = false GROUP BY StageName ORDER BY COUNT(Id) DESC")
    total = sum(int(r.get("deals") or 0) for r in recs)
    rows = [{"label": s(r.get("StageName")), "detail": f"{plural(int(r.get('deals') or 0), 'deal')} · {n(r.get('amount'))}"} for r in recs]
    summary = f"**{plural(total, 'open deal')}** across {plural(len(recs), 'stage')}:" if total else "There are no open deals."
    return {"title": "Open deals by stage", "summary": summary, "total": total, "rows": rows, "salesforce_url": q.list_url("Opportunity")}


def opps_top(q: Lookup) -> dict:
    recs = q.records("SELECT Id, Name, Amount, StageName, CloseDate, Account.Name FROM Opportunity WHERE IsClosed = false AND Amount != null ORDER BY Amount DESC LIMIT 5")
    rows = [
        {"label": s(r.get("Name")), "detail": f"{n(r.get('Amount'))} · {rel(r, 'Account', 'No account')} · {s(r.get('StageName'))} · closes {d(r.get('CloseDate'))}", "url": q.record_url("Opportunity", r.get("Id"))}
        for r in recs
    ]
    k = len(recs)
    summary = (f"Your {'largest open deal' if k == 1 else f'{k} largest open deals'}:") if k else "No open deals have an amount yet."
    return {"title": "Biggest open deals", "summary": summary, "total": k, "rows": rows, "salesforce_url": q.list_url("Opportunity")}


def opps_won_this_quarter(q: Lookup) -> dict:
    r = (q.records("SELECT COUNT(Id) deals, SUM(Amount) amount FROM Opportunity WHERE IsWon = true AND CloseDate = THIS_QUARTER") or [{}])[0]
    deals = int(r.get("deals") or 0)
    summary = f"You’ve won **{plural(deals, 'deal')}** worth **{n(r.get('amount'))}** this quarter." if deals else "No deals have been won yet this quarter."
    return {"title": "Won this quarter", "summary": summary, "total": deals, "rows": [], "salesforce_url": q.list_url("Opportunity")}


def accounts_count(q: Lookup) -> dict:
    total = q.count("SELECT COUNT() FROM Account")
    return {"title": "Accounts", "summary": f"You have **{plural(total, 'account')}** in Salesforce.", "total": total, "rows": [], "salesforce_url": q.list_url("Account")}


def accounts_no_contacts(q: Lookup) -> dict:
    x = q.count_and_list(
        "Account", "Name, Owner.Name, CreatedDate", "Id NOT IN (SELECT AccountId FROM Contact WHERE AccountId != null)", "CreatedDate DESC",
        lambda r: {"label": s(r.get("Name")), "detail": f"{rel(r, 'Owner', 'No owner')} · added {d(r.get('CreatedDate'))}"},
    )
    t = x["total"]
    summary = f"**{plural(t, 'account')}** {'has' if t == 1 else 'have'} no contacts. Newest first:" if t else "Every account has at least one contact."
    return {"title": "Accounts with no contacts", "summary": summary, **x}


def contacts_no_email(q: Lookup) -> dict:
    x = q.count_and_list(
        "Contact", "Name, Account.Name, Phone", "Email = null", "LastModifiedDate DESC",
        lambda r: {"label": s(r.get("Name")), "detail": f"{rel(r, 'Account', 'No account')} · {'has a phone number' if r.get('Phone') else 'no phone either'}"},
    )
    t = x["total"]
    summary = f"**{plural(t, 'contact')}** {'has' if t == 1 else 'have'} no email address:" if t else "Every contact has an email address."
    return {"title": "Contacts with no email", "summary": summary, **x}


def contacts_no_account(q: Lookup) -> dict:
    x = q.count_and_list(
        "Contact", "Name, Email, Owner.Name", "AccountId = null", "LastModifiedDate DESC",
        lambda r: {"label": s(r.get("Name")), "detail": f"{s(r.get('Email'), 'No email')} · {rel(r, 'Owner', 'No owner')}"},
    )
    t = x["total"]
    summary = (
        f"**{plural(t, 'contact')}** {'isn’t' if t == 1 else 'aren’t'} linked to any account, so only their owner can see them:"
        if t else "Every contact is linked to an account."
    )
    return {"title": "Contacts not linked to an account", "summary": summary, **x}


LOOKUPS: dict[str, Callable[[Lookup], dict]] = {
    "leads.open": leads_open,
    "leads.new": leads_new,
    "leads.unassigned": leads_unassigned,
    "leads.stale": leads_stale,
    "leads.bySource": leads_by_source,
    "opps.open": opps_open,
    "opps.closingThisMonth": opps_closing_this_month,
    "opps.overdue": opps_overdue,
    "opps.byStage": opps_by_stage,
    "opps.top": opps_top,
    "opps.wonThisQuarter": opps_won_this_quarter,
    "accounts.count": accounts_count,
    "accounts.noContacts": accounts_no_contacts,
    "contacts.noEmail": contacts_no_email,
    "contacts.noAccount": contacts_no_account,
}


def run_lookup(query_id: str, sf: SalesforceClient) -> dict:
    fn = LOOKUPS.get(query_id)
    if fn is None:
        raise KeyError(query_id)
    result = fn(Lookup(sf))
    return {"id": query_id, "as_of": datetime.now(timezone.utc), **result}
