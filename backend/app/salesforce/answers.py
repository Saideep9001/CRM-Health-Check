"""Answers questions about the connected org's data for the Aqua assistant — by rules, never AI.

Handles, in order:
- org facts: edition, org id, instance, users, API calls and storage used;
- record look-ups: "who is Emily Davis", "find Acme", "tell me about Globex";
- breakdowns: "open deals by stage", "leads by source", "opportunities by owner";
- totals and averages: "total pipeline", "average deal size of won deals this year";
- any filter question the Find-or-ask interpreter understands ("open deals over 50k closing this month"),
  answered with the count and the first matching records.

Every query is built from describe-checked fields and typed, escaped values (see finder.py), so a question
can't change what a query does. Results are read with the connected user's own access.
"""
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

from . import explorer, finder
from .client import SalesforceClient
from .errors import SalesforceError

ROWS = 5
GROUPS = 8
# Everyday words in data questions that don't need a "not used" note.
FILLER = {"size", "deal", "deals", "amount", "value", "revenue", "pipeline", "number", "count", "records", "record", "list",
          "show", "many", "much", "give", "tell", "about", "have", "got", "there", "do", "we", "our", "us", "currently", "right", "now"}

AGGREGATE = re.compile(r"\b(total|sum of|sum|average|avg|mean|how much|value of|worth of)\b", re.I)
PIPELINE = re.compile(r"\bpipeline\b", re.I)
BY = re.compile(r"\b(?:by|per|for each|grouped by|broken down by|split by)\s+(owner|rep|sales ?rep|user|stage|lead source|source|industry|status|type|rating|priority|origin|country|state|forecast category|record type)\b", re.I)
LOOKUP = re.compile(r"^\s*(?:who is|who's|whos|find|look up|lookup|search for|search|show me|tell me about|details (?:of|for|on)|info (?:on|about)|open)\s+(.+?)\s*\??$", re.I)
ORG_INFO = re.compile(r"\b(edition|org(?:anization)? id|which org|what org|instance|sandbox|api (?:limit|usage|calls|requests)|storage|how many users|active users|licen[cs]es?)\b", re.I)

GROUP_FIELD = {
    "owner": "OwnerId", "rep": "OwnerId", "sales rep": "OwnerId", "salesrep": "OwnerId", "user": "OwnerId",
    "stage": "StageName", "lead source": "LeadSource", "source": "LeadSource", "industry": "Industry", "status": "Status",
    "type": "Type", "rating": "Rating", "priority": "Priority", "origin": "Origin", "forecast category": "ForecastCategoryName",
    "record type": "RecordTypeId",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _money(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"


def _answer(id_: str, title: str, summary: str, total: int | None = None, rows: list[dict] | None = None,
            salesforce_url: str | None = None, app_url: str | None = None) -> dict:
    return {"id": id_, "title": title, "summary": summary, "total": total, "rows": rows or [], "salesforce_url": salesforce_url,
            "app_url": app_url, "as_of": _now()}


def _record_url(sf: SalesforceClient, obj: str, rid: str | None) -> str | None:
    return f"{sf.base}/lightning/r/{quote(obj)}/{rid}/view" if rid else None


def _cell(v) -> str | None:
    if v in (None, "", [], {}):
        return None
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float)):
        return _money(float(v)) if not float(v).is_integer() or abs(v) >= 1000 else str(int(v))
    s = str(v)
    if re.match(r"^\d{4}-\d{2}-\d{2}T", s):
        return s[:10]
    return s[:60]


# ---------------------------------------------------------------- org facts

