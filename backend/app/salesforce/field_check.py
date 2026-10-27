"""Check chosen fields of an object: empty values, duplicates and inconsistent spellings, field by field (read-only).

Records are read once (up to duplicates.MAX_SCAN) and every chosen field is checked on that same set:
- Empty: the field has no value.
- Duplicates: records sharing the same value. Names, emails, phones, websites and streets use the duplicate finder's
  fuzzy matching (typos, formats); other fields must be the same after ignoring case and punctuation. Picklist
  choices, dates, numbers and places (city, state, country, ZIP) are shared by design, so they aren't checked for
  duplicates on their own — only together with other fields.
- Standardization: the same value written different ways ("USA" / "United States", "acme" / "ACME"); every record not
  using the most common spelling counts. Text-like fields only.
With several fields, records that are duplicates on all of them together are found too.
"""
import re
from collections import Counter, defaultdict

from . import duplicates, empty_fields, explorer
from .client import SalesforceClient

MAX_FIELDS = 10
GROUPS_SHOWN = 300  # duplicate groups returned per field (counts are always exact)
RECORDS_PER_GROUP = 20
ODD_SHOWN = 500  # records with an odd spelling returned per field
VARIANTS_SHOWN = 100

_FUZZY = {"company", "last", "email", "phone", "website", "street"}  # compared with the duplicate finder's matchers
_SAME_ACCOUNT = {"CloseDate", "Amount", "StageName"}  # Opportunity fields compared within one Account
_CHECKED_VALUES = {"currency", "date"}  # amounts (zero or negative) and dates (past close date on an open deal…) are checked too
_TEXT = {"string", "email", "phone", "url", "textarea", "picklist", "combobox"}
_PLACE = re.compile(r"(City|State|Country|PostalCode|StateCode|CountryCode)$")
_NO_DUPLICATES = {"picklist", "multipicklist", "combobox", "boolean", "date", "datetime", "time", "double", "currency", "percent", "int", "long"}


def _spelling_key(field: str, ftype: str, value: object) -> str:
    """Values that mean the same thing get the same key (country/state names map to one code)."""
    from ..engine.data_quality import _COUNTRY, _STATES, _norm  # engine imports salesforce, so import here
    if field.endswith("Country"):
        return _norm(value, _COUNTRY)
    if field.endswith("State"):
        return _norm(value, _STATES)
    if ftype == "phone":
        return re.sub(r"\D", "", str(value))[-10:]
    if ftype == "url":
        return duplicates.norm_website(value)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9@]+", " ", str(value).lower())).strip()


def _exact_groups(rows: list[dict], field: str, ftype: str) -> list[list[int]]:
    """Records sharing a value once case and punctuation are ignored."""
    buckets: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        v = duplicates._value(r, field)
        if v not in (None, ""):
            k = _spelling_key(field, ftype, v)
            if k:
                buckets[k].append(i)
    return sorted((b for b in buckets.values() if len(b) > 1), key=len, reverse=True)


