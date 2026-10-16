"""Category 1 — Data Quality & Optimization (areas 1 and 2).

Based on the Aquarient RevenueOps Consultant Guide v1.0. Indicator labels match
src/config/categories.ts exactly.

Checks run only on the objects chosen for the run (default: Account, Contact,
Lead, Opportunity). Any other chosen object gets generic checks: duplicates by
name, key-field completeness, and unused custom fields.
"""
import re

from .core import Ctx, FindingDraft, Unavailable, in_list, pct, range_score, rate_score

OPEN_LEADS = "IsConverted = false"
BASE_CONDS = {"Lead": (OPEN_LEADS,)}  # only open Leads matter


def _label(ctx: Ctx, obj: str) -> str:
    return "open Leads" if obj == "Lead" else ctx.label(obj)


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


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


def _extra(groups: list[tuple[object, int]]) -> int:
    """Records beyond the first in each group of duplicates."""
    return sum(c - 1 for _, c in groups)


def _top(groups: list[tuple[object, int]], n: int = 3) -> str:
    return ", ".join(f"“{v}” ({c})" for v, c in groups[:n])


# Company names and websites are typed many ways; compare them in a normal form.
_COMPANY_WORDS = re.compile(r"\b(the|incorporated|inc|llc|llp|ltd|limited|corp|corporation|co|company|plc|gmbh|ag|pvt|private|pty|sa|srl|bv)\b")