def org_info(sf: SalesforceClient) -> dict:
    org = (sf.query("SELECT Id, Name, OrganizationType, InstanceName, IsSandbox, CreatedDate FROM Organization LIMIT 1").get("records") or [{}])[0]
    users = sf.query("SELECT COUNT() FROM User WHERE IsActive = true AND UserType = 'Standard'").get("totalSize")
    rows = [
        {"label": "Organization", "detail": org.get("Name")},
        {"label": "Edition", "detail": f"{org.get('OrganizationType') or '—'}{' (sandbox)' if org.get('IsSandbox') else ''}"},
        {"label": "Org ID", "detail": org.get("Id")},
        {"label": "Instance", "detail": org.get("InstanceName")},
        {"label": "Active Salesforce users", "detail": f"{users:,}" if users is not None else "—"},
    ]
    try:
        lim = sf.limits() or {}
        for key, label in (("DailyApiRequests", "API calls today"), ("DataStorageMB", "Data storage (MB)"), ("FileStorageMB", "File storage (MB)")):
            v = lim.get(key) or {}
            if v.get("Max"):
                used = v["Max"] - v.get("Remaining", 0)
                rows.append({"label": label, "detail": f"{used:,} of {v['Max']:,} used ({100 * used / v['Max']:.0f}%)"})
    except SalesforceError:
        pass
    return _answer("org.info", f"About {org.get('Name') or 'your org'}", "Here’s what Salesforce reports about this org right now.",
                   rows=rows, salesforce_url=f"{sf.base}/lightning/setup/CompanyProfileInfo/home")


# ---------------------------------------------------------------- record look-up

def lookup(sf: SalesforceClient, term: str) -> dict | None:
    groups = finder.search_all(sf, term, None)
    hits = [(g, r) for g in groups for r in g["records"]]
    if not hits:
        return None
    rows = [{"label": r["name"], "detail": " · ".join(x for x in (g["label"], r.get("detail")) if x), "url": _record_url(sf, g["object"], r["id"])}
            for g, r in hits[:8]]
    first_g, first = hits[0]
    if len(hits) == 1:
        rec = explorer.get_record(sf, first_g["object"], first["id"])
        desc = explorer._describe(sf, first_g["object"])
        fields = explorer._fields(desc)
        rows = [{"label": fields[c].get("label") or c, "detail": _cell(rec["ref_names"].get(c) or rec["values"].get(c))}
                for c in explorer.default_columns(desc) if c != "Id" and c in fields and _cell(rec["ref_names"].get(c) or rec["values"].get(c))]
        return _answer("lookup", f"{first['name']} ({first_g['label']})", "Here are the key details from Salesforce.", 1, rows[:8],
                       salesforce_url=_record_url(sf, first_g["object"], first["id"]),
                       app_url=f"/data/{quote(first_g['object'])}?only={first['id']}")
    return _answer("lookup", f"Records matching “{term}”", f"I found **{len(hits)}** match{'es' if len(hits) != 1 else ''} across your objects.", len(hits), rows)


# ---------------------------------------------------------------- filtered questions, totals and breakdowns

def _app_url(obj: str, question: str, interp: dict) -> str:
    params = {"ask": question}
    if interp["filters"]:
        params["f"] = json.dumps([{k: f[k] for k in ("field", "op", "value", "label")} for f in interp["filters"]])
    if interp.get("sort"):
        params["sort"], params["dir"] = interp["sort"], interp.get("dir") or "desc"
    return f"/data/{quote(obj)}?{urlencode(params)}"


