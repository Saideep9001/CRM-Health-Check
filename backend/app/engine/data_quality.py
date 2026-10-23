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
    use_name = extra_name >= extra_site
    groups = by_name if use_name else by_site
    field = "Name" if use_name else "Website"
    ids = [r["Id"] for g in groups for r in g if r.get("Id")]
    ctx.metric(
        "Duplicate Accounts", extra, "count", "lower-better", score,
        how=f"Accounts that share a company name or a website with another Account, out of {total:,} Accounts. "
        "We ignore case, punctuation and words like Inc or LLC (and http or www in websites), and count only the extra copies, using whichever check finds more.",
        rule="Scores 100 when there are no duplicates, falling evenly to 0 when the extra copies reach 15% of all Accounts.",
        records=("Account", ctx.ids_in(ids)) if ids else None,
        columns=["Name", "Website", "BillingCity", "Phone", "OwnerId", "CreatedDate"],
        order=field,
        criteria=[
            ("Records checked", f"{total:,} Accounts"),
            ("Compared on", "Account Name, and separately Website" if has_site else "Account Name (this org has no Website field)"),
            ("Name matching", "Ignores upper/lower case and punctuation, treats “&” as “and”, and ignores company words: "
             "The, Inc, Incorporated, LLC, LLP, Ltd, Limited, Corp, Corporation, Co, Company, PLC, GmbH, AG, Pvt, Private, Pty, SA, SRL, BV. "
             "So “Acme, Inc.” and “ACME” match."),
            ("Website matching", "Ignores http:// or https://, www., and anything after the domain (pages, ? and #). "
             "So “https://www.acme.com/about” and “acme.com” match.") if has_site else ("Website matching", ""),
            ("Duplicate group", "Two or more Accounts with the same cleaned name (or the same cleaned website). Blank values are never matched."),
            ("What's counted", f"The extra copies in each group (group size minus the one you keep): {extra_name:,} by name in {len(by_name):,} groups"
             + (f", {extra_site:,} by website in {len(by_site):,} groups" if has_site else "")
             + f". The result uses whichever is higher ({'name' if use_name else 'website'})."),
            ("Very large orgs", f"Above {MAX_SMART_ROWS:,} Accounts we compare exact values only (no cleaning)."
             + (" This org was compared exactly." if total > MAX_SMART_ROWS else " Not used here.")),
            ("Records listed", f"Every Account in a duplicate {'name' if use_name else 'website'} group, including the one you'd keep, "
             f"sorted by {field} so copies sit together (up to 200 Accounts)."),
        ],
    )

    def show(g: list[dict]) -> str:
        spellings = sorted({str(r.get(field)) for r in g if r.get(field)})
        return " / ".join(f"“{s}”" for s in spellings[:3]) + f" ({len(g)})"

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
    label = _label(ctx, obj)
    ctx.metric(
        metric, extra, "count", "lower-better", score,
        how=f"{_cap(label)} that share the same email address with another one, out of {total:,} {label}. We count only the extra copies beyond the first in each group.",
        rule=f"Scores 100 when there are no duplicates, falling evenly to 0 when the extra copies reach 15% of all {label}.",
        records=(obj, *base, in_list("Email", [v for v, _ in groups])) if groups else None,
        columns=["Name", "Email", "Company" if obj == "Lead" else "AccountId", "Phone", "OwnerId", "CreatedDate"],
        order="Email",
        criteria=[
            ("Records checked", f"{total:,} {label}" + (" (Leads that aren’t converted)" if obj == "Lead" else "") + _window(ctx)),
            ("Compared on", "Email address"),
            ("Email matching", "The whole address must match; Salesforce ignores upper/lower case, so “Ann@Acme.com” and “ann@acme.com” match. "
             "Blank emails are never matched."),
            ("Duplicate group", f"Two or more {label} with the same email address: {len(groups):,} groups found"
             + (f", biggest {_top(groups, 1)}" if groups else "") + "."),
            ("What's counted", f"The extra copies in each group (group size minus the one you keep): {extra:,} out of {total:,} {label}."),
            ("Records listed", f"Every {ctx.label(obj, plural=False)} in a duplicate email group, including the one you'd keep, "
             "sorted by email so copies sit together (the first 100 duplicate emails)."),
        ],
    )
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
    names = " and ".join(_label(ctx, p[0]) for p in parts) or "Contacts and open Leads"
    ctx.metric(
        "Missing Email", pct(missing, total), "%", "lower-better", rate_score(missing / total, 0.5) if total else 100,
        how=f"The share of {names} with no email address: {missing:,} out of {total:,}.",
        rule="Scores 100 when every record has an email, falling evenly to 0 when 50% are missing one.",
        records=[(obj, *conds) for obj, n, _, conds in parts if n],
        columns=["Name", "Email", "Company", "AccountId", "Phone", "OwnerId", "CreatedDate"],
        order="Name",
        criteria=[
            ("Records checked", "; ".join(f"{n:,} {_label(ctx, o)}" for o, n, _, _ in parts) + _window(ctx) if parts
             else "No Contacts or Leads with an Email field"),
            ("Fields checked", "Email"),
            ("Counts as missing", "The Email field is empty. Any address that’s filled in counts as present, even if it looks wrong."),
            ("What's counted", "; ".join(f"{m:,} of {n:,} {_label(ctx, o)} ({pct(m, n):.0f}%)" for o, n, m, _ in parts)
             + f" — {missing:,} of {total:,} in all."),
            ("Flagged when", "More than 2.5% of an object’s records have no email (its own score drops below 95)."),
            ("Records listed", "Every record with no email, per object, sorted by name."),
        ],
    )
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
    names = ", ".join(_label(ctx, p[0]) for p in parts) or "Accounts, Contacts and open Leads"
    ctx.metric(
        "Missing Phone", pct(missing, total), "%", "lower-better", rate_score(missing / total, 0.6) if total else 100,
        how=f"The share of {names} with no phone number (and no mobile number, where there is one): {missing:,} out of {total:,}.",
        rule="Scores 100 when every record has a phone number, falling evenly to 0 when 60% are missing one.",
        records=[(obj, *conds) for obj, n, _, conds in parts if n],
        columns=["Name", "Phone", "MobilePhone", "Email", "Company", "AccountId", "OwnerId", "CreatedDate"],
        order="Name",
        criteria=[
            ("Records checked", "; ".join(f"{n:,} {_label(ctx, o)}" for o, n, _, _ in parts) + _window(ctx) if parts
             else "No Accounts, Contacts or Leads with a Phone field"),
            ("Fields checked", "Phone, plus Mobile Phone on objects that have it (Contacts and Leads)"),
            ("Counts as missing", "Phone is empty and, where the object has a Mobile Phone field, that is empty too. "
             "A record with only a mobile number counts as having a phone."),
            ("What's counted", "; ".join(f"{m:,} of {n:,} {_label(ctx, o)} ({pct(m, n):.0f}%)" for o, n, m, _ in parts)
             + f" — {missing:,} of {total:,} in all."),
            ("Flagged when", "More than 3% of an object’s records have no phone number (its own score drops below 95)."),
            ("Records listed", "Every record with no phone number, per object, sorted by name."),
        ],
    )
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
    odd_records: list[tuple[str, ...]] = []  # records with an odd spelling, per object (for the measure's table)
    odd_counts: list[tuple[str, int, int]] = []  # (object, odd records, filled values), for the rule table
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
            odd_records.append((obj, *BASE_CONDS.get(obj, ()), "(" + " OR ".join(odd_conds) + ")"))
        bad_total, filled_total = bad_total + bad, filled_total + filled
        odd_counts.append((obj, bad, filled))
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
    ctx.metric(
        "Data standardization issues", bad_total, "count", "lower-better", score,
        how="Accounts, Contacts and open Leads whose country or state is spelled differently from the most common spelling of the same place "
        "(for example “USA” next to “United States”). A record with both an odd country and an odd state counts once.",
        rule="Scores 100 when every spelling is consistent, falling evenly to 0 when 25% of the filled-in country and state values use an odd spelling. "
        "If State and Country picklists are turned off, the score can’t go above 70.",
        records=odd_records,
        columns=["Name", "BillingCountry", "BillingState", "MailingCountry", "MailingState", "Country", "State"],
        order="Name",
        criteria=[
            ("Records checked", ", ".join(_label(ctx, o) for o in objs) + _window(ctx) + "; only records with a country or state filled in"
             if objs else "No Accounts, Contacts or Leads chosen"),
            ("Fields checked", "Billing Country and Billing State on Accounts, Mailing Country and Mailing State on Contacts, "
             "Country and State on Leads"),
            ("Same place", "Values are compared after ignoring upper/lower case, punctuation and extra spaces, and common names are mapped "
             "to one code: “USA”, “U.S.A.”, “United States” and “America” are all the US; “UK”, “England” and “Great Britain” are GB; "
             "US state names match their two-letter code (“California” = “CA”)."),
            ("Counts as odd", "Any spelling of a place other than its most common spelling in your org. "
             "We look at the 2,000 most common values of each field."),
            ("What's counted", "; ".join(f"{b:,} {_label(ctx, o)}" for o, b, _ in odd_counts) + f" — {bad_total:,} records in all, "
             f"against {filled_total:,} filled-in country and state values. A record with an odd country and an odd state counts once."
             if odd_counts else "Nothing to compare"),
            ("Picklists", "State and Country picklists are on, so people pick from a list." if picklists
             else "State and Country picklists are off, so the score is capped at 70."),
            ("Flagged when", "Any record on an object has an odd spelling."),
            ("Records listed", "Every record using an odd spelling of its country or state, per object, sorted by name."),
        ],
    )


