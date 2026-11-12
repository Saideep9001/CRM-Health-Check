"""Required field gaps: every active rule that makes a field required or stops a save on Accounts, Contacts, Leads and
Opportunities, and the existing records that don't meet them.

Rules read (only active or currently applied ones):
- Required on the field: fields Salesforce itself requires (standard required fields, and custom fields marked Required).
- Page layouts: fields marked Required on a layout, applied to the records of the record types that layout is assigned to.
- Validation rules: each active rule's error condition formula, worked out for every record (see sf_formula).
- Apex triggers: active before insert / before update triggers (and the handler classes they call) that stop a save with
  addError when a field is empty. Read from the code, so these are a best guess.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import quote, unquote

from ..salesforce import assignment
from ..salesforce.errors import SalesforceAuthExpired, SalesforceError
from .core import Ctx, Unavailable
from .sf_formula import Formula, Unsupported, get_path

MASTER_RT = "012000000000000AAA"  # the master record type (records with no record type)
MAX_ROWS = 500_000  # records read per object
SHOWN = 2000  # failing records listed per object (picked by Id)
_NS = assignment.NS


@dataclass
class Rule:
    kind: str  # "field" | "layout" | "validation" | "trigger"
    name: str  # what people see: the layout, rule or trigger name
    fields: list[str]  # the fields it marks (red in the records table)
    message: str = ""  # validation rule error message
    formula: Formula | None = None
    record_types: set[str | None] | None = None  # layouts: the record types it applies to (None = every record)
    broken: int = 0

    def describe(self) -> str:
        return {"field": "Required on the field", "layout": f"Page layout “{self.name}”", "validation": f"Validation rule “{self.name}”",
                "trigger": f"Apex trigger “{self.name}”"}[self.kind]


@dataclass
class ObjectCheck:
    obj: str
    rules: list[Rule] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # rules that couldn't be checked, with why
    notes_read: list[str] = field(default_factory=list)  # setup that couldn't be read
    checked: int = 0
    capped: bool = False
    bad_ids: list[str] = field(default_factory=list)
    notes: dict[str, dict[str, str]] = field(default_factory=dict)  # record id -> field -> why (first SHOWN records)
    # the same, one rule kind at a time (for the rule filter above the table), and each record's broken rules by name
    kind_notes: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    broken: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # record id -> [(kind, "Field: rule")]
    # every rule found, active or not, for the validation rules card's table (see audit_row)
    audit: list[dict] = field(default_factory=list)
    # every page layout, for Layout usability concerns: [{"id", "name", "fields"}]; None = couldn't be read
    layouts: list[dict] | None = None
    # its assignments: [(layout id 15, profile id 15, record type id 15 or None)]; None = couldn't be read
    assignments: list[tuple[str, str, str | None]] | None = None


AREA = {"field": "System Rule", "layout": "Page Layout", "validation": "Validation Rule", "trigger": "Trigger"}
_VAGUE = re.compile(r"^(error|invalid|not allowed|required|please fix( this)?|check (the )?fields?|(an )?error (has )?occurred|"
                    r"something went wrong|validation (error|failed)|invalid (data|value|input)|fix (this|errors?))[.!]*$", re.I)


def message_issue(message: str | None) -> str | None:
    """Why an error message doesn't help the person who sees it, or None when it explains the issue."""
    m = (message or "").strip()
    if not m:
        return "Empty error message"
    if re.fullmatch(r"(error|invalid)[.!]*", m, re.I):
        return f"Only “{m}”"
    if _VAGUE.match(m):
        return "Generic: doesn’t say what to fix"
    if len(m) < 20:
        return "Too short to explain the issue"
    return None


def audit_row(obj: str, kind: str, name: str, description: str, active: bool, message: str | None, assessed: bool,
              url: str | None = None) -> dict:
    """One rule in the validation rules card's table. `assessed` = the error message is the rule's own (validation rules, and
    trigger messages found in the code), so its quality is judged; otherwise it's Salesforce's standard message (N/A)."""
    return {"object": obj, "area": AREA[kind], "name": name, "description": description, "active": active,
            "message": message if assessed else None, "issue": message_issue(message) if assessed else None, "assessed": assessed, "url": url}


