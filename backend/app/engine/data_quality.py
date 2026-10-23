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

from ..salesforce import duplicates as dupes
from ..salesforce.errors import SalesforceAuthExpired, SalesforceError
from .core import Ctx, FindingDraft, Unavailable, pct, range_score, rate_score

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
# 6 Months. Accounts also get Accounts Without Contacts and Accounts Without Open Opportunities. Lead, Account, Contact
# and Opportunity use the fields below; any other object uses every field people fill in.

DUP_FIELDS: dict[str, tuple[str, ...]] = {
    "Lead": ("LastName", "Company", "Email", "Phone", "Title", "State", "City", "PostalCode"),
    "Account": ("Website", "Phone", "BillingState", "BillingCity", "BillingPostalCode", "Title"),
    "Contact": ("LastName", "Email", "Phone", "MailingState", "MailingCity", "MailingPostalCode"),
    "Opportunity": ("Amount", "CloseDate"),
}
KEY_FIELDS_BY_OBJECT: dict[str, tuple[str, ...]] = {
    "Lead": ("LastName", "Title", "Company", "Email", "Phone", "State", "City", "PostalCode", "LeadSource"),
    "Account": ("Website", "Phone", "BillingState", "BillingCity", "BillingPostalCode", "Title"),
    "Contact": ("LastName", "Email", "Phone", "MailingState", "MailingCity", "MailingPostalCode"),
    "Opportunity": ("Amount", "CloseDate"),
}
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
    kinds = {f: _dup_kind(f, fields[f], name_field) for f in keys}
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
    for f in strong:  # identifying fields only: places, titles and surnames are shared by design
        if kinds[f] == "amount":
            continue
        norm = [_same_value(kinds[f], v[f]) for v in vals if filled(v[f])]
        norm = [n for n in norm if n]
        if norm:
            seen = Counter(norm)
            _by_field(ctx, obj, "duplicates", f, sum(1 for n in norm if seen[n] > 1), len(norm))  # records sharing their value
    score = rate_score(extra / total, 0.15)
    label = _label(ctx, obj)
    ids = [rows[i]["Id"] for g in groups for i in g if rows[i].get("Id")]
    names = ", ".join(_flabel(ctx, obj, f) for f in keys)

    def show(g: list[int]) -> str:
        r = rows[g[0]]
        return f"“{r.get(name_field) or r.get('Id')}” ({len(g)})"

    records = _listed(ctx, obj, ids)
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
            ("Duplicate means", "Every one of these fields that both records have filled in matches, at least two of them match, and one of those is "
             + ", ".join(_flabel(ctx, obj, f) for f in strong) + ". A blank field is skipped, never matched."),
            ("How values match", "; ".join(f"{_flabel(ctx, obj, f)}: {'exact value' if kinds[f] in ('name', 'amount') else dupes.KINDS[kinds[f]][0]}" for f in keys)),
            ("Duplicate group", "Records that all match the group's first record (no chains of near-matches)."),
            ("What's counted", f"The extra copies in each group (group size minus the one you keep): {extra:,} in {len(groups):,} groups."),
            ("Records listed", f"Every record in a duplicate group, including the one you'd keep (up to {LISTED})."),
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
        columns=["Name", *keys[:12], "OwnerId", "CreatedDate"],
        order="Name",
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

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$")
_PROVIDERS = ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com")
_STD_RULES = {
    "text": "the same value written different ways (upper/lower case, punctuation, spacing; the most common way counts as right), or extra spaces",
    "country": "the same country written different ways (“USA” / “United States”); the most common spelling counts as right",
    "state": "the same state written different ways (“California” / “CA”); the most common spelling counts as right",
    "email": "not a valid address, spaces in it, or a misspelled common domain (“gmial.com”, “yaho.com”)",
    "phone": "too few or too many digits (under 7 or over 15), or written in a different format from the one most used",
    "website": "not a valid web address, or written differently from the usual form (with or without http:// and www.)",
    "postal": "a different format from the one most used (for example 5 digits vs 5+4) ",
    "amount": "zero or negative",
    "date": "an open deal whose close date has passed, or a date before 2000 or more than 5 years ahead",
}


