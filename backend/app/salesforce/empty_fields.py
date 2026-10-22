"""Find records whose chosen fields are empty (read-only).

Fields are checked against the object's describe, so only real, filterable fields reach the query; a checkbox can never
be empty, so those are left out. In Salesforce, `= null` also matches empty text.
"""
from . import explorer
from .client import SalesforceClient

MAX_FIELDS = 10
_NEVER_EMPTY = {"boolean", "id", "base64", "address", "location", "complexvalue", "anyType"}


def empty_options(sf: SalesforceClient, obj: str) -> list[dict]:
    """Fields that can be checked for being empty."""
    desc = explorer._describe(sf, obj)
    return [
        {"name": f["name"], "label": f.get("label") or f["name"], "type": f.get("type", "")}
        for f in desc.get("fields", [])
        if f.get("filterable") and f.get("type") not in _NEVER_EMPTY
    ]


def where_empty(sf: SalesforceClient, obj: str, fields: list[str], match: str) -> tuple[str, list[str]]:
    allowed = {f["name"] for f in empty_options(sf, obj)}
    chosen = [f for f in dict.fromkeys(fields) if f in allowed]
    if not chosen:
        raise ValueError("Choose at least one field to check.")
    if len(chosen) > MAX_FIELDS:
        raise ValueError(f"Choose up to {MAX_FIELDS} fields.")
    joiner = " AND " if match == "all" else " OR "
    return "(" + joiner.join(f"{f} = null" for f in chosen) + ")", chosen


def find_empty(sf: SalesforceClient, obj: str, fields: list[str], match: str = "any", cursor: str | None = None) -> dict:
    where, chosen = where_empty(sf, obj, fields, match)
    page = explorer.records_matching(sf, obj, where, cursor, columns=chosen, order=explorer._name_field(explorer._describe(sf, obj)))
    total = None if cursor else sf.query(f"SELECT COUNT() FROM {obj}").get("totalSize")
    labels = {f["name"]: f["label"] for f in empty_options(sf, obj)}
    return {**page, "object_total": total, "fields": chosen, "field_labels": [labels.get(f, f) for f in chosen], "match": match}
