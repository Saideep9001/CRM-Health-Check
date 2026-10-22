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
    paths = list(dict.fromkeys(([name_field] if name_field else []) + chosen + context))
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
    for f in chosen:
        ftype = options[f]["type"]
        cols = shown(f)
        values = [duplicates._value(r, f) for r in rows]
        empty = sum(1 for v in values if v in (None, ""))

        # duplicates on this field alone
        dup = None
        if ftype not in _NO_DUPLICATES and not _PLACE.search(f) and f in matchable:
            kind = matchable[f]["kind"]
            if kind in _FUZZY:
                dup = trim(duplicates.find_duplicates(sf, obj, [f], prefetched=prefetched))
                method = duplicates.KINDS[kind][0]
            else:
                found = _exact_groups(rows, f, ftype)
                method = "Same value (ignores case and punctuation)"
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

        # standardization: the same value written different ways
        std = None
        if ftype in _TEXT:
            buckets: dict[str, Counter] = defaultdict(Counter)
            where: dict[tuple[str, str], list[int]] = defaultdict(list)
            for i, v in enumerate(values):
                if v in (None, ""):
                    continue
                k = _spelling_key(f, ftype, v)
                if k:
                    buckets[k][str(v)] += 1
                    where[(k, str(v))].append(i)
            variants, odd = [], []
            for k, spellings in buckets.items():
                if len(spellings) > 1:
                    ranked = spellings.most_common()
                    variants.append({"usual": ranked[0][0], "spellings": [{"value": s, "count": c} for s, c in ranked],
                                     "odd_records": sum(c for _, c in ranked[1:])})
                    for s, _ in ranked[1:]:
                        odd += where[(k, s)]
            variants.sort(key=lambda x: -x["odd_records"])
            std = {
                "odd_records": len(odd),
                "values_with_variants": len(variants),
                "variants": variants[:VARIANTS_SHOWN],
                "columns": [{"name": c, "label": label(c)} for c in cols],
                "records": [record(i, cols) for i in sorted(odd, key=lambda i: str(values[i]).lower())[:ODD_SHOWN]],
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

    return {
        "object": obj,
        "scanned": len(rows),
        "truncated": truncated,
        "fields": out_fields,
        "combined": combined,
        "record_url_prefix": f"{sf.base}/",
    }
