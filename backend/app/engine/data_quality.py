"""Category 1 — Data Quality & Optimization (areas 1 and 2).

Based on the Aquarient RevenueOps Consultant Guide v1.0. Indicator labels match
src/config/categories.ts exactly.

Checks run only on the objects chosen for the run (default: Account, Contact,
Lead, Opportunity). Any other chosen object gets generic checks: duplicates by
name, key-field completeness, and unused custom fields.
"""
import logging
import re
from collections import Counter, defaultdict
from functools import lru_cache

from ..salesforce import duplicates as dupes
from ..salesforce.errors import SalesforceAuthExpired, SalesforceError
from . import standards
from .core import Ctx, FindingDraft, Metric, Unavailable, pct, range_score, rate_score

log = logging.getLogger(__name__)

OPEN_LEADS = "IsConverted = false"
BASE_CONDS = {"Lead": (OPEN_LEADS,)}  # only open Leads matter


def _label(ctx: Ctx, obj: str) -> str:
    return "open Leads" if obj == "Lead" else ctx.label(obj)


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _window(ctx: Ctx) -> str:
    """Plain words for the run's date window (text only, for the "Records checked" rule rows)."""
    n = ctx.scope.lookback_days
    return f", changed in the last {int(n)} days" if n else ""


def _base_total(ctx: Ctx, obj: str) -> int:
    """Records in scope for an object (open Leads only), also recorded for "Results by object"."""
    conds = BASE_CONDS.get(obj, ())
    if not conds:
        return ctx.total(obj)
    n = ctx.count(obj, *conds)
    ctx.totals[obj] = n
    ctx.stat(obj).records = n
    return n


# ---------------------------------------------------------------- area 1: duplicates, key fields, standardization

DUP_WHY = "People can’t tell which record is the right one, activity gets split across copies, and reports count the same customer twice."
DUP_IMPACT = "Wasted rep time, confused customers, and customer counts and revenue figures you can’t trust."


# Common ways people type the same country or US state.
_COUNTRY = {
    "us": "US", "usa": "US", "united states": "US", "united states of america": "US", "america": "US", "u s": "US", "u s a": "US",
    "uk": "GB", "u k": "GB", "united kingdom": "GB", "great britain": "GB", "gb": "GB", "england": "GB", "britain": "GB",
    "uae": "AE", "united arab emirates": "AE", "ca": "CA", "canada": "CA", "in": "IN", "india": "IN", "au": "AU", "australia": "AU",
    "de": "DE", "germany": "DE", "deutschland": "DE", "fr": "FR", "france": "FR", "mx": "MX", "mexico": "MX",
}
_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO", "connecticut": "CT",
    "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN",
    "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}


def _norm(value: object, table: dict[str, str]) -> str:
    key = re.sub(r"[^a-z ]", " ", str(value).lower())
    key = re.sub(r"\s+", " ", key).strip()
    return table.get(key, key.upper() if len(key) <= 3 else key)



# ---------------------------------------------------------------- per-object cards
#
# Every chosen object gets four cards: Duplicates, Missing Key Fields, Data Standardization Issues and No Activity in
# 6 Months. Accounts also get Accounts Without Open Opportunities; Opportunities get Closed Lost Without a Reason and
# Opportunities Without Line Items (Accounts Without Contacts and Contact Roles are in Area 4). Lead, Account,
# Contact and Opportunity use the fields below; any other object uses every field people fill in.

DUP_FIELDS: dict[str, tuple[str, ...]] = {
    "Lead": ("LastName", "Company", "Email", "Phone", "Title", "State", "City", "PostalCode"),
    "Account": ("Name", "Website", "Phone", "BillingState", "BillingCity", "BillingPostalCode", "Title"),
    "Contact": ("LastName", "Email", "Phone", "MailingState", "MailingCity", "MailingPostalCode"),
    "Opportunity": ("Name", "AccountId", "CloseDate", "Amount"),  # its own rule: opportunity_duplicates
}
KEY_FIELDS_BY_OBJECT: dict[str, tuple[str, ...]] = {
    "Lead": ("LastName", "Title", "Company", "Email", "Phone", "State", "City", "PostalCode", "LeadSource"),
    "Account": ("Name", "Website", "Phone", "BillingState", "BillingCity", "BillingPostalCode", "Title"),
    "Contact": ("LastName", "Email", "Phone", "MailingState", "MailingCity", "MailingPostalCode"),
    "Opportunity": ("Amount", "CloseDate", "NextStep"),
}
# Fields checked for invalid data, when they differ from the key fields.
STD_FIELDS: dict[str, tuple[str, ...]] = {"Opportunity": ("Name", "Amount", "CloseDate")}
BY_ACCOUNT = {"Opportunity"}  # records tables grouped by their Account
MISSING_ONLY = {"LeadSource"}  # picked from a list: checked for missing values only
# A duplicate must match on at least one of these (sharing only a city or a title isn't a duplicate).
STRONG_KINDS = {"email", "phone", "website", "company", "name", "amount"}
STRONG_FIELDS = {"Email", "Phone", "MobilePhone", "Website", "Company", "Amount"}
MAX_ALL_FIELDS = 50  # other objects: fields checked for missing values
MAX_DUP_FIELDS = 8  # other objects: text fields compared for duplicates (with the record name)
CARD_ROWS = 50_000  # records read to find duplicates and odd formats
LISTED = 500  # records listed under a duplicates or standardization card
INACTIVE_DAYS = 180


def _flabel(ctx: Ctx, obj: str, f: str) -> str:
    return ctx.fields(obj).get(f, {}).get("label") or f


MAX_SCORED_FIELDS = 12  # fields charted per object


def _by_field(ctx: Ctx, obj: str, card: str, f: str, count: int, of: int) -> None:
    """One field's number for one of the object's cards: `count` of `of` records (duplicated, empty or odd)."""
    ctx.memo.setdefault(("by_field", obj, card), []).append(
        {"field": f, "label": _flabel(ctx, obj, f), "count": count, "of": of, "pct": round(100 * count / of, 1) if of else 0.0})


def _same_value(kind: str, v) -> str:
    """A value in a form where the same thing written differently compares equal (for "unique")."""
    if kind == "company":
        return dupes.norm_company(v)
    if kind == "website":
        return dupes.norm_website(v)
    if kind == "phone":
        return re.sub(r"\D", "", str(v))[-10:]
    if kind == "email":
        return str(v).strip().lower()
    return dupes._clean(v)


def _present(ctx: Ctx, obj: str, names: tuple[str, ...]) -> list[str]:
    return [f for f in names if ctx.has_field(obj, f)]


def _name_field(ctx: Ctx, obj: str) -> str | None:
    return next((f["name"] for f in ctx.fields(obj).values() if f.get("nameField")), None)


def _text_fields(ctx: Ctx, obj: str) -> list[str]:
    """Other objects: text fields people fill in (for duplicates and spellings)."""
    fields = ctx.fields(obj)
    return [f for f in _generic_key_fields(fields, MAX_ALL_FIELDS) if fields[f].get("type") in ("string", "email", "phone", "url")]


def _rows(ctx: Ctx, obj: str, fields: list[str]) -> list[dict]:
    cols = ", ".join(dict.fromkeys(["Id", *fields]))
    return ctx.rows(f"SELECT {cols} FROM {obj}{ctx._where(obj, BASE_CONDS.get(obj, ()), True)}", CARD_ROWS)


def _listed(ctx: Ctx, obj: str, ids: list[str]) -> tuple[str, ...] | None:
    return (obj, ctx.ids_in(ids, LISTED)) if ids else None


# ---------------- duplicates on the object's fields

def _dup_kind(f: str, field: dict, name_field: str | None) -> str:
    if f == name_field and f not in ("LastName",):
        return "name"
    if f == "Amount" or field.get("type") == "currency":
        return "amount"
    if f == "Company":
        return "company"
    return dupes.kind_of(f, field)


@lru_cache(maxsize=500_000)  # the same pairs of values are compared many times (records sharing a phone, a surname…)
def _matches(kind: str, a, b) -> bool:
    if kind in ("name", "amount"):
        return dupes.m_exact(a, b)
    return dupes.KINDS[kind][1](a, b)


def _block_key(kind: str, v) -> str:
    if kind == "name":
        return dupes._clean(v)
    if kind == "amount":
        return str(v)
    return dupes._key(kind, v)


