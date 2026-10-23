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


# ---------------------------------------------------------------- area 2: redundant fields & scorecard

KEY_FIELDS: dict[str, tuple[str, ...]] = {
    "Account": ("Industry", "Phone", "Website", "Type", "BillingCountry", "NumberOfEmployees"),
    "Contact": ("Email", "Phone", "Title", "AccountId", "MailingCountry"),
    "Lead": ("Email", "Phone", "Company", "Title", "LeadSource", "Industry", "Country"),
    "Opportunity": ("Amount", "NextStep", "LeadSource", "Type"),
}

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


def field_completeness(ctx: Ctx) -> None:
    slots = missing_total = 0
    incomplete_records: list[tuple[str, ...]] = []  # records missing at least one key field, per object
    per_obj: list[tuple[str, int, int, float, list[str], int]] = []  # (object, records, incomplete, % filled, key fields, empty values)
    for obj in ctx.selected(*KEY_FIELDS, *ctx.others()):
        try:
            fields = ctx.fields(obj)
        except Unavailable:
            continue
        total = _base_total(ctx, obj)
        if not total:
            continue
        keys = [f for f in KEY_FIELDS.get(obj, ()) if ctx.has_field(obj, f)] or _generic_key_fields(fields)
        base = BASE_CONDS.get(obj, ())
        filled_by = ctx.filled_counts(obj, keys, *base)
        rows = [(f, total - filled_by[f]) for f in keys if f in filled_by]
        if not rows:
            continue
        any_missing = "(" + " OR ".join(f"{f} = null" for f, _ in rows) + ")"
        incomplete = ctx.count(obj, *base, any_missing)
        incomplete_records.append((obj, *base, any_missing))
        slots += total * len(rows)
        missing_total += sum(m for _, m in rows)
        obj_pct = 100 - pct(sum(m for _, m in rows), total * len(rows))
        ctx.stat(obj).completeness = round(obj_pct, 1)
        per_obj.append((obj, total, incomplete, obj_pct, [fields[f].get("label") or f for f, _ in rows], sum(m for _, m in rows)))
        worst = sorted(rows, key=lambda r: -r[1])[:4]
        label = _label(ctx, obj)
        ctx.finding(
            name=f"{_cap(label)} are missing key details",
            score=range_score(obj_pct, 50, 95),
            affected=incomplete,
            description=f"{incomplete:,} of {total:,} {label} are missing at least one key detail; key fields are {obj_pct:.0f}% filled in overall. Least complete: "
            + ", ".join(f"{fields[f].get('label') or f} ({100 - pct(m, total):.0f}% filled)" for f, m in worst)
            + ".",
            why="Missing details make records hard to act on and make reports by industry, source, or region unreliable.",
            impact="Poor targeting, weak forecasts, and time lost looking for information.",
            action=f"Fill the gaps (start with the least complete fields), and make the most important ones required on the {ctx.label(obj, plural=False)} layout or with a validation rule.",
            obj=obj,
            url=ctx.list_url(obj),
            min_score=90,
            records=(obj, *base, any_missing),
            fix=f"/lightning/setup/ObjectManager/{obj}/FieldsAndRelationships/view",
        )
    complete = 100 - pct(missing_total, slots) if slots else 100
    key_columns = ["Name"] + list(dict.fromkeys(f for r in incomplete_records for f in re.findall(r"(\w+) = null", r[-1])))
    ctx.metric(
        "Field completeness", complete, "%", "higher-better", range_score(complete, 50, 95),
        how="How many of the key fields are filled in, across every chosen object: for example industry, phone and website on Accounts, "
        "email and title on Contacts, company and lead source on open Leads, and amount and next step on Opportunities.",
        rule="0 at 50% filled in or below, 100 at 95% or above, in proportion in between. "
        "A problem is raised for an object when its own score is below 90.",
        records=incomplete_records,
        columns=key_columns,
        order="Name",
        criteria=[
            ("Records checked", "; ".join(f"{n:,} {_label(ctx, o)}" for o, n, *_ in per_obj) + _window(ctx) if per_obj else "No records to check"),
            ("Fields checked", "; ".join(f"{_cap(_label(ctx, o))}: {', '.join(k)}" for o, _, _, _, k, _ in per_obj) if per_obj else ""),
            ("Other objects", "Objects without a set list use up to 8 fields people can fill in and that aren’t required (standard fields first, "
             "then custom), skipping checkboxes, long text, formulas and auto-numbers."),
            ("Counts as missing", "The field is empty."),
            ("What's counted", "; ".join(f"{_cap(_label(ctx, o))} {p:.0f}% filled ({i:,} of {n:,} missing at least one)" for o, n, i, p, _, _ in per_obj)
             + f" — {slots - missing_total:,} of {slots:,} key values filled in all." if per_obj else ""),
            ("Flagged when", "An object’s key fields are less than about 90% filled in (its own score drops below 90)."),
            ("Records listed", "Every record missing at least one key field, per object, sorted by name."),
        ],
    )
    ctx.metric(
        "Missing field values", missing_total, "count", "lower-better", None,
        how="The total number of empty key fields across every chosen object (one record missing three key fields counts as three).",
        rule="Shown for information only; it doesn’t change the area score.",
        records=incomplete_records,
        columns=key_columns,
        order="Name",
        criteria=[
            ("Records checked", "; ".join(f"{n:,} {_label(ctx, o)}" for o, n, *_ in per_obj) + _window(ctx) if per_obj else "No records to check"),
            ("Fields checked", "The same key fields as Field completeness"),
            ("What's counted", "; ".join(f"{e:,} empty values on {_label(ctx, o)}" for o, *_, e in per_obj)
             + f" — {missing_total:,} in all. One record missing three key fields counts three times." if per_obj else ""),
            ("Records listed", "Every record missing at least one key field, per object, sorted by name."),
        ],
    )


