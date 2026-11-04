"""Lead Assignment Rules and their entries (Metadata API, read-only), and how open Leads compare with them.

Salesforce tries a rule's entries in order and assigns a Lead by the first one whose criteria it meets; a Lead that meets
none goes to the default lead owner (Setup → Lead Settings). Only one rule is active at a time. Criteria are checked here
the way Salesforce checks them: each item's comma-separated values are alternatives, items are all required unless the
entry has a filter logic ("1 AND (2 OR 3)"). An entry we can't check (a formula, a related-record field, a date) counts as
possibly matching, so no Lead is flagged on a guess.
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
    formula: str | None = None


@dataclass
class Rule:
    name: str
    entries: list[Entry]
    active: bool = True


def _text(el: ET.Element | None, tag: str) -> str | None:
    found = el.find(f"m:{tag}", NS) if el is not None else None
    return found.text.strip() if found is not None and found.text else None


def all_rules(xml: str) -> list[Rule]:
    """Every Lead Assignment Rule (active or not) from a readMetadata("AssignmentRules", ["Lead"]) response."""
    out = []
    for rule in ET.fromstring(xml).iter(f"{{{NS['m']}}}assignmentRule"):
        entries = []
        for n, e in enumerate(rule.findall("m:ruleEntry", NS), 1):
            items = [Item((_text(c, "field") or "").removeprefix("Lead."), _text(c, "operation") or "", _text(c, "value") or "")
                     for c in e.findall("m:criteriaItems", NS)]
            formula = _text(e, "formula")
            checkable = not formula and all(i.field and "." not in i.field for i in items)
            entries.append(Entry(n, _text(e, "assignedTo"), _text(e, "assignedToType"), items, _text(e, "booleanFilter"), checkable, formula))
        out.append(Rule(_text(rule, "fullName") or "Lead Assignment Rule", entries, (_text(rule, "active") or "").lower() == "true"))
    return out


def active_rule(xml: str) -> Rule | None:
    """The active Lead Assignment Rule, or None."""
    return next((r for r in all_rules(xml) if r.active), None)


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


def _results(entry: Entry, lead: dict, types: dict[str, str]) -> list[bool | None]:
    return [_item_met(i, lead.get(i.field), types.get(i.field, "")) if i.field in types else None for i in entry.items]


def matches(entry: Entry, lead: dict, types: dict[str, str]) -> bool | None:
    """Does the Lead meet this entry's criteria? True for an entry with no criteria; None when it can't be told."""
    if not entry.checkable:
        return None
    if not entry.items:
        return True
    results = _results(entry, lead, types)
    if entry.logic:
        return _logic(entry.logic, results)
    if any(r is False for r in results):
        return False
    return None if any(r is None for r in results) else True


def first_match(rule: Rule, lead: dict, types: dict[str, str]) -> Entry | None:
    """The entry that would assign this Lead (the first it surely meets), if any."""
    return next((e for e in rule.entries if matches(e, lead, types) is True), None)


def fields_used(*rules: Rule) -> list[str]:
    return sorted({i.field for r in rules for e in r.entries for i in e.items if i.field and "." not in i.field})


# ---------------- in words, for the cards

_OPS = {"equals": "equals", "notEqual": "doesn’t equal", "contains": "contains", "notContain": "doesn’t contain",
        "startsWith": "starts with", "includes": "includes", "excludes": "excludes", "lessThan": "is less than",
        "greaterThan": "is greater than", "lessOrEqual": "is at most", "greaterOrEqual": "is at least", "within": "is within"}


def _values(item: Item) -> str:
    opts = [v.strip() for v in item.value.split(",") if v.strip()] if item.value else []
    return " or ".join(f"“{v}”" for v in opts) if opts else "blank"


def criterion(item: Item, labels: dict[str, str]) -> str:
    return f"{labels.get(item.field, item.field)} {_OPS.get(item.operation, item.operation)} {_values(item)}"


def target(entry: Entry) -> str:
    who = entry.assigned_to or "nobody"
    return f"queue {who}" if (entry.assigned_type or "").lower() == "queue" else who


def describe(entry: Entry, labels: dict[str, str]) -> str:
    """"Entry 2: Lead Source equals “Web” or “Phone” → queue Web_Queue"."""
    if entry.formula:
        crit = f"formula {entry.formula}"
    elif not entry.items:
        crit = "no criteria (every Lead)"
    else:
        crit = " AND ".join(criterion(i, labels) for i in entry.items)
        if entry.logic:
            crit = f"{crit} (filter logic {entry.logic})"
    return f"Entry {entry.order}: {crit} → {target(entry)}"


def _shown(value: object) -> str:
    return "blank" if value is None or str(value).strip() == "" else f"“{value}”"


def miss(entry: Entry, lead: dict, types: dict[str, str], labels: dict[str, str]) -> str:
    """Why this Lead doesn't meet the entry, in words (call only when `matches` is False)."""
    results = _results(entry, lead, types)
    if entry.logic:
        return f"Entry {entry.order}: its filter logic {entry.logic} isn’t met"
    item = next((i for i, r in zip(entry.items, results) if r is False), entry.items[0])
    return f"Entry {entry.order} needs {criterion(item, labels)} (it’s {_shown(lead.get(item.field))})"


# ---------------- extra columns on the cards' record tables

GAP_COLUMN = {"name": "AssignmentGapReason", "label": "Assignment Gap Reason", "type": "string"}
MATCH_COLUMN = {"name": "PotentialMatch", "label": "Potential Match (inactive rule)", "type": "string"}


def add_reason(columns: list[dict], records: list[dict], reasons: dict[str, str], default: str | None = None,
               column: dict = GAP_COLUMN) -> list[dict]:
    """Adds each listed Lead's saved reason (or `default`, the same for every Lead) in place, and returns the columns with it
    after the Created Date, the owner named "Current Owner"."""
    for r in records:
        r["values"][column["name"]] = reasons.get(r.get("id") or "") or default
    out: list[dict] = []
    for c in columns:
        out.append({**c, "label": "Current Owner"} if c["name"] == "OwnerId" else c)
        if c["name"] == "CreatedDate":
            out.append(column)
    return out if column in out else out + [column]


def add_gap_reason(columns: list[dict], records: list[dict], reasons: dict[str, str], default: str | None = None) -> list[dict]:
    return add_reason(columns, records, reasons, default, GAP_COLUMN)
