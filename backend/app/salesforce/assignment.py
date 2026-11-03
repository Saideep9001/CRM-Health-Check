"""The active Lead Assignment Rule's entries (Metadata API, read-only), and which Leads match none of them.

Salesforce tries a rule's entries in order and assigns a Lead by the first one whose criteria it meets; a Lead that meets
none goes to the default lead owner (Setup → Lead Settings). Criteria are checked here the way Salesforce checks them:
each item's comma-separated values are alternatives, items are all required unless the entry has a filter logic
("1 AND (2 OR 3)"). An entry we can't check (a formula, a related-record field, a date) counts as possibly matching,
so no Lead is flagged on a guess.
"""
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

NS = {"m": "http://soap.sforce.com/2006/04/metadata"}


@dataclass
class Item:
    field: str  # the Lead field, e.g. LeadSource
    operation: str
    value: str


@dataclass
class Entry:
    order: int
    assigned_to: str | None  # a username, or a queue's API name
    assigned_type: str | None  # User or Queue
    items: list[Item] = field(default_factory=list)
    logic: str | None = None
    checkable: bool = True  # False: a formula or a criterion we can't check here


@dataclass
class Rule:
    name: str
    entries: list[Entry]


def _text(el: ET.Element | None, tag: str) -> str | None:
    found = el.find(f"m:{tag}", NS) if el is not None else None
    return found.text.strip() if found is not None and found.text else None


def active_rule(xml: str) -> Rule | None:
    """The active Lead Assignment Rule from a readMetadata("AssignmentRules", ["Lead"]) response, or None."""
    root = ET.fromstring(xml)
    for rule in root.iter(f"{{{NS['m']}}}assignmentRule"):
        if (_text(rule, "active") or "").lower() != "true":
            continue
        entries = []
        for n, e in enumerate(rule.findall("m:ruleEntry", NS), 1):
            items = [Item((_text(c, "field") or "").removeprefix("Lead."), _text(c, "operation") or "", _text(c, "value") or "")
                     for c in e.findall("m:criteriaItems", NS)]
            checkable = not _text(e, "formula") and all(i.field and "." not in i.field for i in items)
            entries.append(Entry(n, _text(e, "assignedTo"), _text(e, "assignedToType"), items, _text(e, "booleanFilter"), checkable))
        return Rule(_text(rule, "fullName") or "Lead Assignment Rule", entries)
    return None


_NUMBER = {"double", "currency", "percent", "int", "long"}
_TEXT = {"string", "email", "phone", "url", "textarea", "picklist", "multipicklist", "combobox", "id", "reference"}


def _item_met(item: Item, value: object, ftype: str) -> bool | None:
    """Does one criterion hold for this value? None = can't tell here (e.g. a date)."""
    op = item.operation
    options = [v.strip() for v in item.value.split(",")] if item.value else [""]
    if ftype == "boolean":
        want = [o.lower() == "true" for o in options]
        got = bool(value)
        return got in want if op == "equals" else got not in want if op == "notEqual" else None
    if ftype in _NUMBER:
        if value is None:
            return op == "equals" and "" in options or op == "notEqual" and "" not in options
        try:
            nums, v = [float(o) for o in options if o], float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        tests = {"equals": lambda x: v == x, "notEqual": lambda x: v != x, "lessThan": lambda x: v < x, "greaterThan": lambda x: v > x,
                 "lessOrEqual": lambda x: v <= x, "greaterOrEqual": lambda x: v >= x}
        if op not in tests:
            return None
        return all(tests[op](x) for x in nums) if op == "notEqual" else any(tests[op](x) for x in nums)
    if ftype not in _TEXT:
        return None  # dates and the like: Salesforce compares these in ways we don't repeat here
    v = "" if value is None else str(value).strip().lower()
    opts = [o.lower() for o in options]
    parts = [p.strip().lower() for p in v.split(";")] if ftype == "multipicklist" else [v]
    checks = {
        "equals": lambda: v in opts,
        "notEqual": lambda: v not in opts,
        "contains": lambda: any(o and o in v for o in opts),
        "notContain": lambda: not any(o and o in v for o in opts),
        "startsWith": lambda: any(o and v.startswith(o) for o in opts),
        "includes": lambda: any(o in parts for o in opts),
        "excludes": lambda: not any(o in parts for o in opts),
    }
    return checks[op]() if op in checks else None


def _logic(expr: str, results: list[bool | None]) -> bool | None:
    """Evaluate filter logic like "1 AND (2 OR 3)" (None if it uses a criterion we can't check, or is malformed)."""
    tokens = re.findall(r"\d+|AND|OR|NOT|\(|\)", expr.upper())
    if "".join(tokens) != re.sub(r"\s+", "", expr.upper()):
        return None
    out = []
    for t in tokens:
        if t.isdigit():
            i = int(t) - 1
            if not 0 <= i < len(results) or results[i] is None:
                return None
            out.append(str(bool(results[i])))
        else:
            out.append(t.lower() if t in ("AND", "OR", "NOT") else t)
    try:
        return bool(eval(" ".join(out), {"__builtins__": {}}, {}))  # only True/False, and/or/not and brackets reach here
    except SyntaxError:
        return None


def matches(entry: Entry, lead: dict, types: dict[str, str]) -> bool | None:
    """Does the Lead meet this entry's criteria? True for an entry with no criteria; None when it can't be told."""
    if not entry.checkable:
        return None
    if not entry.items:
        return True
    results = [_item_met(i, lead.get(i.field), types.get(i.field, "")) if i.field in types else None for i in entry.items]
    if entry.logic:
        return _logic(entry.logic, results)
    if any(r is False for r in results):
        return False
    return None if any(r is None for r in results) else True


def fields_used(rule: Rule) -> list[str]:
    return sorted({i.field for e in rule.entries for i in e.items if i.field and "." not in i.field})


GAP_COLUMN = {"name": "AssignmentGapReason", "label": "Assignment Gap Reason", "type": "string"}


def add_gap_reason(columns: list[dict], records: list[dict], reasons: dict[str, str]) -> list[dict]:
    """Adds each listed Lead's saved reason (in place) and returns the columns with it after the Created Date, the owner
    named "Current Owner"."""
    for r in records:
        r["values"][GAP_COLUMN["name"]] = reasons.get(r.get("id") or "")
    out: list[dict] = []
    for c in columns:
        out.append({**c, "label": "Current Owner"} if c["name"] == "OwnerId" else c)
        if c["name"] == "CreatedDate":
            out.append(GAP_COLUMN)
    return out if GAP_COLUMN in out else out + [GAP_COLUMN]