# The details every object should have: phone, website and address (the object's main address — billing on Accounts,
# mailing on Contacts). Each object is checked on the ones it has (Contacts have no Website).
_ADDRESS_PREFIXES = ("", "Billing", "Mailing", "Shipping", "Other")
_KEY_PARTS = (("Phone", "Phone"), ("Website", "Website"), ("City", "City"), ("State", "State"), ("PostalCode", "Postal Code"))


def _common_key_fields(ctx: Ctx, obj: str) -> list[tuple[str, str]]:
    """(field, part) for Phone, Website, City, State and Postal Code on this object, using one address."""
    out = [(f, part) for f, part in (("Phone", "Phone"), ("Website", "Website")) if ctx.has_field(obj, f, "filterable")]
    for prefix in _ADDRESS_PREFIXES:
        address = [(f"{prefix}{f}", part) for f, part in _KEY_PARTS[2:] if ctx.has_field(obj, f"{prefix}{f}", "filterable")]
        if address:
            return out + address
    return out


def _field_label(ctx: Ctx, obj: str, name: str) -> str:
    return ctx.fields(obj).get(name, {}).get("label") or name


def missing_key_fields(ctx: Ctx) -> None:
    """Records missing any of the details every object should have: phone, website and address (city, state, postal code)."""
    parts: list[tuple[str, int, int, dict[str, int], list[str]]] = []  # (object, records, missing any, empty per field, fields)
    for obj in ctx.selected(*KEY_FIELDS, *ctx.others()):
        try:
            ctx.fields(obj)
        except Unavailable:
            continue
        keys = _common_key_fields(ctx, obj)
        total = _base_total(ctx, obj) if keys else 0
        if not total:
            continue
        names = [f for f, _ in keys]
        base = BASE_CONDS.get(obj, ())
        filled_by = ctx.filled_counts(obj, names, *base)
        any_missing = "(" + " OR ".join(f"{f} = null" for f in names) + ")"
        parts.append((obj, total, ctx.count(obj, *base, any_missing), {f: total - filled_by.get(f, total) for f in names}, names))
    if not parts:
        return  # e.g. only Opportunities chosen: none of these fields to check
    total, missing = sum(p[1] for p in parts), sum(p[2] for p in parts)
    label_of = {f"{prefix}{f}": part for prefix in _ADDRESS_PREFIXES for f, part in _KEY_PARTS}

    def per_field(obj: str, empty: dict[str, int], n: int) -> str:
        return ", ".join(f"{label_of.get(f, f)} {e:,} ({pct(e, n):.0f}%)" for f, e in empty.items())

    ctx.metric(
        "Missing Key Fields", pct(missing, total), "%", "lower-better", None,
        how=f"The share of {', '.join(_label(ctx, o) for o, *_ in parts) or 'records'} missing a phone number, website or address "
        f"(city, state or postal code): {missing:,} out of {total:,}.",
        rule="Shown for information only; it doesn’t change the area score.",
        records=[(o, *BASE_CONDS.get(o, ()), "(" + " OR ".join(f"{f} = null" for f in names) + ")") for o, n, m, _, names in parts if m],
        columns=["Name", *dict.fromkeys(f for *_, names in parts for f in names), "OwnerId", "CreatedDate"],
        order="Name",
        criteria=[
            ("Records checked", "; ".join(f"{n:,} {_label(ctx, o)}" for o, n, *_ in parts) + _window(ctx)),
            ("Fields checked", "; ".join(f"{_cap(_label(ctx, o))}: {', '.join(_field_label(ctx, o, f) for f in names)}" for o, *_, names in parts)),
            ("Counts as missing", "Any of these fields is empty. A record missing several counts once."),
            ("What's counted", "; ".join(f"{m:,} of {n:,} {_label(ctx, o)} ({pct(m, n):.0f}%) — empty: {per_field(o, e, n)}" for o, n, m, e, _ in parts)
             + f". {missing:,} of {total:,} in all."),
            ("Records listed", "Every record missing at least one of these fields, per object, sorted by name."),
        ],
    )


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