def duplicates_on_fields(ctx: Ctx, obj: str) -> None:
    fields = ctx.fields(obj)
    name_field = _name_field(ctx, obj)
    if obj in DUP_FIELDS:
        keys = _present(ctx, obj, DUP_FIELDS[obj])
    else:
        keys = ([name_field] if name_field and not fields[name_field].get("autoNumber") else []) + _text_fields(ctx, obj)[:MAX_DUP_FIELDS]
    total = _base_total(ctx, obj)
    kinds = {f: "company" if (obj, f) == ("Account", "Name") else _dup_kind(f, fields[f], name_field) for f in keys}  # "Acme, Inc." = "ACME"
    strong = [f for f in keys if kinds[f] in STRONG_KINDS or f in STRONG_FIELDS]
    if not total or not strong:
        return
    rows = _rows(ctx, obj, [*([name_field] if name_field else []), *keys])
    vals = [{f: r.get(f) for f in keys} for r in rows]
    filled = lambda v: v not in (None, "")  # noqa: E731

    def same(a: dict, b: dict) -> bool:
        """Every field filled on both matches, at least two match, and one of them is a strong identifier."""
        both = [f for f in keys if filled(a[f]) and filled(b[f])]
        if len(both) < 2 or not any(f in strong for f in both):
            return False
        return all(_matches(kinds[f], a[f], b[f]) for f in both)

    blocks: dict[str, list[int]] = defaultdict(list)
    for i, v in enumerate(vals):
        for f in strong:
            if filled(v[f]) and (k := _block_key(kinds[f], v[f])):
                blocks[f"{f}|{k}"].append(i)
    uf = dupes._Groups(len(vals))
    members: dict[int, list[int]] = {i: [i] for i in range(len(vals))}
    for block in blocks.values():
        block = list(dict.fromkeys(block))[:dupes.MAX_BLOCK]
        for x in range(len(block)):
            for y in range(x + 1, len(block)):
                i, j = block[x], block[y]
                ri, rj = uf.find(i), uf.find(j)
                if ri == rj or not same(vals[i], vals[j]):
                    continue
                # No chaining: every record in a group must match the group's first record.
                if not (all(same(vals[ri], vals[m]) for m in members[rj]) and all(same(vals[rj], vals[m]) for m in members[ri])):
                    continue
                merged = members.pop(ri) + members.pop(rj)
                uf.union(i, j)
                members[uf.find(i)] = merged
    groups = sorted((g for g in members.values() if len(g) > 1), key=len, reverse=True)
    extra = sum(len(g) - 1 for g in groups)
    ctx.stat(obj).duplicates = extra
    # "Duplicates by field": every field compared the way Check fields compares it on its own (same numbers there);
    # picklists, dates, numbers and places are shared by design and left out.
    from ..salesforce import field_check
    matchable = {m["name"]: m for m in dupes.matchable_fields(ctx.sf, obj)}
    for f in keys:
        n = field_check.duplicate_records(ctx.sf, obj, f, fields[f].get("type", ""), rows, matchable)
        if n is not None:
            _by_field(ctx, obj, "duplicates", f, n, sum(1 for v in vals if filled(v[f])))  # records sharing their value
    score = rate_score(extra / total, 0.15)
    label = _label(ctx, obj)
    ids = [rows[i]["Id"] for g in groups for i in g if rows[i].get("Id")]
    names = ", ".join(_flabel(ctx, obj, f) for f in keys)

    def show(g: list[int]) -> str:
        r = rows[g[0]]
        return f"“{r.get(name_field) or r.get('Id')}” ({len(g)})"

    records = _listed(ctx, obj, ids)
    # Which fields actually make the records duplicates: per field, the extra copies whose value matches their group's first record.
    matched = {f: sum(1 for g in groups for m in g[1:] if filled(vals[g[0]][f]) and filled(vals[m][f]) and _matches(kinds[f], vals[g[0]][f], vals[m][f]))
               for f in keys}
    matched_on = " · ".join(f"{_flabel(ctx, obj, f)} {n:,}" for f, n in sorted(matched.items(), key=lambda x: -x[1]) if n)
    ctx.metric(
        f"Duplicate {ctx.label(obj)}", extra, "count", "lower-better", score,
        how=f"{_cap(label)} that match another record on {names}, out of {total:,}. We count only the extra copies beyond the first in each group.",
        rule=f"Scores 100 when there are no duplicates, falling evenly to 0 when the extra copies reach 15% of all {label}.",
        records=records,
        columns=[*([name_field] if name_field else []), *keys, "OwnerId", "CreatedDate"],
        order=name_field,
        criteria=[
            ("Records checked", f"{len(rows):,} {label}{_window(ctx)}" + (f" (the first {CARD_ROWS:,})" if len(rows) >= CARD_ROWS else "")),
            ("Compared on", names + ("" if obj in DUP_FIELDS else " (the record name and its text fields)")),
            ("Check fields starts with", names),
            ("Duplicate means", "Every one of these fields that both records have filled in matches, at least two of them match, and one of those is "
             + ", ".join(_flabel(ctx, obj, f) for f in strong) + ". A blank field is skipped, never matched."),
            ("How values match", "; ".join(f"{_flabel(ctx, obj, f)}: {'exact value' if kinds[f] in ('name', 'amount') else dupes.KINDS[kinds[f]][0]}" for f in keys)),
            ("Duplicate group", "Records that all match the group's first record (no chains of near-matches)."),
            ("What's counted", f"The extra copies in each group (group size minus the one you keep): {extra:,} in {len(groups):,} groups."),
            ("Records listed", f"Every record in a duplicate group, including the one you'd keep (up to {LISTED})."),
            *([("Matched on", matched_on)] if matched_on else []),
        ],
    )
    ctx.finding(
        name=f"Duplicate {ctx.label(obj)}",
        score=score,
        affected=extra,
        description=f"{extra:,} extra {label} match another record on {names} ({len(groups):,} groups). Biggest: {', '.join(show(g) for g in groups[:3])}.",
        why=DUP_WHY,
        impact=DUP_IMPACT,
        action=f"Merge the duplicates, starting with the biggest groups, then turn on Matching and Duplicate Rules for {ctx.label(obj)}.",
        obj=obj,
        url=ctx.list_url(obj),
        records=records,
        fix="/lightning/setup/DuplicateRules/home",
    )


# ---------------- missing key fields

def missing_key_fields(ctx: Ctx, obj: str) -> None:
    fields = ctx.fields(obj)
    keys = _present(ctx, obj, KEY_FIELDS_BY_OBJECT[obj]) if obj in KEY_FIELDS_BY_OBJECT else _generic_key_fields(fields, MAX_ALL_FIELDS)
    total = _base_total(ctx, obj)
    if not keys or not total:
        return
    base = BASE_CONDS.get(obj, ())
    filled_by = ctx.filled_counts(obj, keys, *base)
    keys = [f for f in keys if f in filled_by]
    if not keys:
        return
    empty = {f: total - filled_by[f] for f in keys}
    for f in keys:
        _by_field(ctx, obj, "missing", f, total - filled_by[f], total)
    cond = "(" + " OR ".join(f"{f} = null" for f in keys) + ")"
    n = ctx.count(obj, *base, cond)
    filled_pct = 100 - pct(sum(empty.values()), total * len(keys))
    ctx.stat(obj).completeness = round(filled_pct, 1)  # "Results by object": % of key values filled in
    score = range_score(filled_pct, 50, 95)
    label = _label(ctx, obj)
    worst = sorted(keys, key=lambda f: -empty[f])
    names = ", ".join(_flabel(ctx, obj, f) for f in keys)
    ctx.metric(
        f"Missing Key Fields ({ctx.label(obj)})", pct(n, total), "%", "lower-better", score,
        how=f"{_cap(label)} missing at least one key field ({names}): {n:,} out of {total:,}.",
        rule="Scored on how many key values are filled in: 100 at 95% or more, 0 at 50% or less, in proportion in between. "
        "A problem is raised when the score is below 90.",
        records=(obj, *base, cond),
        columns=["Name", *(["AccountId"] if obj in BY_ACCOUNT else []), *keys[:12], "OwnerId", "CreatedDate"],
        order="Account.Name" if obj in BY_ACCOUNT else "Name",
        criteria=[
            ("Records checked", f"{total:,} {label}{_window(ctx)}"),
            ("Fields checked", names + ("" if obj in KEY_FIELDS_BY_OBJECT else f" (every field people fill in, up to {MAX_ALL_FIELDS})")),
            ("Counts as missing", "Any of these fields is empty. A record missing several counts once."),
            ("Empty per field", "; ".join(f"{_flabel(ctx, obj, f)} {empty[f]:,} ({pct(empty[f], total):.0f}%)" for f in worst)),
            ("What's counted", f"{n:,} of {total:,} {label} ({pct(n, total):.0f}%) miss at least one; {filled_pct:.0f}% of key values are filled in."),
            ("Records listed", "Every record missing at least one key field, sorted by name."),
        ],
    )
    ctx.finding(
        name=f"{_cap(label)} missing key fields",
        score=score,
        affected=n,
        description=f"{n:,} of {total:,} {label} miss at least one key field. Most often empty: "
        + ", ".join(f"{_flabel(ctx, obj, f)} ({pct(empty[f], total):.0f}% empty)" for f in worst[:4] if empty[f]) + ".",
        why="Missing details make records hard to act on: no way to call, email or locate the customer, and reports by region or source are wrong.",
        impact="Lost follow-ups, poor targeting and unreliable reports.",
        action=f"Fill the gaps, starting with the emptiest fields, and make the important ones required on the {ctx.label(obj, plural=False)} layout.",
        obj=obj,
        url=ctx.list_url(obj),
        min_score=90,
        records=(obj, *base, cond),
        fix=f"/lightning/setup/ObjectManager/{obj}/FieldsAndRelationships/view",
    )


# ---------------- data standardization

def _std_kind(f: str, field: dict, obj: str | None = None) -> str:
    t = field.get("type")
    if (obj, f) == ("Opportunity", "Name"):
        return "dealname"
    if f == "Account.Name":  # the related Account's name: the Account Name rules
        return "company"
    if f == "Amount" or t == "currency":
        return "amount"
    if f == "CloseDate" or t == "date":
        return "date"
    if t == "email":
        return "email"
    if t == "phone" or f.endswith("Phone"):
        return "phone"
    if t == "url" or f == "Website":
        return "website"
    if f.endswith("PostalCode"):
        return "postal"
    if f.endswith("Country"):
        return "country"
    if f.endswith("State"):
        return "state"
    if f.endswith("City"):
        return "city"
    if f in ("Name", "Company"):  # a company's name (Account Name, Lead Company)
        return "company"
    return "text"