def check_fields(sf: SalesforceClient, obj: str, fields: list[str]) -> dict:
    options = {f["name"]: f for f in empty_fields.empty_options(sf, obj)}
    chosen = [f for f in dict.fromkeys(fields) if f in options]
    if not chosen:
        raise ValueError("Choose at least one field to check.")
    if len(chosen) > MAX_FIELDS:
        raise ValueError(f"Choose up to {MAX_FIELDS} fields.")

    desc = explorer._describe(sf, obj)
    described = explorer._fields(desc)
    name_field = next((f["name"] for f in desc.get("fields", []) if f.get("nameField")), None)
    has = lambda f: f in described or (f == "Owner.Name" and "OwnerId" in described) or (f == "Account.Name" and "AccountId" in described)  # noqa: E731
    context = [f for f in duplicates.CONTEXT.get(obj, duplicates.DEFAULT_CONTEXT) if has(f)]
    open_flag = ["IsClosed"] if "CloseDate" in chosen and "IsClosed" in described else []  # "an open deal whose close date has passed"
    same_account = [f for f in chosen if obj == "Opportunity" and f in _SAME_ACCOUNT] if "AccountId" in described else []
    paths = list(dict.fromkeys(([name_field] if name_field else []) + chosen + context + open_flag + (["AccountId"] if same_account else [])))
    rows, truncated = duplicates._fetch(sf, obj, paths)
    prefetched = (rows, truncated)
    matchable = {f["name"]: f for f in duplicates.matchable_fields(sf, obj)}

    def label(f: str) -> str:
        return options.get(f, {}).get("label") or {"Owner.Name": "Owner"}.get(f) or described.get(f, {}).get("label") or f

    def record(i: int, cols: list[str]) -> dict:
        return {"id": rows[i].get("Id"), "values": {c: duplicates._value(rows[i], c) for c in cols}}

    def shown(field: str) -> list[str]:
        return list(dict.fromkeys(([name_field] if name_field else []) + [field] + context))

    def trim(result: dict) -> dict:
        result["groups"] = [{**g, "records": g["records"][:RECORDS_PER_GROUP]} for g in result["groups"][:GROUPS_SHOWN]]
        return result

    out_fields = []
    odd_any: set[int] = set()  # records with an odd spelling in at least one checked text field
    valued_any: set[int] = set()  # records with a value in at least one checked text field
    for f in chosen:
        ftype = options[f]["type"]
        cols = shown(f)
        values = [duplicates._value(r, f) for r in rows]
        empty = sum(1 for v in values if v in (None, ""))

        # duplicates on this field alone
        dup = None
        if f in same_account:  # Opportunities: the same Close Date, Amount or Stage on the same Account (as the health check's chart)
            buckets: dict[tuple, list[int]] = defaultdict(list)
            for i, r in enumerate(rows):
                v = duplicates._value(r, f)
                if r.get("AccountId") and v not in (None, ""):
                    buckets[(r["AccountId"], str(v))].append(i)
            found = sorted((b for b in buckets.values() if len(b) > 1), key=len, reverse=True)
            acc_cols = list(dict.fromkeys([*cols[:1], "AccountId", f, *cols[1:]]))
            dup = {
                "object": obj, "standard": False, "rule_name": None, "rules": [[label("AccountId"), label(f)]],
                "methods": [{"field": label(f), "method": "Same value on the same Account"}],
                "columns": [{"name": c, "label": label(c)} for c in acc_cols],
                "scanned": len(rows), "truncated": truncated,
                "total_groups": len(found), "extra_copies": sum(len(g) - 1 for g in found),
                "groups": [{"size": len(g), "matched_on": f"{label(f)} on the same Account", "records": [record(i, acc_cols) for i in g[:RECORDS_PER_GROUP]]}
                           for g in found[:GROUPS_SHOWN]],
                "record_url_prefix": f"{sf.base}/",
            }
        elif ftype not in _NO_DUPLICATES and not _PLACE.search(f) and f in matchable:
            kind = matchable[f]["kind"]
            if kind in _FUZZY and kind != "phone":
                dup = trim(duplicates.find_duplicates(sf, obj, [f], prefetched=prefetched))
                method = duplicates.KINDS[kind][0]
            else:  # phones: the same number (a close number is a different phone), as the health check's chart counts them
                found = _exact_groups(rows, f, ftype)
                method = "Same number (ignores spaces, brackets and dashes)" if ftype == "phone" or kind == "phone" else "Same value (ignores case and punctuation)"
                dup = {
                    "object": obj, "standard": False, "rule_name": None, "rules": [[label(f)]],
                    "methods": [{"field": label(f), "method": method}],
                    "columns": [{"name": c, "label": label(c)} for c in cols],
                    "scanned": len(rows), "truncated": truncated,
                    "total_groups": len(found), "extra_copies": sum(len(g) - 1 for g in found),
                    "groups": [{"size": len(g), "matched_on": label(f), "records": [record(i, cols) for i in g[:RECORDS_PER_GROUP]]}
                               for g in found[:GROUPS_SHOWN]],
                    "record_url_prefix": f"{sf.base}/",
                }

        # standardization: the health check's rules (engine/standards.py), with why each value is odd
        std = None
        if ftype in _TEXT or ftype in _CHECKED_VALUES:
            from ..engine import standards
            from ..engine.data_quality import _std_kind  # engine imports salesforce, so import here
            items = [(str(i), v) for i, v in enumerate(values) if v not in (None, "")]
            open_ids = {str(i) for i, r in enumerate(rows) if open_flag and r.get("IsClosed") is False}
            why = {int(i): r for i, r in standards.odd_values(_std_kind(f, options[f], obj), items, open_ids).items()}
            odd = sorted(why, key=lambda i: str(values[i]).lower())
            odd_any.update(odd)
            valued_any.update(int(i) for i, _ in items)
            std = {
                "odd_records": len(odd),
                "values_with_variants": len({str(values[i]) for i in odd}),
                "variants": [],
                "reasons": [{"reason": r, "count": n} for r, n in Counter(why.values()).most_common()],
                "rule": standards.RULES.get(_std_kind(f, options[f], obj), ""),
                "columns": [{"name": c, "label": label(c)} for c in cols],
                "records": [{**record(i, cols), "note": why[i]} for i in odd[:ODD_SHOWN]],
            }

        out_fields.append({
            "name": f, "label": label(f), "type": ftype,
            "filled": len(rows) - empty, "empty": empty,
            "duplicates": dup, "standardization": std,
        })

    combined = None
    together = [f for f in chosen if f in matchable][: 6]
    if len(chosen) > 1 and len(together) > 1:
        combined = trim(duplicates.find_duplicates(sf, obj, together, prefetched=prefetched))

    any_empty = sum(1 for r in rows if any(duplicates._value(r, f) in (None, "") for f in chosen))
    return {
        "object": obj,
        "scanned": len(rows),
        "truncated": truncated,
        "any_empty": any_empty,  # records missing at least one chosen field (each counted once)
        "any_odd": len(odd_any),  # records with an odd spelling in at least one checked text field
        "any_value": len(valued_any),  # records with a value in at least one checked text field
        "fields": out_fields,
        "combined": combined,
        "record_url_prefix": f"{sf.base}/",
    }