def answer(sf: SalesforceClient, question: str, context: str | None = None) -> dict | None:
    """An answer, or None when the question isn't about the org's data (the caller shows platform help instead)."""
    q = (question or "").strip()[:300]
    if not q:
        return None
    if ORG_INFO.search(q):
        return org_info(sf)

    known = explorer._global(sf)
    group = BY.search(q)
    want_agg = AGGREGATE.search(q) or PIPELINE.search(q)
    core = BY.sub(" ", q)
    core = re.sub(r"\b(total|sum of|sum|average|avg|mean|how much|value of|worth of|is the|are the|what is|what's|whats)\b", " ", core, flags=re.I)
    if PIPELINE.search(core) and not re.search(r"\b(deals?|opportunit|opps?)\b", core, re.I):
        core = PIPELINE.sub("open deals", core)
    try:
        interp = finder.interpret(core, known, describe=lambda n: explorer._describe(sf, n),
                                  children_of=lambda n: explorer.child_relationships(sf, n), context=context)
    except ValueError:
        m = LOOKUP.match(q)
        return lookup(sf, m.group(1)) if m else None

    m = LOOKUP.match(q)
    if m and not interp["filters"] and not group and not want_agg and interp["ignored"]:
        found = lookup(sf, m.group(1))  # "find Acme" where Acme isn't an object word
        if found:
            return found

    obj = interp["object"]
    desc = explorer._describe(sf, obj)
    fields = explorer._fields(desc)
    children = {c["name"]: c for c in explorer.child_relationships(sf, obj)}
    where = finder.conditions(fields, interp["filters"], children)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    g = known[obj]
    plural = g.get("labelPlural") or obj
    filt = " · ".join(f["label"] for f in interp["filters"]) or f"all {plural.lower()}"
    total = sf.query(f"SELECT COUNT() FROM {obj}{clause}").get("totalSize") or 0
    unused = [w for w in interp["ignored"] if w not in FILLER]
    note = f" (I didn’t use: {', '.join(unused)})" if unused else ""
    money = finder.Interpreter(fields, obj, children).money_field()
    app_url = _app_url(obj, q, interp)
    list_url = f"{sf.base}/lightning/o/{quote(obj)}/list"

    if group:
        key = group.group(1).lower().replace("salesrep", "sales rep")
        name = GROUP_FIELD.get(key) or finder._find_field(fields, key, {"text"})
        if name and name in fields and fields[name].get("groupable", True):
            expr = "Owner.Name" if name == "OwnerId" else "RecordType.Name" if name == "RecordTypeId" else name
            # Amounts only where they mean something (deal value), or when the question asks for a total.
            agg = f", SUM({money}) a" if money and fields[money].get("aggregatable", True) and (obj == "Opportunity" or want_agg) else ""
            recs = sf.query(f"SELECT {expr} g, COUNT(Id) c{agg} FROM {obj}{clause} GROUP BY {expr} ORDER BY COUNT(Id) DESC LIMIT {GROUPS}").get("records", [])
            label = (fields[name].get("label") or name).removesuffix(" ID")
            rows = [{"label": str(r.get("g") or "(blank)"), "detail": f"{r.get('c', 0):,}" + (f" · {_money(r.get('a'))} {fields[money].get('label', '').lower()}" if agg else "")} for r in recs]
            return _answer("group", f"{plural} by {label.lower()}", f"**{total:,}** {plural.lower()} ({filt}){note}, grouped by {label.lower()}:", total, rows, list_url, app_url)

    if want_agg and money:
        rec = (sf.query(f"SELECT SUM({money}) s, AVG({money}) a, MAX({money}) m FROM {obj}{clause}").get("records") or [{}])[0]
        mlabel = (fields[money].get("label") or money).lower()
        avg_asked = re.search(r"\b(average|avg|mean)\b", q, re.I)
        headline = (f"Average {mlabel}: **{_money(rec.get('a'))}**" if avg_asked else f"Total {mlabel}: **{_money(rec.get('s'))}**")
        rows = [{"label": "Records", "detail": f"{total:,}"}, {"label": f"Total {mlabel}", "detail": _money(rec.get("s"))},
                {"label": f"Average {mlabel}", "detail": _money(rec.get("a"))}, {"label": f"Largest {mlabel}", "detail": _money(rec.get("m"))}]
        return _answer("aggregate", f"{plural}: {filt}", f"{headline} across **{total:,}** {plural.lower()} ({filt}){note}.", total, rows, list_url, app_url)

    page = explorer.list_records(sf, obj, None, None, interp.get("sort"), interp.get("dir") or "desc", None, None, interp["filters"])
    name_field = explorer._name_field(desc)
    cols = [c for c in page["columns"] if c not in ("Id", name_field)][:3]
    rows = []
    for r in page["records"][:ROWS]:
        detail = " · ".join(x for x in (_cell(r["ref_names"].get(c) or r["values"].get(c)) for c in cols) if x)
        rows.append({"label": str(r["values"].get(name_field) or r["id"]), "detail": detail or None, "url": _record_url(sf, obj, r["id"])})
    summary = (f"**{total:,}** {plural.lower() if total != 1 else (g.get('label') or obj).lower()} match ({filt}){note}."
               if interp["filters"] else f"There are **{total:,}** {plural.lower()} you can see{note}.")
    return _answer("filter", f"{plural}: {filt}", summary, total, rows if not interp["count_only"] else rows[:3], list_url, app_url)