def norm_company(value: object) -> str:
    s = str(value or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = _COMPANY_WORDS.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_website(value: object) -> str:
    s = str(value or "").strip().lower()
    s = re.sub(r"^[a-z]+://", "", s)
    s = re.sub(r"^www\d?\.", "", s)
    return re.split(r"[/?#:]", s, maxsplit=1)[0].strip(".")


MAX_SMART_ROWS = 50_000  # above this, fall back to exact matching in SOQL


def _clusters(rows: list[dict], key) -> list[list[dict]]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        k = key(r)
        if k:
            groups.setdefault(k, []).append(r)
    return sorted((g for g in groups.values() if len(g) > 1), key=len, reverse=True)


def duplicate_accounts(ctx: Ctx) -> None:
    ctx.selected("Account")
    total = _base_total(ctx, "Account")
    has_site = ctx.has_field("Account", "Website")
    if 0 < total <= MAX_SMART_ROWS:
        cols = "Id, Name" + (", Website" if has_site else "")
        rows = ctx.rows(f"SELECT {cols} FROM Account{ctx._where('Account', (), True)}", MAX_SMART_ROWS)
        by_name = _clusters(rows, lambda r: norm_company(r.get("Name")))
        by_site = _clusters(rows, lambda r: norm_website(r.get("Website"))) if has_site else []
    else:  # very large org: exact matches only
        by_name = [[{"Name": v}] * c for v, c in (ctx.duplicate_groups("Account", "Name") if total else [])]
        groupable = has_site and ctx.has_field("Account", "Website", "groupable")
        by_site = [[{"Website": v}] * c for v, c in (ctx.duplicate_groups("Account", "Website") if total and groupable else [])]
    extra_name, extra_site = sum(len(g) - 1 for g in by_name), sum(len(g) - 1 for g in by_site)
    extra = max(extra_name, extra_site)
    ctx.stat("Account").duplicates = extra
    score = rate_score(extra / total, 0.15) if total else 100
    ctx.metric("Duplicate Accounts", extra, "count", "lower-better", score)
    use_name = extra_name >= extra_site
    groups = by_name if use_name else by_site
    field = "Name" if use_name else "Website"

    def show(g: list[dict]) -> str:
        spellings = sorted({str(r.get(field)) for r in g if r.get(field)})
        return " / ".join(f"“{s}”" for s in spellings[:3]) + f" ({len(g)})"

    ids = [r["Id"] for g in groups for r in g if r.get("Id")]
    how = "ignoring case, punctuation, and words like Inc, LLC, Ltd" if use_name else "ignoring http, www, and page paths"
    ctx.finding(
        name="Duplicate Accounts",
        score=score,
        affected=extra,
        description=(
            f"{extra:,} extra Account records match another Account by {'name' if use_name else 'website'} "
            f"({len(groups):,} groups, {how}). Biggest: {', '.join(show(g) for g in groups[:3])}."
        ),
        why=DUP_WHY,
        impact=DUP_IMPACT,
        action="Merge the duplicates, starting with the biggest groups. Then turn on Matching Rules and Duplicate Rules for Accounts (set to Alert or Block) so new copies are caught.",
        obj="Account",
        url=ctx.list_url("Account"),
        records=("Account", ctx.ids_in(ids)) if ids else None,
        fix="/lightning/setup/DuplicateRules/home",
    )


def _email_duplicates(ctx: Ctx, obj: str, metric: str, impact: str, action: str) -> None:
    ctx.selected(obj)
    total = _base_total(ctx, obj)
    base = BASE_CONDS.get(obj, ())
    groups = ctx.duplicate_groups(obj, "Email", *base) if total and ctx.has_field(obj, "Email", "groupable") else []
    extra = _extra(groups)
    ctx.stat(obj).duplicates = extra
    score = rate_score(extra / total, 0.15) if total else 100
    ctx.metric(metric, extra, "count", "lower-better", score)
    label = _label(ctx, obj)
    ctx.finding(
        name=f"Duplicate {label}",
        score=score,
        affected=extra,
        description=f"{extra:,} extra {label} share an email address with another one ({len(groups):,} groups). Biggest: {_top(groups)}.",
        why=DUP_WHY,
        impact=impact,
        action=action,
        obj=obj,
        url=ctx.list_url(obj),
        records=(obj, *base, in_list("Email", [v for v, _ in groups])),
        fix="/lightning/setup/DuplicateRules/home",
    )


def duplicate_contacts(ctx: Ctx) -> None:
    _email_duplicates(
        ctx, "Contact", "Duplicate Contacts",
        "Customers get the same email twice, and their history is split across records.",
        "Merge Contacts that share an email. Then turn on Matching Rules and Duplicate Rules for Contacts.",
    )


def duplicate_leads(ctx: Ctx) -> None:
    _email_duplicates(
        ctx, "Lead", "Duplicate Leads",
        "Two reps can end up calling the same person, and lead-source reports are inflated.",
        "Merge duplicate Leads and turn on Duplicate Rules for Leads. Check web forms and imports, which often create copies.",
    )


def duplicate_other_objects(ctx: Ctx) -> None:
    """Any other chosen object: records that share the same name."""
    for obj in ctx.selected(*ctx.others()):
        try:
            fields = ctx.fields(obj)
        except Unavailable:
            continue
        name = next((f["name"] for f in fields.values() if f.get("nameField")), None)
        total = _base_total(ctx, obj)
        if not name or not total or not fields[name].get("groupable") or fields[name].get("autoNumber"):
            continue  # auto-numbered names (e.g. "INV-0001") are always unique
        groups = ctx.duplicate_groups(obj, name)
        extra = _extra(groups)
        ctx.stat(obj).duplicates = extra
        label = ctx.label(obj)
        ctx.finding(
            name=f"Duplicate {label}",
            score=rate_score(extra / total, 0.15),
            affected=extra,
            description=f"{extra:,} extra {label} share a name with another record ({len(groups):,} groups). Biggest: {_top(groups)}.",
            why=DUP_WHY,
            impact="Confusing records and reports that count the same thing twice.",
            action=f"Review and merge or delete the copies, and consider a Duplicate Rule for {label}.",
            obj=obj,
            url=ctx.list_url(obj),
            records=(obj, in_list(name, [v for v, _ in groups])),
        )


def _no_value_findings(ctx: Ctx, parts: list[tuple[str, int, int, tuple[str, ...]]], what: str, why: str, action: str, field: str) -> None:
    for obj, total, missing, conds in parts:
        if total:
            label = _label(ctx, obj)
            ctx.finding(
                name=f"{_cap(label)} without {what}",
                score=rate_score(missing / total, 0.5),
                affected=missing,
                description=f"{missing:,} of {total:,} {label} ({pct(missing, total):.0f}%) have no {what.removeprefix('an ').removeprefix('a ')}.",
                why=why,
                impact="Lost follow-ups and slower, less effective outreach.",
                action=action.format(obj=ctx.label(obj, plural=False)),
                obj=obj,
                url=ctx.list_url(obj),
                records=(obj, *conds),
                fix=f"/lightning/setup/ObjectManager/{obj}/FieldsAndRelationships/{field}/view",
            )


def missing_email(ctx: Ctx) -> None:
    parts = []
    for obj in ctx.selected("Contact", "Lead"):
        if not ctx.has_field(obj, "Email"):
            continue
        total = _base_total(ctx, obj)
        conds = (*BASE_CONDS.get(obj, ()), "Email = null")
        parts.append((obj, total, ctx.count(obj, *conds) if total else 0, conds))
    total, missing = sum(p[1] for p in parts), sum(p[2] for p in parts)
    ctx.metric("Missing Email", pct(missing, total), "%", "lower-better", rate_score(missing / total, 0.5) if total else 100)
    _no_value_findings(
        ctx, parts, "an email",
        "Without an email you can’t follow up, send campaigns, or spot duplicates.",
        "Fill in missing emails (an enrichment tool can help) and consider making Email required on the {obj} page layout.",
        "Email",
    )


def missing_phone(ctx: Ctx) -> None:
    parts = []
    for obj in ctx.selected("Account", "Contact", "Lead"):
        if not ctx.has_field(obj, "Phone"):
            continue
        total = _base_total(ctx, obj)
        conds = (*BASE_CONDS.get(obj, ()), "Phone = null", *(["MobilePhone = null"] if ctx.has_field(obj, "MobilePhone") else []))
        parts.append((obj, total, ctx.count(obj, *conds) if total else 0, conds))
    total, missing = sum(p[1] for p in parts), sum(p[2] for p in parts)
    ctx.metric("Missing Phone", pct(missing, total), "%", "lower-better", rate_score(missing / total, 0.6) if total else 100)
    _no_value_findings(
        ctx, parts, "a phone number",
        "Reps can’t call customers or prospects quickly, and they waste time looking numbers up.",
        "Fill in missing phone numbers, starting with the most active records. Make Phone required on the {obj} layout where it matters.",
        "Phone",
    )


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


def _inconsistent(groups: list[tuple[object, int]], table: dict[str, str]) -> tuple[int, int, list[str], list[str]]:
    """Records whose spelling differs from the most common spelling of the same place (and those spellings)."""
    buckets: dict[str, list[tuple[str, int]]] = {}
    for v, c in groups:
        buckets.setdefault(_norm(v, table), []).append((str(v), c))
    bad, examples, odd = 0, [], []
    for spellings in buckets.values():
        if len(spellings) > 1:
            spellings.sort(key=lambda s: -s[1])
            bad += sum(c for _, c in spellings[1:])
            odd += [s for s, _ in spellings[1:]]
            examples.append(" / ".join(f"“{s}”" for s, _ in spellings[:4]))
    return bad, sum(c for _, c in groups), examples, odd


_ADDRESS_FIELDS = {
    "Account": (("BillingCountry", _COUNTRY), ("BillingState", _STATES)),
    "Contact": (("MailingCountry", _COUNTRY), ("MailingState", _STATES)),
    "Lead": (("Country", _COUNTRY), ("State", _STATES)),
}


def standardization(ctx: Ctx) -> None:
    objs = ctx.selected(*_ADDRESS_FIELDS)
    picklists = ctx.has_field("Account", "BillingCountryCode", None)
    bad_total = filled_total = 0
    for obj in objs:
        bad = filled = 0
        examples: list[str] = []
        odd_conds: list[str] = []
        for fld, table in _ADDRESS_FIELDS[obj]:
            if ctx.has_field(obj, fld, "groupable"):
                b, f, ex, odd = _inconsistent(ctx.groups(obj, fld, *BASE_CONDS.get(obj, ())), table)
                bad, filled, examples = bad + b, filled + f, examples + ex
                if odd:
                    odd_conds.append(in_list(fld, odd))
        if odd_conds:
            # Count records, not spellings: a record with an odd country AND an odd state is one record.
            bad = ctx.count(obj, *BASE_CONDS.get(obj, ()), "(" + " OR ".join(odd_conds) + ")")
        bad_total, filled_total = bad_total + bad, filled_total + filled
        if bad:
            label = _label(ctx, obj)
            ctx.finding(
                name=f"Inconsistent country and state values on {label}",
                score=rate_score(bad / filled, 0.25),
                affected=bad,
                description=f"{bad:,} {label} spell their country or state differently from other records for the same place, e.g. {', '.join(examples[:3])}.",
                why="Filters and reports by region miss records, and territory assignment rules break.",
                impact="Wrong regional numbers and leads routed to the wrong team.",
                action="Clean up the spellings, then turn on State and Country/Territory Picklists so people pick from a list.",
                obj=obj,
                url=ctx.list_url(obj),
                min_score=100,
                records=(obj, *BASE_CONDS.get(obj, ()), "(" + " OR ".join(odd_conds) + ")") if odd_conds else None,
                fix="/lightning/setup/AddressCleanerOverview/home",
            )
    score = rate_score(bad_total / filled_total, 0.25) if filled_total else 100
    if not picklists:
        score = min(score, 70)
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
    ctx.metric("Data standardization issues", bad_total, "count", "lower-better", score)


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


def _generic_key_fields(fields: dict[str, dict]) -> list[str]:
    """For objects without a curated list: editable, optional, filterable fields — standard first, then custom."""
    picks = [
        f for f in fields.values()
        if f["name"] not in _SYSTEM_FIELDS and f.get("type") not in _SKIP_TYPES and f.get("filterable")
        and f.get("createable") and f.get("nillable", True) and not f.get("calculated") and not f.get("autoNumber")
    ]
    picks.sort(key=lambda f: bool(f.get("custom")))
    return [f["name"] for f in picks[:MAX_GENERIC_FIELDS]]


def field_completeness(ctx: Ctx) -> None:
    slots = missing_total = 0
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
        slots += total * len(rows)
        missing_total += sum(m for _, m in rows)
        obj_pct = 100 - pct(sum(m for _, m in rows), total * len(rows))
        ctx.stat(obj).completeness = round(obj_pct, 1)
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
    ctx.metric("Field completeness", complete, "%", "higher-better", range_score(complete, 50, 95))
    ctx.metric("Missing field values", missing_total, "count", "lower-better", None)


_LEGACY = re.compile(r"(^|[_\s])(old|v\d+|bak|backup|deprecated|legacy|do not use|dnu|copy|temp|tmp|test|unused)([_\s]|$)", re.I)
MAX_USAGE_CHECKS = 200  # per object; counted 50 at a time


def redundant_fields(ctx: Ctx) -> None:
    flagged_total = checked_total = 0
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
    ctx.metric("Redundant fields", flagged_total, "count", "lower-better", score)


def accounts_without_contacts(ctx: Ctx) -> None:
    ctx.selected("Account")
    total = _base_total(ctx, "Account")
    cond = "Id NOT IN (SELECT AccountId FROM Contact WHERE AccountId != null)"
    n = ctx.count("Account", cond) if total else 0
    score = rate_score(n / total, 0.5) if total else 100
    ctx.metric("Accounts without Contacts", n, "count", "lower-better", score)
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


def scorecard(ctx: Ctx) -> None:
    """Summary of every scored data quality indicator measured in this run."""
    scores = [m.score for area in ("area-1", "area-2") for m in ctx.metrics.get(area, []) if m.score is not None]
    value = sum(scores) / len(scores) if scores else 100
    ctx.metric("Data quality scorecard", value, "%", "higher-better", None)


AREAS = {
    "area-1": [duplicate_accounts, duplicate_contacts, duplicate_leads, duplicate_other_objects, missing_email, missing_phone, standardization],
    "area-2": [field_completeness, redundant_fields, accounts_without_contacts, scorecard],
}

STEP_LABELS = {
    duplicate_accounts: "Looking for duplicate Accounts",
    duplicate_contacts: "Looking for duplicate Contacts",
    duplicate_leads: "Looking for duplicate Leads",
    duplicate_other_objects: "Looking for duplicates in your other objects",
    missing_email: "Checking for missing emails",
    missing_phone: "Checking for missing phone numbers",
    standardization: "Checking country and state values",
    field_completeness: "Measuring how complete key fields are",
    redundant_fields: "Looking for unused custom fields",
    accounts_without_contacts: "Finding Accounts with no Contacts",
    scorecard: "Building the data quality scorecard",
}