def _read(ctx: Ctx, kind: str, names: list[str]) -> list[ET.Element]:
    """Metadata API records of one type (10 names per call); raises Unavailable when it can't be read."""
    read = getattr(ctx.sf, "read_metadata", None)
    if read is None:
        raise Unavailable("The Metadata API isn’t available.")
    out: list[ET.Element] = []
    try:
        for i in range(0, len(names), 10):
            xml = read(kind, [quote(n, safe=" -_.") for n in names[i:i + 10]])
            out += list(ET.fromstring(xml).iter(f"{{{_NS['m']}}}records"))
    except SalesforceAuthExpired:
        raise
    except (SalesforceError, ET.ParseError) as exc:
        raise Unavailable(str(exc)) from None
    return out


def _rt(value: object) -> str | None:
    v = str(value or "")
    return None if not v or v.startswith(MASTER_RT[:15]) else v[:15]


def field_rules(ctx: Ctx, obj: str, fields: dict[str, dict], check: ObjectCheck | None = None) -> list[Rule]:
    """Fields Salesforce requires on every record: not nillable, set by people (not defaulted or calculated)."""
    names = [n for n, f in fields.items()
             if not f.get("nillable", True) and f.get("createable", True) and not f.get("defaultedOnCreate") and not f.get("calculated")
             and f.get("type") not in ("boolean", "id")]
    if check is not None:
        for n in names:
            custom = bool(fields[n].get("custom"))
            check.audit.append(audit_row(
                obj, "field", n, f"{fields[n].get('label') or n} is required on every {obj} "
                + ("(custom field marked Required)" if custom else "(standard field Salesforce always requires)"),
                True, None, False, ctx.setup_url(f"/lightning/setup/ObjectManager/{obj}/FieldsAndRelationships/{n}/view")))
    return [Rule("field", ("Custom required field" if fields[n].get("custom") else "Standard required field") + f" {fields[n].get('label') or n}", [n])
            for n in names]


def layout_rules(ctx: Ctx, obj: str, fields: dict[str, dict], check: ObjectCheck) -> list[Rule]:
    """Fields marked Required on each page layout, for the record types the layout is assigned to."""
    try:
        rows = ctx.setup(f"SELECT Id, Name, NamespacePrefix FROM Layout WHERE TableEnumOrId = '{obj}'")
    except Unavailable:
        check.notes_read.append("page layouts")
        return []
    full = {f"{obj}-" + (f"{r['NamespacePrefix']}__" if r.get("NamespacePrefix") else "") + r["Name"]: r for r in rows if r.get("Name")}
    if not full:
        return []
    try:
        recs = _read(ctx, "Layout", sorted(full))
    except Unavailable:
        check.notes_read.append("page layouts")
        return []
    # which record types each layout is used for (any profile); unreadable = every record
    used: dict[str, set[str | None]] | None = {}
    try:
        check.assignments = []
        for a in ctx.setup(f"SELECT LayoutId, ProfileId, RecordTypeId FROM ProfileLayout WHERE TableEnumOrId = '{obj}'"):
            used.setdefault(str(a.get("LayoutId") or "")[:15], set()).add(_rt(a.get("RecordTypeId")))
            check.assignments.append((str(a.get("LayoutId") or "")[:15], str(a.get("ProfileId") or "")[:15], _rt(a.get("RecordTypeId"))))
    except Unavailable:
        used = None
        check.assignments = None
    has_rt = "RecordTypeId" in fields
    out: list[Rule] = []
    check.layouts = []
    for rec in recs:
        name = unquote(rec.findtext("m:fullName", "", _NS))
        placed = {f for f in (i.findtext("m:field", "", _NS) for i in rec.iter(f"{{{_NS['m']}}}layoutItems")) if f}
        check.layouts.append({"id": str((full.get(name) or {}).get("Id") or ""), "name": name.removeprefix(f"{obj}-"), "fields": len(placed)})
        req = []
        for item in rec.iter(f"{{{_NS['m']}}}layoutItems"):
            if (item.findtext("m:behavior", "", _NS) or "") != "Required":
                continue
            f = item.findtext("m:field", "", _NS) or ""
            if f == "Name" and obj in ("Contact", "Lead"):
                f = "LastName"  # the Name compound field: Last Name is the required part
            meta = fields.get(f)
            if meta and meta.get("nillable", True) and meta.get("updateable", True) and f not in req:
                req.append(f)  # not already required everywhere
        if not req:
            continue
        row = full.get(name) or {}
        short = name.removeprefix(f"{obj}-")
        lid = str(row.get("Id") or "")[:15]
        assigned = used is None or bool(used.get(lid))
        labels = ", ".join(fields[f].get("label") or f for f in req)
        url = ctx.setup_url(f"/lightning/setup/ObjectManager/{obj}/PageLayouts/{row['Id']}/view") if row.get("Id") else None
        check.audit.append(audit_row(obj, "layout", short, f"Requires {labels} on this layout"
                                     + ("" if assigned else " (not assigned to any profile, so it never applies)"), assigned, None, False, url))
        if not assigned:
            continue  # assigned to nobody: it never applies
        types = used.get(lid) if used is not None and has_rt else None
        out.append(Rule("layout", short, req, record_types=types))
    return out