def _edits(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _std_kind(f: str, field: dict) -> str:
    t = field.get("type")
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
    return "text"


def _spelled(items: list[tuple[str, str]], key) -> set[str]:
    """Same value written different ways: the most common writing is right, the others are odd."""
    buckets: dict[str, Counter] = defaultdict(Counter)
    for _, v in items:
        if k := key(v):
            buckets[k][v] += 1
    usual = {k: c.most_common(1)[0][0] for k, c in buckets.items()}
    return {i for i, v in items if (k := key(v)) and v != usual[k]}


def _unusual(items: list[tuple[str, str]], shape) -> set[str]:
    """Values written in a different shape from the one most used."""
    counts = Counter(shape(v) for _, v in items)
    if len(counts) < 2:
        return set()
    usual = counts.most_common(1)[0][0]
    return {i for i, v in items if shape(v) != usual}


def _odd_values(kind: str, items: list[tuple[str, object]], open_ids: set[str]) -> set[str]:
    from datetime import date, timedelta

    text = [(i, str(v)) for i, v in items]
    generic = lambda v: re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", v.lower())).strip()  # noqa: E731
    if kind == "text":
        return _spelled(text, generic) | {i for i, v in text if v != " ".join(v.split())}
    if kind in ("country", "state"):
        return _spelled(text, lambda v: _norm(v, _COUNTRY if kind == "country" else _STATES))
    if kind == "email":
        def bad(v: str) -> bool:
            s = v.strip().lower()
            domain = s.rsplit("@", 1)[-1]
            return v != v.strip() or not _EMAIL.match(s) or any(0 < _edits(domain, p) <= 2 for p in _PROVIDERS)
        return {i for i, v in text if bad(v)}
    if kind == "phone":
        digits = lambda v: len(re.sub(r"\D", "", v))  # noqa: E731
        invalid = {i for i, v in text if not 7 <= digits(v) <= 15}
        return invalid | _unusual([(i, v) for i, v in text if i not in invalid], lambda v: re.sub(r"\d", "9", v))
    if kind == "website":
        invalid = {i for i, v in text if " " in v.strip() or "@" in v or "." not in v}
        form = lambda v: (bool(re.match(r"^[a-z]+://", v.strip().lower())), "www." in v.lower())  # noqa: E731
        return invalid | _unusual([(i, v) for i, v in text if i not in invalid], form)
    if kind == "postal":
        return _unusual(text, lambda v: re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", v.strip())))
    if kind == "amount":
        return {i for i, v in items if isinstance(v, (int, float)) and v <= 0}
    if kind == "date":
        today = date.today()
        out = set()
        for i, v in text:
            try:
                d = date.fromisoformat(v[:10])
            except ValueError:
                out.add(i)
                continue
            if d.year < 2000 or d > today + timedelta(days=5 * 365) or (i in open_ids and d < today):
                out.add(i)
        return out
    return set()


def data_standardization(ctx: Ctx, obj: str) -> None:
    fields = ctx.fields(obj)
    if obj in KEY_FIELDS_BY_OBJECT:
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
    for f in keys:
        kind = _std_kind(f, fields[f])
        items = [(r["Id"], r[f]) for r in rows if r.get("Id") and r.get(f) not in (None, "")]
        with_value.update(i for i, _ in items)
        odd = _odd_values(kind, items, open_ids)
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
        columns=["Name", *keys[:12], "OwnerId"],
        order="Name",
        criteria=[
            ("Records checked", f"{len(rows):,} {label}{_window(ctx)}" + (f" (the first {CARD_ROWS:,})" if len(rows) >= CARD_ROWS else "")),
            ("Fields checked", ", ".join(_flabel(ctx, obj, f) for f in keys) + ("" if obj in KEY_FIELDS_BY_OBJECT else " (text fields people fill in)")),
            ("Counts as odd", "; ".join(f"{_flabel(ctx, obj, f)}: {_STD_RULES[k].strip()}" for f, k, _, _ in per_field)),
            ("Found per field", "; ".join(f"{_flabel(ctx, obj, f)} {n:,}" + (f" (e.g. {', '.join(f'“{e}”' for e in ex)})" if ex else "")
                                          for f, _, n, ex in per_field)),
            ("What's counted", f"{len(bad):,} {label} with at least one odd value; a record with several counts once."),
            ("Records listed", f"Records with an odd value (up to {LISTED}), sorted by name."),
        ],
    )
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
    ctx.metric(
        f"No Activity in 6 Months ({ctx.label(obj)})", pct(n, total), "%", "lower-better", None,
        how=f"{_cap(label)} with no {what} in the last 6 months: {n:,} out of {total:,}.",
        rule="Shown for information only; it doesn’t change the area score.",
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


# ---------------- account extras

def accounts_without_contacts(ctx: Ctx, obj: str = "Account") -> None:
    total = _base_total(ctx, "Account")
    cond = "Id NOT IN (SELECT AccountId FROM Contact WHERE AccountId != null)"
    n = ctx.count("Account", cond) if total else 0
    score = rate_score(n / total, 0.5) if total else 100
    ctx.metric(
        "Accounts Without Contacts", n, "count", "lower-better", score,
        how=f"Accounts that have no Contacts linked to them, out of {total:,} Accounts.",
        rule="Scores 100 when every Account has at least one Contact, falling evenly to 0 when 50% have none.",
        records=("Account", cond),
        columns=["Name", "Type", "Industry", "Phone", "OwnerId", "LastActivityDate", "CreatedDate"],
        order="Name",
        criteria=[
            ("Records checked", f"{total:,} Accounts" + _window(ctx)),
            ("Counts as no Contacts", "No Contact record has this Account as its Account. Contacts linked through other relationships aren’t counted."),
            ("What's counted", f"{n:,} of {total:,} Accounts ({pct(n, total):.0f}%) with no Contacts."),
            ("Flagged when", "More than 2.5% of Accounts have no Contacts (the score drops below 95)."),
            ("Records listed", "Every Account with no Contacts, sorted by name."),
        ],
    )
    ctx.finding(
        name="Accounts with no Contacts",
        score=score,
        affected=n,
        description=f"{n:,} of {total:,} Accounts ({pct(n, total):.0f}%) have no Contacts.",
        why="You can’t sell to a company if you don’t know who works there.",
        impact="Missed relationships and opportunities that stall without a known buyer.",
        action="Add the main people for important Accounts, and review Accounts with no Contacts and no activity for cleanup.",
        obj="Account",
        url=ctx.list_url("Account"),
        records=("Account", cond),
    )


def accounts_without_open_deals(ctx: Ctx, obj: str = "Account") -> None:
    ctx.fields("Opportunity")  # Unavailable when the org has no Opportunities
    total = _base_total(ctx, "Account")
    cond = "Id NOT IN (SELECT AccountId FROM Opportunity WHERE IsClosed = false AND AccountId != null)"
    n = ctx.count("Account", cond) if total else 0
    ctx.metric(
        "Accounts Without Open Opportunities", n, "count", "lower-better", None,
        how=f"Accounts with no open Opportunity, out of {total:,} Accounts.",
        rule="Shown for information only; it doesn’t change the area score (many Accounts have no deal in progress).",
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


# ---------------- one step per object (cards for an object stay together)

def _cards(ctx: Ctx, obj: str, *checks) -> None:
    for check in checks:
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
    _cards(ctx, "Account", *CORE_CARDS, accounts_without_contacts, accounts_without_open_deals)


def contact_cards(ctx: Ctx) -> None:
    ctx.selected("Contact")
    _cards(ctx, "Contact", *CORE_CARDS)


def lead_cards(ctx: Ctx) -> None:
    ctx.selected("Lead")
    _cards(ctx, "Lead", *CORE_CARDS)


def opportunity_cards(ctx: Ctx) -> None:
    ctx.selected("Opportunity")
    _cards(ctx, "Opportunity", *CORE_CARDS)


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
# Scorecard grades each object from its area 1 and area 2 results.

_LEGACY = re.compile(r"(^|[_\s])(old|v\d+|bak|backup|deprecated|legacy|do not use|dnu|copy|temp|tmp|test|unused)([_\s]|$)", re.I)
LOW_FILL = 0.2  # "low completion": filled on fewer than 20% of records
UNUSED_FILL = 0.01  # "unused": filled on fewer than 1%
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


def unused_fields(ctx: Ctx, obj: str) -> None:
    fields = ctx.fields(obj)
    total, filled = _fill(ctx, obj)
    custom = [f for f in _fillable(fields) if _own(fields[f]) and f in filled]
    if total < MIN_RECORDS or not custom:
        return
    unused = sorted((f for f in custom if filled[f] / total < UNUSED_FILL), key=lambda f: filled[f])
    score = rate_score(len(unused) / len(custom), 0.4)
    label = _label(ctx, obj)
    items = [_field_item(ctx, obj, f, "Never filled in" if not filled[f] else f"Filled on only {filled[f]:,} records") for f in unused]
    _fields_card(
        ctx, obj, "Unused Fields", len(unused), "count", "lower-better", score, out_of=(len(custom), "custom fields"),
        how=f"Custom fields built in your org on {label} that are never filled in, or filled on fewer than {UNUSED_FILL:.0%} of records: "
        f"{len(unused):,} of {len(custom):,}.",
        rule="Scores 100 when every custom field is used, falling evenly to 0 when 40% are unused. A problem is raised when the score is below 90.",
        items=items,
        criteria=[
            ("Fields checked", f"{len(custom):,} custom fields people fill in, built in your org (fields from installed packages, checkboxes, "
             "long text and formulas are left out)"),
            ("Records", f"{total:,} {label}, all of them"),
            ("Counts as unused", f"Filled on fewer than {UNUSED_FILL:.0%} of records (or never)."),
            ("What's counted", f"{len(unused):,} unused: "
             + (", ".join(fields[f].get("label") or f for f in unused[:8]) + (" …" if len(unused) > 8 else "") if unused else "none")),
        ],
    )
    ctx.finding(
        name=f"Unused custom fields on {label}", score=score, affected=len(unused), min_score=90,
        description=f"{len(unused):,} of {len(custom):,} custom fields on {label} are never or hardly ever filled in, e.g. "
        + ", ".join(fields[f].get("label") or f for f in unused[:4]) + ".",
        why="Unused fields clutter page layouts and reports, slow people down and make it unclear which field is the right one.",
        impact="Messy layouts, confused users and harder admin work.",
        action="Check with the owners, then hide these fields from layouts or delete them (export the few values first).",
        obj=obj, url=ctx.list_url(obj), fix=_setup_link(obj), measure=f"Unused Fields ({ctx.label(obj)})",
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


def _plain(label: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", label.lower())
    return re.sub(r"\s+", " ", _NOISE.sub(" ", s)).strip()


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
        how=f"Pairs of fields on {label} with the same name once words like old, copy or 2 are ignored (at least one built in your org): {len(pairs):,}.",
        rule="Scores 100 when there are none, falling evenly to 0 when the pairs reach 20% of the custom fields. A problem is raised when the score is below 95.",
        items=items,
        criteria=[
            ("Fields compared", f"{len(candidates):,} fields, {custom:,} of them built in your org (parts of addresses and map locations left out)"),
            ("Look-alike means", "The labels match once case, punctuation, numbers and words like old, new, copy, v2 or test are ignored "
             "(“Phone 2” = “Phone”, “Old Title” = “Title”). At least one of the two is built in your org."),
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


def low_completion_fields(ctx: Ctx, obj: str) -> None:
    fields = ctx.fields(obj)
    total, filled = _fill(ctx, obj)
    checked = [f for f in _fillable(fields) if f in filled]
    if total < MIN_RECORDS or not checked:
        return
    low = sorted((f for f in checked if filled[f] / total < LOW_FILL), key=lambda f: filled[f])
    score = rate_score(len(low) / len(checked), 0.5)
    label = _label(ctx, obj)
    _fields_card(
        ctx, obj, "Low-Completion Fields", len(low), "count", "lower-better", score, out_of=(len(checked), "fields people fill in"),
        how=f"Fields on {label} filled on fewer than {LOW_FILL:.0%} of records: {len(low):,} of {len(checked):,}.",
        rule="Scores 100 when every field is filled on at least 20% of records, falling evenly to 0 when half are below that. "
        "A problem is raised when the score is below 90.",
        items=[_field_item(ctx, obj, f) for f in low],
        criteria=[
            ("Fields checked", f"{len(checked):,} fields people fill in, standard and custom (checkboxes, long text, formulas and system fields are left out)"),
            ("Records", f"{total:,} {label}, all of them"),
            ("Counts as low", f"Filled on fewer than {LOW_FILL:.0%} of records."),
            ("What's counted", f"{len(low):,} fields; the least filled: "
             + (", ".join(f"{fields[f].get('label') or f} ({100 * filled[f] / total:.0f}%)" for f in low[:6]) if low else "none")),
        ],
    )
    ctx.metrics[ctx.area_id][-1].field_scores = [
        {"field": f, "label": fields[f].get("label") or f, "count": filled[f], "of": total, "pct": round(100 * filled[f] / total, 1)}
        for f in low[:12]
    ]
    ctx.finding(
        name=f"Rarely filled fields on {label}", score=score, affected=len(low), min_score=90,
        description=f"{len(low):,} of {len(checked):,} fields on {label} are filled on fewer than {LOW_FILL:.0%} of records, e.g. "
        + ", ".join(f"{fields[f].get('label') or f} ({100 * filled[f] / total:.0f}%)" for f in low[:4]) + ".",
        why="Fields nobody fills in make layouts longer and reports that group by them misleading.",
        impact="Reports with mostly blank groups and slower data entry.",
        action="Decide which of these fields matter: make those required at the right moment, and remove the rest from layouts.",
        obj=obj, url=ctx.list_url(obj), fix=_setup_link(obj), measure=f"Low-Completion Fields ({ctx.label(obj)})",
    )


def depended_empty_fields(ctx: Ctx, obj: str) -> None:
    from .core import DEFAULT_OBJECTS
    from .deep import DEPENDENT_TYPES, _plural

    if obj not in DEFAULT_OBJECTS:
        return  # Salesforce lists dependencies by field id for these objects only
    fields = ctx.fields(obj)
    total, filled = _fill(ctx, obj)
    if total < MIN_RECORDS:
        return
    rows = ctx.setup(f"SELECT Id, DeveloperName, NamespacePrefix FROM CustomField WHERE TableEnumOrId = '{obj}'")
    ids = {f"{r.get('DeveloperName')}__c": r["Id"] for r in rows if not r.get("NamespacePrefix")}
    empty = [f for f in ids if f in filled and filled[f] / total < LOW_FILL]
    deps: dict[str, dict[str, int]] = {}
    for i in range(0, len(empty), 100):
        chunk = ", ".join(f"'{ids[f]}'" for f in empty[i:i + 100])
        for r in ctx.setup("SELECT MetadataComponentType, RefMetadataComponentId FROM MetadataComponentDependency "
                           f"WHERE RefMetadataComponentId IN ({chunk})"):
            t = r.get("MetadataComponentType")
            if t in DEPENDENT_TYPES:
                d = deps.setdefault(r.get("RefMetadataComponentId"), {})
                d[t] = d.get(t, 0) + 1
    matter = sorted((f for f in empty if deps.get(ids[f])), key=lambda f: (-sum(deps[ids[f]].values()), filled[f]))
    score = rate_score(len(matter) / max(len(empty), 1), 0.5) if empty else 100
    label = _label(ctx, obj)
    used_by = lambda f: "Used by " + ", ".join(_plural(c, DEPENDENT_TYPES[t]) for t, c in deps[ids[f]].items())  # noqa: E731
    _fields_card(
        ctx, obj, "Empty Fields Others Depend On", len(matter), "count", "lower-better", score, out_of=(len(empty), "nearly empty custom fields"),
        how=f"Custom fields on {label} filled on fewer than {LOW_FILL:.0%} of records ({len(empty):,} found) that a report, flow, Apex code, "
        f"validation rule, workflow rule or email template still uses: {len(matter):,}.",
        rule="Scores 100 when none of the nearly empty fields are relied on, falling evenly to 0 when half of them are. A problem is raised when the score is below 95.",
        items=[_field_item(ctx, obj, f, used_by(f)) for f in matter],
        criteria=[
            ("Fields checked", f"Custom fields built in your org (not from installed packages) on {label}; checkboxes, long text and formulas left out."),
            ("Nearly empty", f"Filled on fewer than {LOW_FILL:.0%} of records: {len(empty):,} fields."),
            ("Relied on", "At least one report, flow, Apex class or trigger, validation rule, workflow rule or email template uses the field, "
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


FIELD_CARDS = (all_fields, unused_fields, outdated_fields, lookalike_fields, low_completion_fields, depended_empty_fields)


def _field_cards(ctx: Ctx, obj: str) -> None:
    for check in FIELD_CARDS:
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


def _grade(score: float) -> str:
    return "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"


def scorecard(ctx: Ctx) -> None:
    """A grade per object from its scored area 1 and area 2 measures, and one overall."""
    per_obj: list[tuple[str, float, int]] = []
    for obj in ctx.scope.objects:
        try:
            plural = ctx.label(obj)
        except Unavailable:
            continue
        mine = [m.score for area in ("area-1", "area-2") for m in ctx.metrics.get(area, [])
                if m.score is not None and (m.label.endswith(f"({plural})") or m.label == f"Duplicate {plural}" or m.label.startswith(f"{plural} Without"))]
        if mine:
            per_obj.append((plural, sum(mine) / len(mine), len(mine)))
    value = sum(s for _, s, _ in per_obj) / len(per_obj) if per_obj else 100
    m = ctx.metric(
        "Data Quality Scorecard", value, "%", "higher-better", None,
        how="A grade for each chosen object from its scored duplicates, missing fields, formats and field-health measures, and the average of them all.",
        rule="Shown for information only; it doesn’t change the area score. Grades: A 90+, B 80–89, C 70–79, D 60–69, F below 60.",
        criteria=[
            ("Grades", "; ".join(f"{p}: {_grade(s)} ({s:.0f}, from {n} measures)" for p, s, n in per_obj) or "Nothing scored yet"),
            ("Overall", f"{_grade(value)} ({value:.0f}) — the plain average of the objects’ scores"),
            ("Measures included", "Every scored card of each object from this check: Duplicates, Key Fields & Standardization (area 1, "
             "when checked together) and this area."),
        ],
    )
    m.field_scores = [{"field": p, "label": f"{p} ({_grade(s)})", "count": round(s), "of": 100, "pct": round(s, 1)} for p, s, _ in per_obj]


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
    account_field_cards: "Checking Account fields: unused, outdated, look-alike, rarely filled",
    contact_field_cards: "Checking Contact fields: unused, outdated, look-alike, rarely filled",
    lead_field_cards: "Checking Lead fields: unused, outdated, look-alike, rarely filled",
    opportunity_field_cards: "Checking Opportunity fields: unused, outdated, look-alike, rarely filled",
    other_object_field_cards: "Checking the fields of your other objects",
    scorecard: "Grading each object",
}