def data_standardization(ctx: Ctx, obj: str) -> None:
    fields = ctx.fields(obj)
    if obj in STD_FIELDS:
        keys = _present(ctx, obj, STD_FIELDS[obj])
    elif obj in KEY_FIELDS_BY_OBJECT:
        keys = [f for f in _present(ctx, obj, KEY_FIELDS_BY_OBJECT[obj]) if f not in MISSING_ONLY]
    else:
        keys = _text_fields(ctx, obj)
    total = _base_total(ctx, obj)
    if not keys or not total:
        return
    closed = ["IsClosed"] if "CloseDate" in keys and ctx.has_field(obj, "IsClosed", None) else []
    rows = _rows(ctx, obj, [*keys, *closed])
    open_ids = {r["Id"] for r in rows if closed and r.get("IsClosed") is False}
    bad: set[str] = set()
    with_value: set[str] = set()
    per_field: list[tuple[str, str, int, list[str]]] = []  # (field, kind, odd records, examples)
    reasons: dict[str, Counter] = {}  # field -> why its values are odd, and how many of each
    notes: dict[str, dict[str, str]] = defaultdict(dict)  # record id -> field -> why that value is odd
    for f in keys:
        kind = _std_kind(f, fields[f], obj)
        items = [(r["Id"], r[f]) for r in rows if r.get("Id") and r.get(f) not in (None, "")]
        with_value.update(i for i, _ in items)
        why = standards.odd_values(kind, items, open_ids)  # record id -> reason
        odd = set(why)
        reasons[f] = Counter(why.values())
        for i, r in why.items():
            notes[i][f] = r
        bad |= odd
        if items:
            _by_field(ctx, obj, "standardization", f, len(odd), len(items))
        examples = list(dict.fromkeys(str(v) for i, v in items if i in odd))[:3]
        per_field.append((f, kind, len(odd), examples))
    score = rate_score(len(bad) / len(with_value), 0.25) if with_value else 100
    label = _label(ctx, obj)
    records = _listed(ctx, obj, sorted(bad))
    worst = sorted((p for p in per_field if p[2]), key=lambda p: -p[2])
    ctx.metric(
        f"Data Standardization Issues ({ctx.label(obj)})", len(bad), "count", "lower-better", score,
        how=f"{_cap(label)} with at least one value in an odd format or spelling ({', '.join(_flabel(ctx, obj, f) for f in keys)}), "
        f"out of {len(with_value):,} with any of them filled in.",
        rule="Scores 100 when every value is consistent, falling evenly to 0 when 25% of the records have an odd value. "
        "A problem is raised when the score is below 95.",
        records=records,
        columns=["Name", *(["AccountId"] if obj in BY_ACCOUNT else []), *keys[:12], "OwnerId"],
        order="Account.Name" if obj in BY_ACCOUNT else "Name",
        criteria=[
            ("Records checked", f"{len(rows):,} {label}{_window(ctx)}" + (f" (the first {CARD_ROWS:,})" if len(rows) >= CARD_ROWS else "")),
            ("Fields checked", ", ".join(_flabel(ctx, obj, f) for f in keys) + ("" if obj in KEY_FIELDS_BY_OBJECT or obj in STD_FIELDS else " (text fields people fill in)")),
            ("Counts as odd", "; ".join(f"{_flabel(ctx, obj, f)}: {standards.RULES[k]}" for f, k, _, _ in per_field)),
            ("Found per field", "; ".join(f"{_flabel(ctx, obj, f)} {n:,}" + (f" — {', '.join(f'{r}: {c:,}' for r, c in reasons[f].most_common(3))}" if n else "")
                                          + (f" (e.g. {', '.join(f'“{e}”' for e in ex)})" if ex else "") for f, _, n, ex in per_field)),
            ("What's counted", f"{len(bad):,} {label} with at least one odd value; a record with several counts once."),
            ("Records listed", f"Records with an odd value (up to {LISTED}), sorted by name."),
        ],
    )
    if records:  # shown on the listed records' cells: why each value is odd
        listed = sorted(bad)[:LISTED]
        ctx.metrics[ctx.area_id][-1].records[0]["notes"] = {i: notes[i] for i in listed}
    ctx.finding(
        name=f"Inconsistent data on {label}",
        score=score,
        affected=len(bad),
        description=f"{len(bad):,} {label} have a value in an odd format or spelling. Most affected: "
        + ", ".join(f"{_flabel(ctx, obj, f)} ({n:,}" + (f", e.g. “{ex[0]}”" if ex else "") + ")" for f, _, n, ex in worst[:3]) + ".",
        why="Values written different ways break filters, reports, routing and duplicate matching.",
        impact="Records missed by reports and rules, and duplicates that slip through.",
        action="Clean up the odd values, then use picklists, validation rules or State and Country picklists so people enter them one way.",
        obj=obj,
        url=ctx.list_url(obj),
        records=records,
    )


# ---------------- no activity in 6 months

def no_recent_activity(ctx: Ctx, obj: str) -> None:
    total = _base_total(ctx, obj)
    fld = next((f for f in ("LastActivityDate", "LastModifiedDate") if ctx.has_field(obj, f)), None)
    if not total or not fld:
        return
    base = BASE_CONDS.get(obj, ())
    older = [f"CreatedDate < LAST_N_DAYS:{INACTIVE_DAYS}"] if ctx.has_field(obj, "CreatedDate") else []
    conds = (*base, f"({fld} = null OR {fld} < LAST_N_DAYS:{INACTIVE_DAYS})", *older)
    n = ctx.count(obj, *conds, recent=False)
    label = _label(ctx, obj)
    what = "activity (task, event, call or email logged)" if fld == "LastActivityDate" else "change"
    score = rate_score(n / total, 0.5)
    measure = f"No Activity in 6 Months ({ctx.label(obj)})"
    ctx.metric(
        measure, pct(n, total), "%", "lower-better", score,
        how=f"{_cap(label)} with no {what} in the last 6 months: {n:,} out of {total:,}.",
        rule="Scores 100 when every record has had activity in the last 6 months, falling evenly to 0 when 50% have none. "
        "A problem is raised whenever any record is inactive.",
        records=(obj, *conds),
        recent=False,
        columns=["Name", fld, "OwnerId", "CreatedDate"],
        order=fld,
        criteria=[
            ("Records checked", f"{total:,} {label}"),
            ("Activity date", f"{_flabel(ctx, obj, fld)}" + (" (the last task or event)" if fld == "LastActivityDate"
                                                            else " (this object has no activity date, so the last change is used)")),
            ("Counts as inactive", f"No {what} in the last {INACTIVE_DAYS} days (or never)"
             + (", and created more than 6 months ago (newer records aren’t counted)." if older else ".")),
            ("What's counted", f"{n:,} of {total:,} {label} ({pct(n, total):.0f}%)."),
            ("Records listed", "Every inactive record, oldest activity first."),
        ],
    )
    ctx.finding(
        name=f"{_cap(label)} with no activity in 6 months",
        score=score,
        affected=n,
        min_score=101,  # raised whenever any record is inactive; its urgency comes from the score
        description=f"{n:,} of {total:,} {label} ({pct(n, total):.0f}%) have had no {what} in the last 6 months.",
        why="Records nobody works on go cold: details get out of date and real chances are missed.",
        impact="Neglected customers and leads, and lists and reports cluttered with records nobody follows up.",
        action="Give the inactive records to an owner with a follow-up task, and close or archive the ones that no longer matter.",
        obj=obj,
        url=ctx.list_url(obj),
        records=(obj, *conds),
        recent=False,
        fix=f"/lightning/o/{obj}/list",  # Fix it in Salesforce: the records, to give owners follow-ups or close them
        measure=measure,
    )


# ---------------- account extras

def accounts_without_contacts(ctx: Ctx, obj: str = "Account") -> None:
    total = _base_total(ctx, "Account")
    cond = "Id NOT IN (SELECT AccountId FROM Contact WHERE AccountId != null)"
    n = ctx.count("Account", cond) if total else 0
    score = rate_score(n / total, 0.5) if total else 100
    ctx.metric(
        "Accounts Without Contacts", n, "count", "lower-better", score,
        how=f"Accounts that have no Contacts linked to them, out of {total:,} Accounts.",
        rule="Scores 100 when every Account has at least one Contact, falling evenly to 0 when 50% have none. "
        "A problem is raised whenever any Account has none.",
        records=("Account", cond),
        columns=["Name", "Type", "Industry", "Phone", "OwnerId", "LastActivityDate", "CreatedDate"],
        order="Name",
        criteria=[
            ("Records checked", f"{total:,} Accounts" + _window(ctx)),
            ("Counts as no Contacts", "No Contact record has this Account as its Account. Contacts linked through other relationships aren’t counted."),
            ("What's counted", f"{n:,} of {total:,} Accounts ({pct(n, total):.0f}%) with no Contacts."),
            ("Records listed", "Every Account with no Contacts, sorted by name."),
        ],
    )
    ctx.finding(
        name="Accounts with no Contacts",
        score=score,
        affected=n,
        min_score=101,  # raised whenever any Account has none; its urgency comes from the score
        description=f"{n:,} of {total:,} Accounts ({pct(n, total):.0f}%) have no Contacts.",
        why="You can’t sell to a company if you don’t know who works there.",
        impact="Missed relationships and opportunities that stall without a known buyer.",
        action="Add the main people for important Accounts, and review Accounts with no Contacts and no activity for cleanup.",
        obj="Account",
        url=ctx.list_url("Account"),
        records=("Account", cond),
        fix="/lightning/o/Account/list",  # Fix it in Salesforce: the Accounts, to add their Contacts
        measure="Accounts Without Contacts",
    )