def validation_rules(ctx: Ctx, obj: str, fields: dict[str, dict], check: ObjectCheck) -> list[Rule]:
    """Each active validation rule with its error condition formula."""
    try:
        every = ctx.setup(f"SELECT Id, ValidationName, NamespacePrefix, Active, Description, ErrorMessage FROM ValidationRule "
                          f"WHERE EntityDefinition.QualifiedApiName = '{obj}'")
    except Unavailable:
        check.notes_read.append("validation rules")
        return []
    if not every:
        return []
    allnames = {f"{obj}." + (f"{r['NamespacePrefix']}__" if r.get("NamespacePrefix") else "") + r["ValidationName"]: r for r in every}
    try:
        recs = {unquote(e.findtext("m:fullName", "", _NS)): e for e in _read(ctx, "ValidationRule", sorted(allnames))}
    except Unavailable:
        recs = None
    for full, row in allnames.items():
        e = (recs or {}).get(full)
        text = (e.findtext("m:errorConditionFormula", "", _NS) if e is not None else "").strip()
        desc = (row.get("Description") or "").strip() or (f"Error when: {' '.join(text.split())[:160]}" if text else "No description")
        url = ctx.setup_url(f"/lightning/setup/ObjectManager/{obj}/ValidationRules/{row['Id']}/view") if row.get("Id") else None
        check.audit.append(audit_row(obj, "validation", row["ValidationName"], desc, bool(row.get("Active")),
                                     (row.get("ErrorMessage") or "").strip(), True, url))
    rows = [r for r in every if r.get("Active")]
    names = {k: r for k, r in allnames.items() if r.get("Active")}
    if not rows:
        return []
    if recs is None:
        check.notes_read.append("validation rule formulas")
        check.skipped += [f"Validation rule “{r['ValidationName']}”: its formula couldn’t be read" for r in rows]
        return []
    out: list[Rule] = []
    for full, row in names.items():
        label = row["ValidationName"]
        e = recs.get(full)
        text = e.findtext("m:errorConditionFormula", "", _NS) if e is not None else ""
        if not text:
            check.skipped.append(f"Validation rule “{label}”: its formula couldn’t be read")
            continue
        try:
            formula = Formula(text)
        except (Unsupported, RecursionError) as exc:
            check.skipped.append(f"Validation rule “{label}”: {exc}")
            continue
        shown = e.findtext("m:errorDisplayField", "", _NS) if e is not None else ""
        own = [p for p in formula.fields if "." not in p and p in fields]
        marks = [shown] if shown in fields else own[:3] or ["Name"]
        out.append(Rule("validation", label, marks, message=(row.get("ErrorMessage") or "").strip(), formula=formula))
    return out


_NULL_CHECKS = (
    re.compile(r"\b\w+\.(\w+)\s*==\s*null\b"),
    re.compile(r"\bnull\s*==\s*\w+\.(\w+)\b"),
    re.compile(r"\bString\s*\.\s*is(?:Blank|Empty)\s*\(\s*\w+\.(\w+)\s*\)", re.I),
    re.compile(r"\b\w+\.(\w+)\s*==\s*''"),
    re.compile(r"\.get\(\s*'(\w+)'\s*\)\s*==\s*null"),
)