def accounts_without_contacts(ctx: Ctx) -> None:
    ctx.selected("Account")
    total = _base_total(ctx, "Account")
    cond = "Id NOT IN (SELECT AccountId FROM Contact WHERE AccountId != null)"
    n = ctx.count("Account", cond) if total else 0
    score = rate_score(n / total, 0.5) if total else 100
    ctx.metric(
        "Accounts without Contacts", n, "count", "lower-better", score,
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
    "area-1": [duplicate_accounts, duplicate_contacts, duplicate_leads, duplicate_other_objects, missing_email, missing_phone, missing_key_fields, standardization],
    "area-2": [field_completeness, redundant_fields, accounts_without_contacts, scorecard],
}

STEP_LABELS = {
    duplicate_accounts: "Looking for duplicate Accounts",
    duplicate_contacts: "Looking for duplicate Contacts",
    duplicate_leads: "Looking for duplicate Leads",
    duplicate_other_objects: "Looking for duplicates in your other objects",
    missing_email: "Checking for missing emails",
    missing_phone: "Checking for missing phone numbers",
    missing_key_fields: "Checking phone, website and address fields",
    standardization: "Checking country and state values",
    field_completeness: "Measuring how complete key fields are",
    redundant_fields: "Looking for unused custom fields",
    accounts_without_contacts: "Finding Accounts with no Contacts",
    scorecard: "Building the data quality scorecard",
}