def accounts_without_open_deals(ctx: Ctx, obj: str = "Account") -> None:
    ctx.fields("Opportunity")  # Unavailable when the org has no Opportunities
    total = _base_total(ctx, "Account")
    cond = "Id NOT IN (SELECT AccountId FROM Opportunity WHERE IsClosed = false AND AccountId != null)"
    n = ctx.count("Account", cond) if total else 0
    score = rate_score(n / total, 1.0) if total else 100  # the share of Accounts with a deal in progress
    ctx.metric(
        "Accounts Without Open Opportunities", n, "count", "lower-better", score,
        how=f"Accounts with no open Opportunity, out of {total:,} Accounts.",
        rule="The score is the share of Accounts with at least one open Opportunity (100 when every Account has one, 0 when none do). "
        "A problem is raised whenever any Account has none.",
        records=("Account", cond),
        columns=["Name", "Type", "Industry", "OwnerId", "LastActivityDate", "CreatedDate"],
        order="Name",
        criteria=[
            ("Records checked", f"{total:,} Accounts" + _window(ctx)),
            ("Counts as no open Opportunities", "No Opportunity that isn’t Closed Won or Closed Lost has this Account."),
            ("What's counted", f"{n:,} of {total:,} Accounts ({pct(n, total):.0f}%)."),
            ("Records listed", "Every Account with no open Opportunity, sorted by name."),
        ],
    )
    ctx.finding(
        name="Accounts with no open Opportunities",
        score=score,
        affected=n,
        min_score=101,  # raised whenever any Account has none; its urgency comes from the score
        description=f"{n:,} of {total:,} Accounts ({pct(n, total):.0f}%) have no Opportunity in progress.",
        why="An Account with no deal in progress isn’t bringing in new business, and may be slipping away.",
        impact="A thin pipeline, and missed upsell, cross-sell and renewal chances with existing customers.",
        action="Review active Accounts with no open Opportunity: open deals for real chances, and mark dormant Accounts as such.",
        obj="Account",
        url=ctx.list_url("Account"),
        records=("Account", cond),
        fix="/lightning/o/Account/list",  # Fix it in Salesforce: the Accounts, to open deals or mark them dormant
        measure="Accounts Without Open Opportunities",
    )


# ---------------- opportunities

CLOSED_LOST = "IsClosed = true AND IsWon = false"
OPEN_DEALS = "IsClosed = false"  # neither Closed Won nor Closed Lost: the deals still being worked