def _empty_checks(code: str, fields: dict[str, dict]) -> list[str]:
    """Fields the code tests for empty, in code that stops the save with addError."""
    if "adderror" not in code.lower():
        return []
    code = re.sub(r"/\*.*?\*/|//[^\n]*", " ", code, flags=re.S)
    lower = {n.lower(): n for n in fields}
    out: list[str] = []
    for pat in _NULL_CHECKS:
        for m in pat.finditer(code):
            f = lower.get(m.group(1).lower())
            if f and f not in out and fields[f].get("nillable", True):
                out.append(f)
    return out


def trigger_rules(ctx: Ctx, obj: str, fields: dict[str, dict], check: ObjectCheck) -> list[Rule]:
    """Active before insert / before update triggers that stop a save when a field is empty (with their handler classes)."""
    try:
        rows = ctx.setup(f"SELECT Id, Name, Status, UsageBeforeInsert, UsageBeforeUpdate, Body FROM ApexTrigger WHERE TableEnumOrId = '{obj}'")
    except Unavailable:
        check.notes_read.append("Apex triggers")
        return []
    out: list[Rule] = []
    for t in rows:
        body = t.get("Body") or ""
        code = [body]
        found = _empty_checks(body, fields)
        # handler classes the trigger calls (Handler.method(...) or new Handler(...))
        classes = sorted({m for m in re.findall(r"\bnew\s+(\w+)\s*\(|\b(\w+)\s*\.\s*\w+\s*\(", body) for m in m if m} - {"Trigger", "System", "String", "Database"})
        handlers: list[str] = []
        if classes:
            try:
                for c in ctx.setup("SELECT Name, Body FROM ApexClass WHERE Name IN (" + ", ".join(f"'{n}'" for n in classes[:50]) + ")"):
                    code.append(c.get("Body") or "")
                    handlers.append(c.get("Name") or "")
                    found += [f for f in _empty_checks(c.get("Body") or "", fields) if f not in found]
            except Unavailable:
                pass
        if not any("adderror" in c.lower() for c in code):
            continue  # never stops a save: not an enforcement rule
        active = t.get("Status") == "Active"
        before = bool(t.get("UsageBeforeInsert") or t.get("UsageBeforeUpdate"))
        messages = _error_messages(code)
        events = " / ".join(e for e, on in (("before insert", t.get("UsageBeforeInsert")), ("before update", t.get("UsageBeforeUpdate"))) if on)
        desc = (f"Stops the save ({events or 'after save'})" + (f" when {', '.join(fields[f].get('label') or f for f in found)} is empty" if found else "")
                + (f"; handler: {', '.join(h for h in handlers if h)}" if any(handlers) else ""))
        url = ctx.setup_url(f"/lightning/setup/ApexTriggers/page?address=%2F{t['Id']}") if t.get("Id") else None
        # its messages are judged only when the code spells them out (not a Custom Label or a variable)
        worst = next((m for m in messages if message_issue(m)), messages[0] if messages else None)
        row = audit_row(obj, "trigger", t.get("Name") or "trigger", desc, active, worst, bool(messages), url)
        if len(messages) > 1:
            row["message"] = " | ".join(messages)
        check.audit.append(row)
        if active and before and found:
            out.append(Rule("trigger", t.get("Name") or "trigger", found))
    return out


def _error_messages(code: list[str]) -> list[str]:
    """The messages the code passes to addError as plain text ('…'), in order, without repeats."""
    out: list[str] = []
    for c in code:
        for m in re.finditer(r"addError\s*\(\s*'((?:[^'\\]|\\.)*)'\s*[),]", c, re.I):
            text = re.sub(r"\\(.)", r"\1", m.group(1)).strip()
            if text not in out:
                out.append(text)
    return out


def _reason(rule: Rule, value_empty: bool) -> str:
    if rule.kind == "validation":
        return f"Breaks validation rule “{rule.name}”" + (f": {rule.message}" if rule.message else "")
    if rule.kind == "layout":
        return f"Empty, but required on page layout “{rule.name}”"
    if rule.kind == "trigger":
        return f"Empty, but Apex trigger “{rule.name}” requires it (read from its code)"
    return "Empty, but Salesforce requires this field"