_LEGACY = re.compile(r"(^|[_\s])(old|v\d+|bak|backup|deprecated|legacy|do not use|dnu|copy|temp|tmp|test|unused)([_\s]|$)", re.I)
MAX_USAGE_CHECKS = 200  # per object; counted 50 at a time


def redundant_fields(ctx: Ctx) -> None:
    flagged_total = checked_total = 0
    per_obj: list[tuple[str, int, int]] = []  # (object, flagged fields, custom fields), for the rule table
    for obj in ctx.selected(*KEY_FIELDS, *ctx.others()):
        try:
            fields = ctx.fields(obj)
        except Unavailable:
            continue
        custom = [f for f in fields.values() if f.get("custom") and f.get("type") != "boolean" and not f.get("calculated")]
        total = ctx.count(obj, recent=False) if custom else 0
        flagged: list[str] = []
        legacy = [f for f in custom if _LEGACY.search(f["name"].removesuffix("__c")) or _LEGACY.search(f.get("label") or "")]
        flagged += [f"{f['name']} (looks outdated)" for f in legacy]
        to_count = [f["name"] for f in custom if f not in legacy and f.get("filterable") and f.get("type") not in _SKIP_TYPES][:MAX_USAGE_CHECKS]
        usage = ctx.filled_counts(obj, to_count, recent=False) if total >= 20 and to_count else {}
        for f in custom:
            if f["name"] in usage:
                used = usage[f["name"]]
                if used == 0:
                    flagged.append(f"{f['name']} (never filled in)")
                elif total >= 100 and used / total < 0.01:
                    flagged.append(f"{f['name']} (filled on {used} of {total:,} records)")
        flagged_total += len(flagged)
        checked_total += len(custom)
        if custom:
            per_obj.append((obj, len(flagged), len(custom)))
        if custom:
            label = ctx.label(obj)
            ctx.finding(
                name=f"Unused or outdated custom fields on {label}",
                score=rate_score(len(flagged) / len(custom), 0.4),
                affected=len(flagged),
                description=f"{len(flagged)} of {len(custom)} custom fields on {label} look unused or outdated: "
                + "; ".join(flagged[:10])
                + (" …" if len(flagged) > 10 else "")
                + ".",
                why="Cluttered pages slow people down, and similar-looking fields lead to data being entered in the wrong place.",
                impact="Lower adoption, inconsistent data, and higher admin effort.",
                action="Confirm with the business, remove these fields from page layouts, then delete or archive them. Dynamic Forms can also hide fields that only matter sometimes.",
                obj=obj,
                min_score=90,
                fix=f"/lightning/setup/ObjectManager/{obj}/FieldsAndRelationships/view",
            )
    score = rate_score(flagged_total / checked_total, 0.4) if checked_total else 100
    ctx.metric(
        "Redundant fields", flagged_total, "count", "lower-better", score,
        how=f"Custom fields (not checkboxes or formulas) on the chosen objects that look outdated by their name, such as “old”, “backup”, “test” or “do not use”, "
        f"or that are never filled in or filled on fewer than 1% of records. We checked {checked_total:,} custom fields.",
        rule="Scores 100 when no custom field looks unused, falling evenly to 0 when 40% of them do. "
        "A problem is raised for an object when its own score is below 90.",
        criteria=[
            ("Fields checked", "; ".join(f"{c:,} custom fields on {ctx.label(o)}" for o, _, c in per_obj)
             + ". Checkboxes and formula fields are left out." if per_obj else "No custom fields on the chosen objects"),
            ("Looks outdated", "The field’s name or label contains a word such as old, v1/v2…, bak, backup, deprecated, legacy, "
             "do not use, DNU, copy, temp, tmp, test or unused."),
            ("Never filled in", "Empty on every record (checked only on objects with at least 20 records, across all records, "
             f"up to {MAX_USAGE_CHECKS} fields per object; long text and similar fields can’t be counted)."),
            ("Hardly used", "Filled on fewer than 1% of records (checked only on objects with at least 100 records)."),
            ("What's counted", "; ".join(f"{f:,} of {c:,} on {ctx.label(o)}" for o, f, c in per_obj)
             + f" — {flagged_total:,} of {checked_total:,} custom fields in all." if per_obj else ""),
            ("Flagged when", "More than 4% of an object’s custom fields look unused or outdated (its own score drops below 90)."),
        ],
    )