def opportunity_duplicates(ctx: Ctx, obj: str = "Opportunity") -> None:
    """Two rules: the same Opportunity Name (on any Account), or the same Account with the same Close Date and Amount.
    Stage and Type are shared by design, so they aren't compared."""
    total = _base_total(ctx, obj)
    if not total or not ctx.has_field(obj, "Name"):
        return
    combo = _present(ctx, obj, ("AccountId", "CloseDate", "Amount"))
    rows = _rows(ctx, obj, ["Name", *combo])
    uf = dupes._Groups(len(rows))
    by_name: dict[str, list[int]] = defaultdict(list)
    by_combo: dict[tuple, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        if k := dupes._clean(r.get("Name")):
            by_name[k].append(i)
        if len(combo) == 3 and all(r.get(f) not in (None, "") for f in combo):
            by_combo[tuple(str(r[f]) for f in combo)].append(i)
    for block in [*by_name.values(), *by_combo.values()]:
        for i in block[1:]:
            uf.union(block[0], i)
    members: dict[int, list[int]] = defaultdict(list)
    for i in range(len(rows)):
        members[uf.find(i)].append(i)
    groups = sorted((g for g in members.values() if len(g) > 1), key=len, reverse=True)
    extra = sum(len(g) - 1 for g in groups)
    ctx.stat(obj).duplicates = extra
    same_name = sum(len(b) for b in by_name.values() if len(b) > 1)
    same_deal = sum(len(b) for b in by_combo.values() if len(b) > 1)
    # The chart: one bar per field. Opportunity Name: records sharing their name (any Account); Close Date and Amount:
    # records sharing that value with another Opportunity on the same Account.
    _by_field(ctx, obj, "duplicates", "Name", same_name, len(rows))
    if "AccountId" in combo:
        for f in combo[1:]:
            shared = Counter((r.get("AccountId"), r.get(f)) for r in rows if r.get("AccountId") and r.get(f) not in (None, ""))
            _by_field(ctx, obj, "duplicates", f, sum(c for c in shared.values() if c > 1),
                      sum(1 for r in rows if r.get("AccountId") and r.get(f) not in (None, "")))
    score = rate_score(extra / total, 0.15)
    ids = [rows[i]["Id"] for g in groups for i in g if rows[i].get("Id")]
    records = _listed(ctx, obj, ids)
    combo_names = ", ".join(_flabel(ctx, obj, f) for f in combo[1:])
    ctx.metric(
        "Duplicate Opportunities", extra, "count", "lower-better", score,
        how=f"Opportunities with the same name as another (on any Account), or on the same Account with the same {combo_names}, "
        f"out of {total:,}. We count only the extra copies beyond the first in each group.",
        rule="Scores 100 when there are no duplicates, falling evenly to 0 when the extra copies reach 15% of all Opportunities.",
        records=records,
        columns=["Name", *combo, "OwnerId", "CreatedDate"],
        order="Account.Name",  # grouped by Account in the records table
        criteria=[
            ("Records checked", f"{len(rows):,} Opportunities{_window(ctx)}" + (f" (the first {CARD_ROWS:,})" if len(rows) >= CARD_ROWS else "")),
            ("Compared on", f"Opportunity Name (on any Account); Account ID, {combo_names} (on the same Account)"),
            ("Duplicate means", f"The same Opportunity Name, even on different Accounts (case, spaces and punctuation ignored); or the same Account with "
             f"the same {combo_names}. A blank value is never matched."),
            ("Found by rule", f"Same name: {same_name:,} Opportunities; same Account and deal details: {same_deal:,}."),
            ("Check fields starts with", ", ".join([_flabel(ctx, obj, "Name"), *(_flabel(ctx, obj, f) for f in ("CloseDate", "Amount") if f in combo)])),
            ("Duplicate group", "Records linked by either rule."),
            ("What's counted", f"The extra copies in each group (group size minus the one you keep): {extra:,} in {len(groups):,} groups."),
            ("Records listed", f"Every record in a duplicate group, including the one you'd keep (up to {LISTED})."),
        ],
    )
    ctx.finding(
        name="Duplicate Opportunities",
        score=score,
        affected=extra,
        description=f"{extra:,} extra Opportunities repeat another one's name or deal details ({len(groups):,} groups)."
        + (" Biggest: " + ", ".join(f"“{rows[g[0]].get('Name')}” ({len(g)})" for g in groups[:3]) + "." if groups else ""),
        why="The same deal entered twice inflates the pipeline and forecast, and splits the activity and notes between copies.",
        impact="Forecasts and win rates you can’t trust, and reps working the same deal twice.",
        action="Merge or close the duplicate Opportunities, starting with the biggest groups, and add a Duplicate Rule for Opportunities.",
        obj=obj,
        url=ctx.list_url(obj),
        records=records,
        fix="/lightning/setup/DuplicateRules/home",
    )


def _loss_reason_field(ctx: Ctx) -> str | None:
    """The org's Loss Reason field, if it has one (there's no standard one): a field named or labelled like it."""
    for name, f in ctx.fields("Opportunity").items():
        text = f"{name} {f.get('label') or ''}".lower()
        if re.search(r"(loss|lost).{0,12}reason|reason.{0,12}(loss|lost)", text):
            return name
    return None


def _without(ctx: Ctx, label: str, cond: str, *, base: tuple[str, ...], counted: str, checked: str, fine: str, why: str, impact: str,
             action: str, fix: str, name: str, columns: list[str], bad: float = 0.5, obj: str = "Opportunity",
             extra: list[tuple[str, str]] | None = None) -> Metric:
    """A card: how many of the `base` records of `obj` match `cond`, scored, raising a problem whenever any do."""
    total = ctx.count(obj, *base)
    n = ctx.count(obj, *base, cond) if total else 0
    score = rate_score(n / total, bad) if total else 100
    m = ctx.metric(
        label, n, "count", "lower-better", score,
        how=f"{counted}, out of {total:,} {checked}.",
        rule=f"Scores 100 when every one {fine}, falling evenly to 0 when {bad:.0%} don’t. A problem is raised whenever any record is affected.",
        records=(obj, *base, cond),
        columns=columns,
        order="Name",
        criteria=[
            ("Records checked", f"{total:,} {checked}" + _window(ctx)),
            ("Counts as affected", counted + "."),
            *(extra or []),
            ("What's counted", f"{n:,} of {total:,} {checked} ({pct(n, total):.0f}%)."),
            ("Records listed", f"Every affected {ctx.label(obj, plural=False)}, sorted by name."),
        ],
    )
    m.out_of, m.out_of_label = total, checked  # the card's "x% of …" is out of these, not every Opportunity
    ctx.finding(
        name=name,
        score=score,
        affected=n,
        min_score=101,  # raised whenever any record is affected; its urgency comes from the score
        description=f"{n:,} of {total:,} {checked} ({pct(n, total):.0f}%): {counted[0].lower() + counted[1:]}.",
        why=why,
        impact=impact,
        action=action,
        obj=obj,
        url=ctx.list_url(obj),
        records=(obj, *base, cond),
        fix=fix,
        measure=label,
    )
    return m


def closed_lost_without_reason(ctx: Ctx, obj: str = "Opportunity") -> None:
    if not ctx.has_field(obj, "IsWon"):
        return
    reason = _loss_reason_field(ctx)
    cond = f"{reason} = null" if reason else "Id != null"  # no Loss Reason field: no Closed Lost deal has a reason
    _without(
        ctx, "Closed Lost Without a Reason (Opportunities)", cond, base=(CLOSED_LOST,),
        counted=(f"Closed Lost Opportunities with {_flabel(ctx, obj, reason)} empty" if reason
                 else "Closed Lost Opportunities with no reason recorded (this org has no Loss Reason field)"),
        checked="Closed Lost Opportunities", fine="has a loss reason",
        why="Without a reason for each lost deal you can’t see why you lose: price, product, competitor or timing.",
        impact="The same deals keep being lost for the same reasons, and win-rate reviews have nothing to go on.",
        action=(f"Fill in {_flabel(ctx, obj, reason)} on recent lost deals, and make it required when the Stage is Closed Lost."
                if reason else "Add a Loss Reason picklist to Opportunity and make it required when the Stage is Closed Lost."),
        fix="/lightning/setup/ObjectManager/Opportunity/FieldsAndRelationships/view",
        name="Closed Lost Opportunities without a reason",
        columns=["Name", *([reason] if reason else []), "AccountId", "Amount", "CloseDate", "OwnerId"],
    )


def opportunities_without_line_items(ctx: Ctx, obj: str = "Opportunity") -> None:
    if not ctx.has_field(obj, "HasOpportunityLineItem"):
        return
    _without(
        ctx, "Opportunities Without Line Items", "HasOpportunityLineItem = false", base=(OPEN_DEALS,),
        counted="Open Opportunities with no products (line items)",
        checked="open Opportunities (not Closed Won or Closed Lost)", fine="has its products",
        why="An Opportunity without products doesn’t say what you’re selling, so its amount can’t be checked or reported by product.",
        impact="Revenue by product, quotas and forecasts that miss what was actually sold.",
        action="Add the products to open deals, and require at least one product before a deal can move past qualification.",
        fix="/lightning/o/Opportunity/list",
        name="Opportunities without line items",
        columns=["Name", "AccountId", "Amount", "StageName", "CloseDate", "OwnerId"],
    )


# ---------------- leads

def leads_without_campaign(ctx: Ctx, obj: str = "Lead") -> None:
    ctx.fields("CampaignMember")  # Unavailable when Campaigns aren't used
    _without(
        ctx, "Campaign Association Gaps (Leads)", "Id NOT IN (SELECT LeadId FROM CampaignMember WHERE LeadId != null)", base=BASE_CONDS["Lead"],
        obj="Lead",
        counted="Open Leads that aren’t a member of any Campaign",
        checked="open Leads", fine="is in a Campaign",
        why="Without a Campaign you can’t tell which marketing brought the Lead in, so campaign results and spend can’t be judged.",
        impact="Campaign ROI and lead-source reports that miss these Leads, and budget spent on the wrong channels.",
        action="Add the Leads to the Campaign that generated them, and set web-to-lead forms and imports to add new Leads to a Campaign.",
        fix="/lightning/o/Lead/list",
        name="Campaign Association Gaps",
        columns=["Name", "Company", "LeadSource", "Status", "OwnerId", "CreatedDate"],
    )


def stale_leads(ctx: Ctx, obj: str = "Lead") -> None:
    """Open Leads whose Status hasn't changed for `stale_lead_days` (from Lead History when Status is tracked, otherwise the
    last change of any kind), created before that."""
    days = int(ctx.scope.stale_lead_days)
    older = f"CreatedDate < LAST_N_DAYS:{days}"
    history = True
    try:  # Status tracked in Lead History: the Leads whose Status changed recently aren't stale
        ctx.count("Lead", "Id IN (SELECT LeadId FROM LeadHistory WHERE Field = 'Status')")
        moved = lambda n: f"Id NOT IN (SELECT LeadId FROM LeadHistory WHERE Field = 'Status' AND CreatedDate = LAST_N_DAYS:{n})"  # noqa: E731
        how = "The Status hasn’t changed (from Lead History)"
        counted = f"Open Leads whose Status hasn’t changed in the last {days} days"
    except SalesforceAuthExpired:
        raise
    except SalesforceError:  # no history to go by: no change of any kind
        history = False
        moved = lambda n: f"LastModifiedDate < LAST_N_DAYS:{n}"  # noqa: E731
        how = "The Lead hasn’t changed at all (Status changes aren’t tracked in Lead History, so its last change is used)"
        counted = f"Open Leads not changed at all in the last {days} days"
    by_age = [(n, ctx.count("Lead", *BASE_CONDS["Lead"], f"CreatedDate < LAST_N_DAYS:{n}", moved(n))) for n in (30, 60, 90)]
    m = _without(
        ctx, "Stale Leads", f"{older} AND {moved(days)}", base=BASE_CONDS["Lead"], obj="Lead",
        counted=counted,
        checked="open Leads", fine="moves forward",
        why="A Lead left in the same status goes cold: the longer nobody works it, the less likely it is to convert.",
        impact="Lost conversions, a lead list full of dead records, and conversion rates that look worse than they are.",
        action="Work or reassign the stale Leads, close the ones that won’t convert, and add a rule or reminder when a Lead sits too long.",
        fix="/lightning/o/Lead/list",
        name=f"Open Leads stuck in the same status for {days}+ days",
        columns=["Name", "Company", "Status", "OwnerId", "LastModifiedDate", "CreatedDate"],
        extra=[("Stale means", f"{how} for {days} days or more (the check's setting), on Leads created before then."),
               ("By how long", "; ".join(f"{n}+ days: {c:,}" for n, c in by_age))],
    )
    if m.records:  # the table can show another period (1, 3, 6 months or dates) and one Status at a time
        m.records[0].update({"stale_days": days, "stale_history": history, "by_status": True})


# ---------------- one step per object (cards for an object stay together)

def _cards(ctx: Ctx, obj: str, *checks) -> None:
    for k, check in enumerate(checks):
        ctx.tick(k / len(checks))
        try:
            check(ctx, obj)
        except Unavailable:
            continue
        except SalesforceAuthExpired:
            raise
        except SalesforceError as exc:  # one card failing shouldn't hide the others
            log.warning("%s on %s skipped: %s", check.__name__, obj, exc)
    plural = ctx.label(obj)
    cards = {f"Duplicate {plural}": "duplicates", f"Missing Key Fields ({plural})": "missing", f"Data Standardization Issues ({plural})": "standardization"}
    for m in ctx.metrics.get(ctx.area_id, []):
        rows = ctx.memo.get(("by_field", obj, cards.get(m.label)), [])
        if m.label in cards and rows:
            m.field_scores = rows[:MAX_SCORED_FIELDS]
    if not ctx.memo.get("picklists_checked") and obj in ("Account", "Contact", "Lead") and not ctx.has_field("Account", "BillingCountryCode", None):
        ctx.memo["picklists_checked"] = True
        ctx.findings.append(FindingDraft(
            area_id=ctx.area_id,
            name="State and Country picklists are turned off",
            severity="medium",
            affected_records=0,
            description="Addresses are typed as free text, so the same place gets spelled many different ways.",
            why_it_matters="Clean, consistent data starts with settings that stop bad data from being entered.",
            business_impact="Ongoing cleanup work and unreliable reports.",
            recommended_action="In Setup, turn on State and Country/Territory Picklists (convert existing data first using the built-in tool).",
            fix_url=ctx.setup_url("/lightning/setup/AddressCleanerOverview/home"),
        ))


CORE_CARDS = (duplicates_on_fields, missing_key_fields, data_standardization, no_recent_activity)


def account_cards(ctx: Ctx) -> None:
    ctx.selected("Account")
    _cards(ctx, "Account", *CORE_CARDS, accounts_without_open_deals)  # Accounts Without Contacts is in Area 4


def contact_cards(ctx: Ctx) -> None:
    ctx.selected("Contact")
    _cards(ctx, "Contact", *CORE_CARDS)


def lead_cards(ctx: Ctx) -> None:
    ctx.selected("Lead")
    # No Activity in 6 Months and Stale Leads are in Area 3 (Lead queues & assignment)
    _cards(ctx, "Lead", duplicates_on_fields, missing_key_fields, data_standardization, leads_without_campaign)


def opportunity_cards(ctx: Ctx) -> None:
    ctx.selected("Opportunity")
    # No Activity in 6 Months and Closed Lost Without a Reason are in Area 5 (sales path & feedback loops)
    _cards(ctx, "Opportunity", opportunity_duplicates, missing_key_fields, data_standardization, opportunities_without_line_items)


def other_object_cards(ctx: Ctx) -> None:
    for obj in ctx.selected(*ctx.others()):
        try:
            ctx.fields(obj)
        except Unavailable:
            continue
        _cards(ctx, obj, *CORE_CARDS)


# ---------------------------------------------------------------- area 2: the fields themselves, per object

# Fields every record has or that the system fills in; not useful for "completeness".
_SYSTEM_FIELDS = {
    "Id", "OwnerId", "CreatedById", "LastModifiedById", "CreatedDate", "LastModifiedDate", "SystemModstamp", "IsDeleted",
    "LastActivityDate", "LastViewedDate", "LastReferencedDate", "RecordTypeId", "CurrencyIsoCode", "MasterRecordId", "Name",
}
_SKIP_TYPES = {"boolean", "id", "base64", "address", "location", "textarea", "encryptedstring"}
MAX_GENERIC_FIELDS = 8


def _generic_key_fields(fields: dict[str, dict], limit: int = MAX_GENERIC_FIELDS) -> list[str]:
    """For objects without a curated list: editable, optional, filterable fields — standard first, then custom."""
    picks = [
        f for f in fields.values()
        if f["name"] not in _SYSTEM_FIELDS and f.get("type") not in _SKIP_TYPES and f.get("filterable")
        and f.get("createable") and f.get("nillable", True) and not f.get("calculated") and not f.get("autoNumber")
    ]
    picks.sort(key=lambda f: bool(f.get("custom")))
    return [f["name"] for f in picks[:limit]]


# Every chosen object gets cards about its fields: All Fields, Unused Fields, Outdated Fields, Look-alike Fields,
# Low-Completion Fields and (Accounts, Contacts, Leads, Opportunities) Empty Fields Others Depend On. One Data Quality
# Scorecard scores each object from its area 1 and area 2 results.

_LEGACY = re.compile(r"(^|[_\s])(old|v\d+|bak|backup|deprecated|legacy|do not use|dnu|copy|temp|tmp|test|unused)([_\s]|$)", re.I)
LOW_FILL = 0.2  # "low completion": filled on fewer than 20% of records…
UNUSED_FILL = 0.01  # "hardly ever filled": filled on fewer than 1% (between never and rarely)
MIN_RECORDS = 20  # fill rates aren't judged on objects with fewer records
MAX_FILL_FIELDS = 400  # fields whose fill rate is counted per object (50 per query)


def _own(f: dict) -> bool:
    """A custom field built in this org on this object — not from an installed package (namespace__Field__c), which admins
    can't change, nor a Contact field shown on person accounts (Field__pc)."""
    return bool(f.get("custom")) and f["name"].count("__") < 2 and not f["name"].endswith("__pc")


def _setup_link(obj: str) -> str:
    return f"/lightning/setup/ObjectManager/{obj}/FieldsAndRelationships/view"


def _fillable(fields: dict[str, dict]) -> list[str]:
    """Fields people fill in: not system fields, checkboxes, long text, formulas or auto-numbers."""
    return [f["name"] for f in fields.values()
            if f["name"] not in _SYSTEM_FIELDS and f.get("type") not in _SKIP_TYPES and f.get("filterable")
            and not f.get("calculated") and not f.get("autoNumber")]


def _fill(ctx: Ctx, obj: str) -> tuple[int, dict[str, int]]:
    """All records of the object, and how many have each fillable field filled in (counted once per object)."""
    key = ("fill", obj)
    if key not in ctx.memo:
        fields = ctx.fields(obj)
        total = ctx.count(obj, recent=False)
        ctx.memo[key] = (total, ctx.filled_counts(obj, _fillable(fields)[:MAX_FILL_FIELDS], recent=False) if total else {})
    return ctx.memo[key]


def _field_item(ctx: Ctx, obj: str, f: str, note: str = "") -> dict:
    """One row of a card's field list."""
    meta = ctx.fields(obj).get(f, {})
    total, filled = _fill(ctx, obj)
    n = filled.get(f)
    return {"name": f, "label": meta.get("label") or f, "type": meta.get("type", ""), "custom": bool(meta.get("custom")),
            "filled": n, "of": total if n is not None else None, "pct": round(100 * n / total, 1) if n is not None and total else None,
            "note": note}


def _fields_card(ctx: Ctx, obj: str, title: str, value: float, unit: str, direction: str, score: float | None, *,
                 how: str, rule: str, items: list[dict], criteria: list[tuple[str, str]], out_of: tuple[int, str] | None = None) -> None:
    m = ctx.metric(f"{title} ({ctx.label(obj)})", value, unit, direction, score, how=how, rule=rule, criteria=criteria)  # type: ignore[arg-type]
    m.field_list = items
    if out_of:
        m.out_of, m.out_of_label = out_of


def all_fields(ctx: Ctx, obj: str) -> None:
    fields = ctx.fields(obj)
    total, _ = _fill(ctx, obj)
    custom = [f for f in fields.values() if f.get("custom")]
    formula = [f for f in fields.values() if f.get("calculated")]
    required = [f for f in fields.values() if not f.get("nillable", True) and f.get("createable") and not f.get("defaultedOnCreate")]
    items = sorted((_field_item(ctx, obj, f) for f in fields), key=lambda x: (not x["custom"], x["label"].lower()))
    label = ctx.label(obj)
    _fields_card(
        ctx, obj, "All Fields", len(fields), "count", "lower-better", None,
        how=f"{label} have {len(fields):,} fields: {len(fields) - len(custom):,} from Salesforce and {len(custom):,} added in your org.",
        rule="Shown for information only; it doesn’t change the area score.",
        items=items,
        criteria=[
            ("Fields", f"{len(fields):,} in all — {len(fields) - len(custom):,} standard, {len(custom):,} custom"),
            ("Formula fields", f"{len(formula):,} (worked out by Salesforce, never typed in)"),
            ("Required", f"{len(required):,} must be filled in to save a record"),
            ("Records", f"{total:,} {label} (used for the fill rates in the list)"),
            ("Fields listed", "Every field, custom ones first, with how many records have it filled in where Salesforce can count it."),
        ],
    )


def _relied_on(ctx: Ctx, obj: str) -> tuple[list[str], list[str], dict[str, str], dict[str, dict[str, int]]]:
    """Nearly empty custom fields (filled on fewer than 20% of records) and which of them something still relies on:
    (nearly empty, relied on, field → Salesforce id, field id → what relies on it by type). Asked once per object."""
    from .core import DEFAULT_OBJECTS
    from .deep import DEPENDENT_TYPES as AUTOMATION

    key = ("relied_on", obj)
    if key in ctx.memo:
        return ctx.memo[key]
    dependent = {**AUTOMATION, "CustomField": "formula field"}  # formulas that read the field rely on it too
    out: tuple = ([], [], {}, {})
    total, filled = _fill(ctx, obj)
    if obj in DEFAULT_OBJECTS and total >= MIN_RECORDS:  # Salesforce lists dependencies by field id for these objects only
        rows = ctx.setup(f"SELECT Id, DeveloperName, NamespacePrefix FROM CustomField WHERE TableEnumOrId = '{obj}'")
        ids = {f"{r.get('DeveloperName')}__c": r["Id"] for r in rows if not r.get("NamespacePrefix")}
        empty = [f for f in ids if f in filled and filled[f] / total < LOW_FILL]
        deps: dict[str, dict[str, int]] = {}
        for i in range(0, len(empty), 100):
            chunk = ", ".join(f"'{ids[f]}'" for f in empty[i:i + 100])
            for r in ctx.setup("SELECT MetadataComponentType, RefMetadataComponentId FROM MetadataComponentDependency "
                               f"WHERE RefMetadataComponentId IN ({chunk})"):
                t = r.get("MetadataComponentType")
                if t in dependent:
                    d = deps.setdefault(r.get("RefMetadataComponentId"), {})
                    d[t] = d.get(t, 0) + 1
        matter = sorted((f for f in empty if deps.get(ids[f])), key=lambda f: (-sum(deps[ids[f]].values()), filled[f]))
        out = (empty, matter, ids, deps)
    ctx.memo[key] = out
    return out


def unused_low_completion_fields(ctx: Ctx, obj: str) -> None:
    """Fields people fill in (standard and custom) that are filled on fewer than 20% of records, in three bands: never filled,
    hardly ever filled (under 1%) and rarely filled (1% to under 20%)."""
    fields = ctx.fields(obj)
    total, filled = _fill(ctx, obj)
    checked = [f for f in _fillable(fields) if f in filled]
    if total < MIN_RECORDS or not checked:
        return
    try:  # fields something relies on are listed under Empty Fields Others Depend On instead, so no field is in both cards
        relied = set(_relied_on(ctx, obj)[1])
    except (Unavailable, SalesforceError):
        relied = set()  # can't tell (e.g. no "View Setup and Configuration"): every low-use field is listed here
    low = sorted((f for f in checked if filled[f] / total < LOW_FILL and f not in relied), key=lambda f: (filled[f], not fields[f].get("custom")))
    never = [f for f in low if not filled[f]]
    hardly = [f for f in low if filled[f] and filled[f] / total < UNUSED_FILL]
    rarely = [f for f in low if filled[f] / total >= UNUSED_FILL]
    score = rate_score(len(low) / len(checked), 0.5)
    label = _label(ctx, obj)

    def band(f: str) -> str:
        if not filled[f]:
            return "Never filled in"
        return f"Hardly ever filled — on {filled[f]:,} records" if filled[f] / total < UNUSED_FILL else f"Rarely filled — on {filled[f]:,} records"

    _fields_card(
        ctx, obj, "Unused & Low-Completion Fields", len(low), "count", "lower-better", score, out_of=(len(checked), "fields people fill in"),
        how=f"Fields on {label}, standard and custom, that are filled on fewer than {LOW_FILL:.0%} of records: {len(low):,} of {len(checked):,} "
        f"({len(never):,} never filled in, {len(hardly):,} on under {UNUSED_FILL:.0%}, {len(rarely):,} on {UNUSED_FILL:.0%} to under {LOW_FILL:.0%}).",
        rule="Scores 100 when every field is filled on at least 20% of records, falling evenly to 0 when half are below that. "
        "A problem is raised when the score is below 90.",
        items=[_field_item(ctx, obj, f, band(f)) for f in low],
        criteria=[
            ("Fields checked", f"{len(checked):,} fields people fill in, standard and custom ({sum(1 for f in checked if fields[f].get('custom')):,} custom); "
             "checkboxes, long text, formulas and system fields are left out"),
            ("Records", f"{total:,} {label}, all of them"),
            *([("Listed elsewhere", f"{len(relied):,} low-use fields that formulas, flows, reports or code rely on are under Empty Fields Others "
                "Depend On instead (they mustn't be deleted)")] if relied else []),
            ("Counts as unused or low-completion", f"Filled on fewer than {LOW_FILL:.0%} of records, in three bands: never filled in; hardly ever filled "
             f"(under {UNUSED_FILL:.0%}); rarely filled ({UNUSED_FILL:.0%} to under {LOW_FILL:.0%})."),
            ("Never filled in", f"{len(never):,}"),
            ("Hardly ever filled", f"{len(hardly):,}"),
            ("Rarely filled", f"{len(rarely):,}"),
            ("What's counted", f"{len(low):,} of {len(checked):,} fields; the least filled first: "
             + (", ".join(fields[f].get("label") or f for f in low[:6]) + (" …" if len(low) > 6 else "") if low else "none")),
        ],
    )
    ctx.metrics[ctx.area_id][-1].field_scores = [
        {"field": f, "label": fields[f].get("label") or f, "count": filled[f], "of": total, "pct": round(100 * filled[f] / total, 1)}
        for f in [*rarely[::-1], *hardly[::-1]][:12]  # the chart: the fields that are partly filled, most filled first
    ]
    ctx.finding(
        name=f"Unused and low-completion fields on {label}", score=score, affected=len(low), min_score=90,
        description=f"{len(low):,} of {len(checked):,} fields on {label} are filled on fewer than {LOW_FILL:.0%} of records: {len(never):,} never, "
        f"{len(hardly):,} on under {UNUSED_FILL:.0%} and {len(rarely):,} on {UNUSED_FILL:.0%} to {LOW_FILL:.0%}, e.g. "
        + ", ".join(fields[f].get("label") or f for f in low[:4]) + ".",
        why="Fields nobody fills in clutter layouts and reports, slow people down and make it unclear which field is the right one.",
        impact="Messy layouts, reports with mostly blank groups, and harder admin work.",
        action="Hide the never and hardly ever filled fields from layouts and delete the custom ones (export the few values first); for rarely "
        "filled fields that matter, make them required at the right stage.",
        obj=obj, url=ctx.list_url(obj), fix=_setup_link(obj), measure=f"Unused & Low-Completion Fields ({ctx.label(obj)})",
    )


def outdated_fields(ctx: Ctx, obj: str) -> None:
    fields = ctx.fields(obj)
    custom = [f for f in fields.values() if _own(f)]
    if not custom:
        return
    old = sorted((f for f in custom if _LEGACY.search(f["name"].removesuffix("__c")) or _LEGACY.search(f.get("label") or "")),
                 key=lambda f: (f.get("label") or f["name"]).lower())
    score = rate_score(len(old) / len(custom), 0.2)
    label = _label(ctx, obj)

    def why(f: dict) -> str:
        m = _LEGACY.search(f.get("label") or "") or _LEGACY.search(f["name"].removesuffix("__c"))
        return f"Name says “{m.group(2)}”" if m else ""

    _fields_card(
        ctx, obj, "Outdated Fields", len(old), "count", "lower-better", score, out_of=(len(custom), "custom fields"),
        how=f"Custom fields on {label} whose name or label says they’re old, a copy or a test: {len(old):,} of {len(custom):,}.",
        rule="Scores 100 when none look outdated, falling evenly to 0 when 20% do. A problem is raised when the score is below 95.",
        items=[_field_item(ctx, obj, f["name"], why(f)) for f in old],
        criteria=[
            ("Fields checked", f"{len(custom):,} custom fields built in your org (not from installed packages)"),
            ("Looks outdated", "The name or label contains old, v1/v2…, bak, backup, deprecated, legacy, do not use, DNU, copy, temp, tmp, test or unused."),
            ("What's counted", f"{len(old):,}: " + (", ".join(f.get("label") or f["name"] for f in old[:8]) + (" …" if len(old) > 8 else "") if old else "none")),
        ],
    )
    ctx.finding(
        name=f"Outdated-looking fields on {label}", score=score, affected=len(old),
        description=f"{len(old):,} custom fields on {label} are named as old, copies or tests, e.g. " + ", ".join(f.get("label") or f["name"] for f in old[:4]) + ".",
        why="People can’t tell the live field from the leftover one, so data ends up split between them.",
        impact="Data in the wrong field and reports that miss it.",
        action="Move any values worth keeping into the live field, then remove the old ones from layouts and delete them.",
        obj=obj, url=ctx.list_url(obj), fix=_setup_link(obj), measure=f"Outdated Fields ({ctx.label(obj)})",
    )


_NOISE = re.compile(r"\b(old|new|v\d+|bak|backup|copy|temp|tmp|test|legacy|deprecated|dnu|do not use|id|c)\b|\d+")


# Words that don't change what a field holds ("Phone Number" = "Phone", "Email Address" = "Email"), and different words
# for the same thing ("Deal Value" = "Amount", "Telephone" = "Phone", "Web Site" = "Website").
_FILLER = re.compile(r"\b(number|no|num|nbr|address|addr|field|info|information|details?|primary|main|custom|the|of|my)\b")
_SAME_THING = [
    (re.compile(r"\b(deal|opportunity|opp|contract|sale|sales) (value|amount|size|total)\b|\b(revenue|deal value|value)\b"), "amount"),
    (re.compile(r"\b(telephone|tel|phone no|ph)\b"), "phone"),
    (re.compile(r"\b(cell phone|mobile phone|cellphone|cell)\b"), "mobile"),  # longest first
    (re.compile(r"\be mail\b|\bemail id\b"), "email"),
    (re.compile(r"\b(web site|web|url|site|homepage)\b"), "website"),
    (re.compile(r"\b(zip|zipcode|zip code|postcode|post code|postal)\b"), "postal code"),
]


def _plain(label: str) -> str:
    """What a field holds, from its label: case, punctuation, numbers, version words and filler ignored, synonyms merged."""
    s = re.sub(r"[^a-z0-9 ]+", " ", label.lower())
    s = re.sub(r"\s+", " ", _NOISE.sub(" ", s)).strip()
    for pattern, word in _SAME_THING:
        s = pattern.sub(word, s)
    s = re.sub(r"\s+", " ", _FILLER.sub(" ", s)).strip()
    return " ".join(dict.fromkeys(s.split()))  # "postal code code" → "postal code"


def lookalike_fields(ctx: Ctx, obj: str) -> None:
    fields = ctx.fields(obj)
    # Parts of an address or map location (Billing Latitude, ShippingGeo__Latitude__s…) belong to their compound field.
    candidates = [f for f in fields.values() if f["name"] not in _SYSTEM_FIELDS and f.get("type") not in ("id", "address", "location")
                  and not f.get("compoundFieldName") and not f["name"].endswith(("__s", "__pc"))]
    if not any(_own(f) for f in candidates):
        return
    plain = {f["name"]: _plain(f.get("label") or f["name"]) for f in candidates}
    pairs: list[tuple[dict, dict]] = []
    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            if not (_own(a) or _own(b)):
                continue  # Salesforce's and packages' fields aren't yours to merge
            nums = [re.findall(r"\d+", f.get("label") or f["name"]) for f in (a, b)]
            if all(nums) and nums[0] != nums[1]:
                continue  # numbered slots ("Metric 1" / "Metric 2") are different fields; "Phone" / "Phone 2" still match
            if len(plain[a["name"]]) >= 3 and plain[a["name"]] == plain[b["name"]]:
                pairs.append((a, b))
    custom = sum(1 for f in candidates if _own(f))
    score = rate_score(len(pairs) / custom, 0.2)
    label = _label(ctx, obj)
    named = lambda f: f"{f.get('label') or f['name']} ({f['name']})"  # noqa: E731
    items = []
    for a, b in pairs:
        items.append(_field_item(ctx, obj, a["name"], f"Looks like {named(b)}"))
        items.append(_field_item(ctx, obj, b["name"], f"Looks like {named(a)}"))
    _fields_card(
        ctx, obj, "Look-alike Fields", len(pairs), "count", "lower-better", score, out_of=(custom, "custom fields"),
        how=f"Pairs of fields on {label} that seem to hold the same thing, e.g. Phone and Phone Number (at least one built in your org): {len(pairs):,}.",
        rule="Scores 100 when there are none, falling evenly to 0 when the pairs reach 20% of the custom fields. A problem is raised when the score is below 95.",
        items=items,
        criteria=[
            ("Fields compared", f"{len(candidates):,} fields, {custom:,} of them built in your org (parts of addresses and map locations left out)"),
            ("Look-alike means", "The labels mean the same once case, punctuation, numbers, version words (old, new, copy, v2, test) and filler "
             "words (number, address, info…) are ignored, and words for the same thing are merged (Deal Value = Amount, Telephone = Phone, "
             "Web Site = Website, Zip = Postal Code): “Phone Number” = “Phone”, “Email Address” = “Email”. At least one of the two is built in your org."),
            ("What's counted", f"{len(pairs):,} pairs: " + ("; ".join(f"{named(a)} ↔ {named(b)}" for a, b in pairs[:5]) + (" …" if len(pairs) > 5 else "") if pairs else "none")),
        ],
    )
    ctx.finding(
        name=f"Look-alike fields on {label}", score=score, affected=len(pairs),
        description=f"{len(pairs):,} pairs of fields on {label} seem to hold the same thing, e.g. "
        + "; ".join(f"{a.get('label')} / {b.get('label')}" for a, b in pairs[:3]) + ".",
        why="When two fields mean the same, people fill in one or the other, so neither is complete and reports disagree.",
        impact="Split data, conflicting reports and wasted admin time.",
        action="Pick the field to keep, copy the other’s values into it, update reports and automation, then retire the copy.",
        obj=obj, url=ctx.list_url(obj), fix=_setup_link(obj), measure=f"Look-alike Fields ({ctx.label(obj)})",
    )


def depended_empty_fields(ctx: Ctx, obj: str) -> None:
    from .core import DEFAULT_OBJECTS
    from .deep import DEPENDENT_TYPES as AUTOMATION, _plural

    DEPENDENT_TYPES = {**AUTOMATION, "CustomField": "formula field"}  # formulas that read the field rely on it too

    if obj not in DEFAULT_OBJECTS:
        return  # Salesforce lists dependencies by field id for these objects only
    fields = ctx.fields(obj)
    total, filled = _fill(ctx, obj)
    if total < MIN_RECORDS:
        return
    empty, matter, ids, deps = _relied_on(ctx, obj)
    score = rate_score(len(matter) / max(len(empty), 1), 0.5) if empty else 100
    label = _label(ctx, obj)
    used_by = lambda f: "Used by " + ", ".join(_plural(c, DEPENDENT_TYPES[t]) for t, c in deps[ids[f]].items())  # noqa: E731
    _fields_card(
        ctx, obj, "Empty Fields Others Depend On", len(matter), "count", "lower-better", score, out_of=(len(empty), "nearly empty custom fields"),
        how=f"Custom fields on {label} filled on fewer than {LOW_FILL:.0%} of records ({len(empty):,} found) that a formula, validation rule, "
        f"flow, workflow rule, Apex code, report or email template still uses: {len(matter):,}.",
        rule="Scores 100 when none of the nearly empty fields are relied on, falling evenly to 0 when half of them are. A problem is raised when the score is below 95.",
        items=[_field_item(ctx, obj, f, used_by(f)) for f in matter],
        criteria=[
            ("Fields checked", f"Custom fields built in your org (not from installed packages) on {label}; checkboxes, long text and formulas left out."),
            ("Nearly empty", f"Filled on fewer than {LOW_FILL:.0%} of records: {len(empty):,} fields."),
            ("Relied on", "At least one formula field, validation rule, flow, workflow rule, Apex class or trigger, report or email template uses the field, "
             "according to Salesforce’s list of what depends on what."),
            ("What's counted", f"{len(matter):,} of the {len(empty):,} nearly empty fields are relied on."),
        ],
    )
    ctx.finding(
        name=f"Nearly empty fields that reports and automation rely on ({label})", score=score, affected=len(matter),
        description=f"{len(matter):,} custom fields on {label} are filled on less than {LOW_FILL:.0%} of records, yet reports, flows or code depend on them: "
        + "; ".join(f"{fields[f].get('label') or f} ({100 * filled[f] / total:.0f}% filled) — {used_by(f).lower()}" for f in matter[:5]) + ".",
        why="A report grouped by an empty field, or a flow that branches on one, quietly gives wrong answers.",
        impact="Reports and automations that look fine but are built on missing data.",
        action="Make these fields required at the right stage, backfill the most important records, or change what relies on them.",
        obj=obj, url=ctx.list_url(obj), fix=_setup_link(obj), measure=f"Empty Fields Others Depend On ({ctx.label(obj)})",
    )


FIELD_CARDS = (all_fields, unused_low_completion_fields, outdated_fields, lookalike_fields, depended_empty_fields)


def _field_cards(ctx: Ctx, obj: str) -> None:
    for k, check in enumerate(FIELD_CARDS):
        ctx.tick(k / len(FIELD_CARDS))
        try:
            check(ctx, obj)
        except Unavailable:
            continue
        except SalesforceAuthExpired:
            raise
        except SalesforceError as exc:  # e.g. no "View Setup" for dependencies: the other cards still show
            log.warning("%s on %s skipped: %s", check.__name__, obj, exc)


def account_field_cards(ctx: Ctx) -> None:
    ctx.selected("Account")
    _field_cards(ctx, "Account")


def contact_field_cards(ctx: Ctx) -> None:
    ctx.selected("Contact")
    _field_cards(ctx, "Contact")


def lead_field_cards(ctx: Ctx) -> None:
    ctx.selected("Lead")
    _field_cards(ctx, "Lead")


def opportunity_field_cards(ctx: Ctx) -> None:
    ctx.selected("Opportunity")
    _field_cards(ctx, "Opportunity")


def other_object_field_cards(ctx: Ctx) -> None:
    for obj in ctx.selected(*ctx.others()):
        try:
            ctx.fields(obj)
        except Unavailable:
            continue
        _field_cards(ctx, obj)


SCORECARD_ORDER = ("Account", "Lead", "Contact", "Opportunity")  # the scores are listed in this order, then any others


def _object_of(ctx: Ctx, label: str) -> str | None:
    """The object a scored card is about: "Missing Key Fields (Leads)", "Duplicate Leads", "Accounts Without Contacts",
    "Stale Leads" → Lead."""
    for obj in ctx.scope.objects:
        try:
            plural = ctx.label(obj)
        except Unavailable:
            continue
        if label.endswith(f"({plural})") or label in (f"Duplicate {plural}", f"Stale {plural}") or label.startswith(f"{plural} Without"):
            return obj
    return None


def scorecard(ctx: Ctx) -> None:
    """A score (%) per object, and one for the organization.

    Object score = the average of two halves, each the plain average of that area's scored cards for the object:
    Area 1 (the data in the records: duplicates, missing and invalid values, activity…) and Area 2 (the fields: unused,
    outdated, look-alike, rarely filled, relied on while empty). An object checked in only one area uses that one.
    Overall = the plain average of the object scores. Colours: green 80%+, orange 40–79%, red below 40%."""
    by_obj: dict[str, dict[str, list[float]]] = {}
    for area in ("area-1", "area-2"):
        for m in ctx.metrics.get(area, []):
            obj = _object_of(ctx, m.label) if m.score is not None else None
            if obj:
                by_obj.setdefault(obj, {}).setdefault(area, []).append(m.score)
    order = [o for o in SCORECARD_ORDER if o in by_obj] + sorted(o for o in by_obj if o not in SCORECARD_ORDER)
    rows: list[tuple[str, str, float, float | None, float | None]] = []  # (object, plural, score, area 1 average, area 2 average)
    for obj in order:
        halves = {a: sum(v) / len(v) for a, v in by_obj[obj].items()}
        rows.append((obj, ctx.label(obj), sum(halves.values()) / len(halves), halves.get("area-1"), halves.get("area-2")))
    value = sum(r[2] for r in rows) / len(rows) if rows else 100
    half = lambda x: "—" if x is None else f"{x:.0f}%"  # noqa: E731
    m = ctx.metric(
        "Data Quality Scorecard", value, "%", "higher-better", None,
        how="A score out of 100% for each object (Account, Lead, Contact, Opportunity) and one for the organization, from the scored cards of "
        "Area 1 (the data in the records) and Area 2 (the fields).",
        rule="Object score = (average of its Area 1 cards + average of its Area 2 cards) ÷ 2 (only one area if only one was checked). "
        "Overall = the average of the object scores. Green 80%+ healthy, orange 40–79% needs a look, red below 40% needs work. "
        "Shown for information only; it doesn’t change the area score.",
        criteria=[
            *[(f"{ctx.label(o, plural=False)} score", f"{sc:.0f}% — Area 1: {half(a1)}, Area 2: {half(a2)}") for o, _, sc, a1, a2 in rows],
            ("Overall Data Quality score", f"{value:.0f}% — the average of the {len(rows)} objects" if rows else "Nothing scored yet"),
            ("Area 1 cards", "Duplicates, Missing Key Fields, Data Standardization, No Activity in 6 Months and the object’s own cards "
             "(e.g. Accounts Without Open Opportunities), when Area 1 is checked in the same run."),
            ("Area 2 cards", "Unused & Low-Completion, Outdated, Look-alike and Empty Fields Others Depend On (All Fields isn’t scored)."),
        ],
    )
    m.field_scores = [{"field": p, "label": p, "count": round(sc), "of": 100, "pct": round(sc, 1)} for _, p, sc, _, _ in rows]


AREAS = {
    "area-1": [account_cards, contact_cards, lead_cards, opportunity_cards, other_object_cards],
    "area-2": [account_field_cards, contact_field_cards, lead_field_cards, opportunity_field_cards, other_object_field_cards, scorecard],
}

STEP_LABELS = {
    account_cards: "Checking Accounts: duplicates, missing fields, formats, activity",
    contact_cards: "Checking Contacts: duplicates, missing fields, formats, activity",
    lead_cards: "Checking Leads: duplicates, missing fields, formats, activity",
    opportunity_cards: "Checking Opportunities: duplicates, missing fields, formats, activity",
    other_object_cards: "Checking your other objects",
    account_field_cards: "Checking Account fields: unused & low-completion, outdated, look-alike",
    contact_field_cards: "Checking Contact fields: unused & low-completion, outdated, look-alike",
    lead_field_cards: "Checking Lead fields: unused & low-completion, outdated, look-alike",
    opportunity_field_cards: "Checking Opportunity fields: unused & low-completion, outdated, look-alike",
    other_object_field_cards: "Checking the fields of your other objects",
    scorecard: "Grading each object",
}