def collect(ctx: Ctx, obj: str) -> ObjectCheck:
    """Every rule on `obj` (read once per health check: the validation rules card and Required field gaps share it)."""
    memo = getattr(ctx, "memo", None)
    key = f"required_rules:{obj}"
    if memo is not None and key in memo:
        return memo[key]
    check = ObjectCheck(obj)
    fields = ctx.fields(obj)
    check.rules = (field_rules(ctx, obj, fields, check) + layout_rules(ctx, obj, fields, check)
                   + validation_rules(ctx, obj, fields, check) + trigger_rules(ctx, obj, fields, check))
    if memo is not None:
        memo[key] = check
    return check


def check_object(ctx: Ctx, obj: str, base: str | None = None) -> ObjectCheck:
    """`obj`'s rules (see collect), and its records (those matching `base`) checked against them."""
    check = collect(ctx, obj)
    fields = ctx.fields(obj)
    if not check.rules:
        return check
    simple = sorted({f for r in check.rules if r.kind != "validation" for f in r.fields})
    extra = ["RecordTypeId"] if "RecordTypeId" in fields else []
    # the fields every rule reads; a validation rule whose fields can't be queried is set aside
    def soql(rules: list[Rule]) -> str:
        cols = list(dict.fromkeys(["Id", *extra, *simple, *(p for r in rules if r.formula for p in r.formula.fields)]))
        return f"SELECT {', '.join(cols)} FROM {obj}" + (f" WHERE {base}" if base else "")

    vrules = [r for r in check.rules if r.kind == "validation"]
    try:
        rows = ctx.rows(soql(vrules), limit=MAX_ROWS)
    except SalesforceAuthExpired:
        raise
    except SalesforceError:
        ok = []
        for r in vrules:
            try:
                ctx.rows(soql([r]) + (" AND" if base else " WHERE") + " Id = null", limit=1)
                ok.append(r)
            except SalesforceAuthExpired:
                raise
            except SalesforceError:
                check.skipped.append(f"Validation rule “{r.name}”: a field it uses can’t be read")
        check.rules = [r for r in check.rules if r.kind != "validation" or r in ok]
        rows = ctx.rows(soql(ok), limit=MAX_ROWS)
    check.checked = len(rows)
    check.capped = len(rows) >= MAX_ROWS
    for rec in rows:
        why: dict[str, str] = {}
        hit: list[tuple[str, str]] = []
        per_kind: dict[str, dict[str, str]] = {}

        def mark(r: Rule, f: str) -> None:
            reason = _reason(r, True)
            why[f] = "; ".join(filter(None, [why.get(f), reason]))
            k = per_kind.setdefault(r.kind, {})
            k[f] = "; ".join(filter(None, [k.get(f), reason]))
            # every rule on every field, one line each: “Company: Page layout “Lead Layout””
            line = (r.kind, f"{fields.get(f, {}).get('label') or f}: {r.describe()}")
            if line not in hit:
                hit.append(line)
        rt = _rt(rec.get("RecordTypeId")) if extra else None
        for r in check.rules:
            if r.kind == "validation":
                try:
                    bad = r.formula(rec)  # type: ignore[misc]
                except Exception:  # noqa: BLE001 - a value the evaluator can't handle: not counted against the record
                    bad = False
                if bad:
                    r.broken += 1
                    for f in r.fields:
                        mark(r, f)
                continue
            if r.record_types is not None and rt not in r.record_types:
                continue
            empty = [f for f in r.fields if get_path(rec, f) in (None, "")]
            if empty:
                r.broken += 1
                for f in empty:
                    mark(r, f)
        if why and rec.get("Id"):
            check.bad_ids.append(rec["Id"])
            if len(check.notes) < SHOWN:
                check.notes[rec["Id"]] = why
                check.broken[rec["Id"]] = sorted(hit, key=lambda x: x[1].split(": ", 1)[0])  # field by field
                for k, n in per_kind.items():
                    check.kind_notes.setdefault(k, {})[rec["Id"]] = n
    return check