def scorecard(ctx: Ctx) -> None:
    """Summary of every scored data quality indicator measured in this run."""
    scores = [m.score for area in ("area-1", "area-2") for m in ctx.metrics.get(area, []) if m.score is not None]
    value = sum(scores) / len(scores) if scores else 100
    ctx.metric(
        "Data quality scorecard", value, "%", "higher-better", None,
        how=f"The average of the {len(scores)} scored data quality measures above (duplicates, missing details, consistent spellings, unused fields and more).",
        rule="Shown for information only; it doesn’t change the area score.",
        criteria=[
            ("Measures included", ", ".join(f"{m.label} ({m.score:.0f})" for area in ("area-1", "area-2")
                                            for m in ctx.metrics.get(area, []) if m.score is not None) or "None were scored"),
            ("What's counted", f"The plain average of those {len(scores)} scores: {value:.0f}%. Every measure counts equally."),
            ("Left out", "Measures shown for information only, and checks that couldn’t run in this org."),
        ],
    )


AREAS = {
    "area-1": [account_cards, contact_cards, lead_cards, opportunity_cards, other_object_cards],
    "area-2": [field_completeness, redundant_fields, scorecard],
}

STEP_LABELS = {
    account_cards: "Checking Accounts: duplicates, missing fields, formats, activity",
    contact_cards: "Checking Contacts: duplicates, missing fields, formats, activity",
    lead_cards: "Checking Leads: duplicates, missing fields, formats, activity",
    opportunity_cards: "Checking Opportunities: duplicates, missing fields, formats, activity",
    other_object_cards: "Checking your other objects",
    field_completeness: "Measuring how complete key fields are",
    redundant_fields: "Looking for unused custom fields",
    scorecard: "Building the data quality scorecard",
}
