"""Find and ask: search every object at once, and turn plain-English questions into safe filters.

Questions are understood by rules (no AI service): the object ("deals", "contacts"), status words
("open", "won", "overdue"), amounts ("over 50k"), dates ("created this month", "last 30 days"),
missing values ("without email"), owners ("owned by Ryan"), places ("in California") and picklist
values ("web leads", "technology accounts"). Words that weren't understood are reported back, so
the person can see exactly what was applied.

Filters are plain data ({field, op, value}). Every field is checked against Salesforce's describe
and every value is typed and escaped before it goes into SOQL, so a filter can never change the
shape of a query — whether it came from the interpreter or was edited in the browser.
"""
import json
import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

from . import explorer
from .client import SalesforceClient

MAX_FILTERS = 20
SEARCH_PER_OBJECT = 5
SEARCH_MAX_OBJECTS = 15

TEXT = {"string", "email", "phone", "url", "picklist", "combobox", "id", "textarea"}
NUMBER = {"double", "currency", "int", "percent", "long"}
DATES = {"date", "datetime"}

OPS = {
    "text": {"eq", "ne", "contains", "in", "notin", "blank", "notblank"},
    "number": {"eq", "ne", "gt", "gte", "lt", "lte", "blank", "notblank"},
    "date": {"eq", "gt", "gte", "lt", "lte", "blank", "notblank"},
    "boolean": {"eq"},
    "reference": {"eq", "ne", "name", "blank", "notblank"},
    "multipicklist": {"blank", "notblank"},
}
CHILD_OPS = {"haschild", "nochild"}

_DATE_LITERAL = re.compile(
    r"^(TODAY|YESTERDAY|TOMORROW|(THIS|LAST|NEXT)_(WEEK|MONTH|QUARTER|YEAR|FISCAL_QUARTER|FISCAL_YEAR)"
    r"|(LAST|NEXT)_N_(DAYS|WEEKS|MONTHS|QUARTERS|YEARS):\d{1,4}|\d{4}-\d{2}-\d{2})$"
)
_ID = re.compile(r"^[A-Za-z0-9]{15}([A-Za-z0-9]{3})?$")


def kind(field: dict) -> str | None:
    t = field["type"]
    if t in TEXT:
        return "text"
    if t in NUMBER:
        return "number"
    if t in DATES:
        return "date"
    if t == "boolean":
        return "boolean"
    if t == "reference":
        return "reference"
    if t == "multipicklist":
        return "multipicklist"
    return None


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise ValueError("Filter text must be 1–255 characters.")
    return "'" + value.strip().replace("\\", "\\\\").replace("'", "\\'") + "'"


def _number(value: Any) -> str:
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Filter number isn’t a number.")
    if not d.is_finite() or isinstance(value, bool):
        raise ValueError("Filter number isn’t a number.")
    return format(d, "f")


def _date(value: Any, field_type: str) -> str:
    if not isinstance(value, str) or not _DATE_LITERAL.match(value):
        raise ValueError("Filter date must be a date like 2026-01-31 or a period like THIS_MONTH.")
    if field_type == "datetime" and value[0].isdigit():
        return f"{value}T00:00:00Z"
    return value


_SYMBOL = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def parse_filters(raw: str | None) -> list[dict]:
    """Filters sent by the browser as JSON: a list of {field, op, value}."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError("Filters aren’t valid.")
    if not isinstance(data, list) or len(data) > MAX_FILTERS:
        raise ValueError("Filters aren’t valid.")
    out = []
    for f in data:
        if not isinstance(f, dict) or not isinstance(f.get("field"), str) or not isinstance(f.get("op"), str):
            raise ValueError("Filters aren’t valid.")
        out.append({"field": f["field"], "op": f["op"], "value": f.get("value")})
    return out


def condition(fields: dict[str, dict], f: dict, children: dict[str, dict] | None = None) -> str:
    """One filter as a SOQL condition. Raises ValueError for anything not allowed."""
    name, op, value = f["field"], f["op"], f.get("value")
    if op in CHILD_OPS:
        rel = (children or {}).get(name)
        if not rel:
            raise ValueError(f"Unknown related list: {name}.")
        # Object and link field come from describe, not from the filter.
        return f"Id {'IN' if op == 'haschild' else 'NOT IN'} (SELECT {rel['field']} FROM {rel['object']} WHERE {rel['field']} != null)"
    field = fields.get(name)
    if not field or not field.get("filterable"):
        raise ValueError(f"You can’t filter on {name}.")
    k = kind(field)
    if k is None or op not in OPS[k]:
        raise ValueError(f"You can’t use “{op}” on {field.get('label') or name}.")
    if op == "blank":
        return f"{name} = null"
    if op == "notblank":
        return f"{name} != null"
    if k == "boolean":
        if not isinstance(value, bool):
            raise ValueError("Filter value must be true or false.")
        return f"{name} = {'TRUE' if value else 'FALSE'}"
    if k == "number":
        return f"{name} {_SYMBOL[op]} {_number(value)}"
    if k == "date":
        return f"{name} {_SYMBOL[op]} {_date(value, field['type'])}"
    if k == "reference":
        if op == "name":
            targets = field.get("referenceTo") or []
            if not field.get("relationshipName") or not targets or not all(t in explorer._NAMED for t in targets):
                raise ValueError(f"You can’t search {field.get('label') or name} by name.")
            return f"{field['relationshipName']}.Name LIKE '%{explorer._soql_text(str(value or '').strip()[:100])}%'"
        if not isinstance(value, str) or not _ID.match(value):
            raise ValueError("Filter value must be a record id.")
        return f"{name} {_SYMBOL[op]} '{value}'"
    # text
    if op == "contains":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Filter text can’t be empty.")
        return f"{name} LIKE '%{explorer._soql_text(value.strip()[:100])}%'"
    if op in ("in", "notin"):
        if not isinstance(value, list) or not 1 <= len(value) <= 50:
            raise ValueError("Pick between 1 and 50 values.")
        return f"{name} {'IN' if op == 'in' else 'NOT IN'} ({', '.join(_text(v) for v in value)})"
    return f"{name} {_SYMBOL[op]} {_text(value)}"


def conditions(fields: dict[str, dict], filters: list[dict], children: dict[str, dict] | None = None) -> list[str]:
    return [condition(fields, f, children) for f in filters]


# ---------------------------------------------------------------- labels people can read

def _period(value: str) -> str:
    m = re.match(r"^(LAST|NEXT)_N_(DAYS|WEEKS|MONTHS|QUARTERS|YEARS):(\d+)$", value)
    if m:
        unit = m.group(2).lower()
        n = int(m.group(3))
        return f"{m.group(1).lower()} {n} {unit if n != 1 else unit[:-1]}"
    return value.replace("_", " ").lower()


def label(fields: dict[str, dict], f: dict, children: dict[str, dict] | None = None) -> str:
    op, value = f["op"], f.get("value")
    if op in CHILD_OPS:
        rel = (children or {}).get(f["field"], {})
        what = (rel.get("label") or f["field"]).lower()
        return f"Has {what}" if op == "haschild" else f"No {what}"
    field = fields.get(f["field"], {})
    name = field.get("label") or f["field"]
    if field.get("type") == "reference":
        name = re.sub(r"\s+ID$", "", name)
    if op == "blank":
        return f"{name} is empty"
    if op == "notblank":
        return f"{name} is filled in"
    if op == "name":
        return f"{name} is {value}"
    if field.get("type") == "boolean":
        return f"{name}: {'yes' if value else 'no'}"
    if op == "contains":
        return f"{name} contains “{value}”"
    if op in ("in", "notin"):
        vals = ", ".join(str(v) for v in value or [])
        return f"{name} {'is' if op == 'in' else 'is not'} {vals}"
    if field.get("type") in DATES and isinstance(value, str) and not value[0].isdigit():
        p = _period(value)
        if op == "eq":
            return f"{name}: {p}"
        if op == "lt" and value.startswith("LAST_N_"):
            return f"{name} more than {p.removeprefix('last ')} ago"
        return f"{name} {'before' if op in ('lt', 'lte') else 'after'} {p}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = f"{value:,.0f}" if float(value).is_integer() else f"{value:,}"
    word = {"eq": "is", "ne": "is not", "gt": ">", "gte": "≥", "lt": "<", "lte": "≤"}.get(op, op)
    return f"{name} {word} {value}"


# ---------------------------------------------------------------- search every object

def _search_fields(desc: dict) -> list[str]:
    fields = explorer._fields(desc)
    name = explorer._name_field(desc)
    out = [name] if name else []
    for f in ("Email", "Company", "Title", "StageName", "Status", "Phone", "Industry", "Type"):
        if f in fields and f not in out and len(out) < 3:
            out.append(f)
    return out


def search_all(sf: SalesforceClient, term: str, objects: list[str] | None) -> list[dict]:
    """Find records whose name, email, phone or other text matches, across many objects in one call."""
    term = re.sub(r"[?&|!{}\[\]()^~*:\\\"'+\-]", " ", term or "").strip()
    if len(term) < 2:
        return []
    known = explorer._global(sf)
    names = [o for o in (objects or explorer.COMMON) if o in known and known[o].get("searchable") and not explorer.is_system(o)]
    names = list(dict.fromkeys(names))[:SEARCH_MAX_OBJECTS]
    if not names:
        return []
    params: list[tuple[str, str]] = [("q", term[:100]), ("in", "ALL"), ("overallLimit", "100")]
    shown: dict[str, list[str]] = {}
    for o in names:
        cols = _search_fields(explorer._describe(sf, o))
        shown[o] = cols
        params += [("sobject", o), (f"{o}.fields", ",".join(["Id"] + cols)), (f"{o}.limit", str(SEARCH_PER_OBJECT))]
    body = sf.get(f"{explorer._api(sf)}/parameterizedSearch/?{urlencode(params)}")
    groups: dict[str, list[dict]] = {}
    for r in body.get("searchRecords", []):
        o = (r.get("attributes") or {}).get("type")
        if o not in shown:
            continue
        cols = shown[o]
        title = r.get(cols[0]) if cols else None
        detail = " · ".join(str(r[c]) for c in cols[1:] if r.get(c))
        groups.setdefault(o, []).append({"id": r.get("Id"), "name": title or r.get("Id"), "detail": detail or None})
    return [
        {"object": o, "label": known[o].get("label") or o, "label_plural": known[o].get("labelPlural") or o, "records": groups[o]}
        for o in names
        if o in groups
    ]


# ---------------------------------------------------------------- understand a question

SYNONYMS = {
    "deal": "Opportunity", "deals": "Opportunity", "opp": "Opportunity", "opps": "Opportunity", "pipeline": "Opportunity",
    "company": "Account", "companies": "Account", "customer": "Account", "customers": "Account", "client": "Account", "clients": "Account",
    "people": "Contact", "person": "Contact",
    "ticket": "Case", "tickets": "Case", "support case": "Case", "support cases": "Case",
    "prospect": "Lead", "prospects": "Lead",
    "activity": "Task", "activities": "Task", "todo": "Task", "todos": "Task", "to-do": "Task", "to-dos": "Task",
    "meeting": "Event", "meetings": "Event", "product": "Product2", "products": "Product2",
}

FIELD_ALIASES = {
    "email": "Email", "emails": "Email", "email address": "Email", "e-mail": "Email",
    "phone": "Phone", "phone number": "Phone", "phones": "Phone", "mobile": "MobilePhone",
    "owner": "OwnerId", "account": "AccountId", "contact": "ContactId", "website": "Website", "web site": "Website",
    "industry": "Industry", "title": "Title", "job title": "Title", "company": "Company", "amount": "Amount", "value": "Amount",
    "close date": "CloseDate", "source": "LeadSource", "lead source": "LeadSource", "revenue": "AnnualRevenue",
    "annual revenue": "AnnualRevenue", "employees": "NumberOfEmployees", "stage": "StageName", "status": "Status",
    "rating": "Rating", "description": "Description", "next step": "NextStep", "due date": "ActivityDate",
    "subject": "Subject", "priority": "Priority", "type": "Type",
}

# Status words per object: phrase -> filters (only used when the object has those fields).
STATUS = {
    "Opportunity": [
        (r"closed\s+won|won", [("IsWon", "eq", True)]),
        (r"closed\s+lost|lost", [("IsClosed", "eq", True), ("IsWon", "eq", False)]),
        (r"overdue|past\s+due|late", [("IsClosed", "eq", False), ("CloseDate", "lt", "TODAY")]),
        (r"open|active|in\s+progress", [("IsClosed", "eq", False)]),
        (r"closed", [("IsClosed", "eq", True)]),
    ],
    "Case": [
        (r"escalated", [("IsEscalated", "eq", True)]),
        (r"open|unresolved|active", [("IsClosed", "eq", False)]),
        (r"closed|resolved", [("IsClosed", "eq", True)]),
    ],
    "Task": [
        (r"overdue|past\s+due|late", [("IsClosed", "eq", False), ("ActivityDate", "lt", "TODAY")]),
        (r"open|incomplete|not\s+done|pending", [("IsClosed", "eq", False)]),
        (r"completed|complete|done|closed", [("IsClosed", "eq", True)]),
    ],
    "Lead": [
        (r"unconverted|not\s+converted|open", [("IsConverted", "eq", False)]),
        (r"converted", [("IsConverted", "eq", True)]),
    ],
    "*": [
        (r"inactive", [("IsActive", "eq", False)]),
        (r"active", [("IsActive", "eq", True)]),
    ],
}

DATE_VERBS = {
    "created": "CreatedDate", "added": "CreatedDate", "new": "CreatedDate", "made": "CreatedDate",
    "closing": "CloseDate", "closes": "CloseDate", "close": "CloseDate", "closed": "CloseDate",
    "modified": "LastModifiedDate", "updated": "LastModifiedDate", "changed": "LastModifiedDate", "edited": "LastModifiedDate",
    "due": "ActivityDate",
}
DEFAULT_DATE = {"Opportunity": "CloseDate", "Task": "ActivityDate"}

PLACES = {
    "Account": ("BillingState", "BillingCountry"), "Contact": ("MailingState", "MailingCountry"),
    "Lead": ("State", "Country"),
}
US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}
COUNTRIES = {
    "usa": ["USA", "US", "United States", "United States of America"], "us": ["USA", "US", "United States", "United States of America"],
    "united states": ["USA", "US", "United States", "United States of America"], "america": ["USA", "US", "United States", "United States of America"],
    "uk": ["UK", "United Kingdom", "GB", "Great Britain", "England"], "united kingdom": ["UK", "United Kingdom", "GB", "Great Britain", "England"],
    "england": ["UK", "United Kingdom", "GB", "England"], "uae": ["UAE", "United Arab Emirates", "AE"],
    "india": ["India", "IN"], "canada": ["Canada", "CA"], "germany": ["Germany", "DE"], "france": ["France", "FR"],
    "australia": ["Australia", "AU"], "japan": ["Japan", "JP"], "china": ["China", "CN"], "singapore": ["Singapore", "SG"],
    "mexico": ["Mexico", "MX"], "brazil": ["Brazil", "BR"], "spain": ["Spain", "ES"], "italy": ["Italy", "IT"],
    "netherlands": ["Netherlands", "NL"], "ireland": ["Ireland", "IE"],
}

STOP = set(
    "show me list find get give all the a an of with and or that which who whose are is was were be have has had do does "
    "any my our their records record please what where there in on for by to from at as it its this those these can you i "
    "we want need see view display how many much number count total s than more less then just only also some".split()
)
# Picklist values too common to mean anything on their own.
_WEAK_VALUES = {"new", "open", "other", "none", "all", "yes", "no", "true", "false", "-", "n/a", "na", "unknown"}

# Picklists whose values people type as plain words; a word may match the start of a value.
PREFIX_FIELDS = ("LeadSource", "Industry", "Type", "StageName", "Status", "Rating", "Priority", "Origin")


def _matchable_picklist(name: str, f: dict) -> bool:
    """Picklists whose values can be matched from words (not state/country codes: "IN", "CA" are words too)."""
    return f["type"] in ("picklist", "combobox") and bool(f.get("filterable")) and not name.endswith(("StateCode", "CountryCode"))


_NUM = r"\$?\s?(\d[\d,]*(?:\.\d+)?)(?:\s*(k|mn|m|million|thousand|bn|b|billion)\b)?"


def _amount(num: str, unit: str | None) -> float:
    v = float(num.replace(",", ""))
    mult = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
    v *= mult.get((unit or "").lower(), 1)
    return int(v) if v.is_integer() else v


class _Text:
    """The question, with understood parts blanked out as they're used."""

    def __init__(self, question: str):
        q = re.sub(r"\s+", " ", question.strip())
        low = q.lower()
        self.orig = q if len(low) == len(q) else low
        self.low = low

    def find(self, pattern: str):
        return re.search(pattern, self.low)

    def finditer(self, pattern: str):
        return list(re.finditer(pattern, self.low))

    def take(self, start: int, end: int) -> None:
        self.low = self.low[:start] + " " * (end - start) + self.low[end:]

    def original(self, start: int, end: int) -> str:
        return self.orig[start:end]

    def leftover(self) -> list[str]:
        words = re.findall(r"[a-z0-9][a-z0-9'&.-]*", self.low)
        return [w for w in words if w not in STOP and not w.isdigit()]


def _object_index(objects: dict[str, dict], prefer: list[str]) -> dict[str, str]:
    # Standard objects first, so a custom object also labelled "Accounts" never wins over Account.
    custom = sorted(n for n, o in objects.items() if o.get("custom"))
    allowed = list(dict.fromkeys([*explorer.COMMON, *prefer, *custom]))
    idx: dict[str, str] = {}
    for name in allowed:
        o = objects.get(name)
        if not o or explorer.is_system(name):
            continue
        for phrase in (o.get("labelPlural"), o.get("label"), name):
            if phrase and len(phrase) > 2:
                idx.setdefault(phrase.lower(), name)
    for phrase, name in SYNONYMS.items():
        if name in objects:
            idx.setdefault(phrase, name)
    return idx


def _find_object(t: _Text, objects: dict[str, dict], prefer: list[str]) -> str | None:
    idx = _object_index(objects, prefer)
    best = None
    for phrase in sorted(idx, key=len, reverse=True):
        m = re.search(rf"\b{re.escape(phrase)}\b", t.low)
        if m and (best is None or m.start() < best[0].start()):
            best = (m, idx[phrase])
    if best:
        t.take(best[0].start(), best[0].end())
        return best[1]
    return None


def _find_field(fields: dict[str, dict], phrase: str, kinds: set[str] | None = None) -> str | None:
    phrase = re.sub(r"\s+", " ", phrase.strip().lower())
    tries = [phrase, phrase.rstrip("s"), phrase.removesuffix("es")]

    def ok(name: str | None) -> bool:
        f = fields.get(name or "")
        return bool(f and f.get("filterable") and (kinds is None or kind(f) in kinds))

    for p in tries:
        if ok(FIELD_ALIASES.get(p)):
            return FIELD_ALIASES[p]
    for p in tries:
        for name, f in fields.items():
            lab = (f.get("label") or "").lower()
            if p and (lab == p or re.sub(r"\s+id$", "", lab) == p or name.lower().removesuffix("__c").replace("_", " ") == p) and ok(name):
                return name
    return None


class Interpreter:
    def __init__(self, fields: dict[str, dict], obj: str, children: dict[str, dict]):
        self.fields, self.obj, self.children = fields, obj, children
        self.filters: list[dict] = []
        self.sort: tuple[str, str] | None = None

    def has(self, *names: str) -> bool:
        return all(n in self.fields and self.fields[n].get("filterable") for n in names)

    def add(self, field: str, op: str, value: Any = None) -> bool:
        if op not in CHILD_OPS and not self.has(field):
            return False
        f = {"field": field, "op": op, "value": value}
        try:
            condition(self.fields, f, self.children)
        except ValueError:
            return False
        if f not in self.filters:
            self.filters.append(f)
        return True

    def money_field(self) -> str | None:
        for n in ("Amount", "AnnualRevenue", "ExpectedRevenue", "UnitPrice", "TotalPrice"):
            if self.has(n):
                return n
        return next((n for n, f in self.fields.items() if f["type"] == "currency" and f.get("filterable")), None)

    def date_field(self, verb: str | None) -> str | None:
        if verb:
            name = DATE_VERBS.get(verb)
            if name == "CloseDate" and self.obj == "Case":
                name = "ClosedDate"
            if name == "ActivityDate" and not self.has("ActivityDate"):
                name = "DueDate" if self.has("DueDate") else None
            if name and self.has(name):
                return name
        d = DEFAULT_DATE.get(self.obj)
        if d and self.has(d):
            return d
        return "CreatedDate" if self.has("CreatedDate") else None


_PERIOD = (
    r"(today|yesterday|tomorrow|(?:this|last|next|previous|past|current)\s+(?:week|month|quarter|year)"
    r"|(?:in\s+the\s+|within\s+the\s+|during\s+the\s+|over\s+the\s+)?(?:last|past|next|previous)\s+(\d+)\s+(days?|weeks?|months?|quarters?|years?))"
)


def _literal(period: str, n: str | None, unit: str | None) -> str:
    period = period.strip()
    if n:
        u = unit.rstrip("s").upper() + "S"
        direction = "NEXT" if " next " in f" {period} " else "LAST"
        return f"{direction}_N_{u}:{int(n)}"
    period = re.sub(r"^(previous|past)\s", "last ", period)
    period = re.sub(r"^current\s", "this ", period)
    return period.upper().replace(" ", "_")


def interpret(question: str, objects: dict[str, dict], describe: Callable[[str], dict],
              children_of: Callable[[str], list[dict]], prefer: list[str] | None = None, context: str | None = None) -> dict:
    """Turn a question into {object, filters, sort, dir, count_only, ignored}. Raises ValueError if it can't."""
    prefer = prefer or []
    t = _Text(question[:300])
    if not t.low.strip():
        raise ValueError("Type a question, like “open deals over 50k closing this month”.")
    count_only = bool(t.find(r"\b(how many|number of|count of|count|total)\b"))
    for m in t.finditer(r"\b(how many|number of|count of|count|total)\b"):
        t.take(m.start(), m.end())

    obj = _find_object(t, objects, prefer) or (context if context in objects else None)
    if not obj:
        raise ValueError("Which records do you mean? Start with an object, like “accounts…”, “open deals…” or “leads…”.")
    desc = describe(obj)
    fields = explorer._fields(desc)
    children = {c["name"]: c for c in children_of(obj)}
    it = Interpreter(fields, obj, children)

    # Owner: "owned by Ryan Clark", "assigned to ryan"
    m = t.find(r"\b(?:owned by|owner is|owner|assigned to|belonging to|belongs to|for rep|rep)\s+([a-z][a-z.'-]*)(?:\s+([a-z][a-z.'-]*))?")
    if m and it.has("OwnerId"):
        first, second = m.group(1), m.group(2)
        end = m.end()
        if second and (second in STOP or second in DATE_VERBS or second in ("without", "with", "over", "under", "created")):
            end = m.end(1)
        if first not in STOP:
            it.add("OwnerId", "name", t.original(m.start(1), end).strip())
            t.take(m.start(), end)

    # Name: named "Acme", called Acme, or anything in quotes
    name_field = explorer._name_field(desc)
    m = t.find(r'\b(?:named|called|name contains|name like|name is)\s+(?:["“]([^"”]{1,80})["”]|([^\s"“”][^"“”]*?)(?=\s+(?:and|with|without|in|created|that|owned)\b|[,?]|\s*$))') \
        or t.find(r'["“]([^"”]{2,80})["”]')
    if m and name_field:
        g = 1 if m.group(1) else 2
        it.add(name_field, "contains", t.original(m.start(g), m.end(g)).strip())
        t.take(m.start(), m.end())

    # Stale: "not updated in 90 days", "no activity for 3 months", "older than 1 year"
    m = t.find(r"\b(not (?:modified|updated|touched|changed|edited)|no (?:activity|updates?|changes?)|untouched|stale|older than)\s+(?:in|for|since)?\s*(?:the\s+)?(?:last|past)?\s*(\d+)\s*(days?|weeks?|months?|years?)\b")
    if m:
        n = int(m.group(2)) * {"d": 1, "w": 7, "m": 30, "y": 365}[m.group(3)[0]]
        target = "CreatedDate" if m.group(1) == "older than" else "LastModifiedDate"
        if it.add(target, "lt", f"LAST_N_DAYS:{n}"):
            t.take(m.start(), m.end())

    # Status words ("open", "won", "overdue", "converted", "active")
    for table in (STATUS.get(obj, []), STATUS["*"]):
        for pattern, conds in table:
            m = t.find(rf"\b(?:{pattern})\b")
            if m and all(it.has(f) for f, _, _ in conds):
                for f, op, v in conds:
                    it.add(f, op, v)
                t.take(m.start(), m.end())

    # Amounts: "between 10k and 50k", "over 50k", "under $5,000", "more than 100 employees"
    m = t.find(rf"\bbetween\s+{_NUM}\s+and\s+{_NUM}")
    if m:
        target = it.money_field()
        if target:
            it.add(target, "gte", _amount(m.group(1), m.group(2)))
            it.add(target, "lte", _amount(m.group(3), m.group(4)))
            t.take(m.start(), m.end())
    for m in reversed(t.finditer(rf"(?:\b([a-z]+(?:\s[a-z]+)?)\s+)?(?:is\s+|of\s+)?\b(over|above|more than|greater than|bigger than|at least|under|below|less than|smaller than|at most|>=|<=|>|<)\s*{_NUM}(?:\s+([a-z]+))?")):
        before, word, num, unit, after = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        target, start, end = None, m.start(2), m.end(4) if m.group(4) else m.end(3)
        if after:
            target = _find_field(fields, after, {"number"})
            if target:
                end = m.end(5)
        if not target and before:
            for phrase in (before, before.split()[-1]):
                target = _find_field(fields, phrase, {"number"})
                if target:
                    start = m.start(1) + (len(before) - len(phrase))
                    break
        target = target or it.money_field()
        if not target:
            continue
        op = "gte" if word in ("at least", ">=") else "lte" if word in ("at most", "<=") else \
            "gt" if word in ("over", "above", "more than", "greater than", "bigger than", ">") else "lt"
        if it.add(target, op, _amount(num, unit)):
            t.take(start, end)

    # Dates: "created this month", "closing next quarter", "in the last 30 days", "in 2025"
    verbs = "|".join(sorted(DATE_VERBS, key=len, reverse=True))
    for m in reversed(t.finditer(rf"\b(?:({verbs})\s+)?(?:in\s+|during\s+|within\s+|on\s+)?(?:the\s+)?{_PERIOD}\b")):
        target = it.date_field(m.group(1))
        if target and it.add(target, "eq", _literal(m.group(2), m.group(3), m.group(4))):
            t.take(m.start(), m.end())
    for m in reversed(t.finditer(rf"\b(?:({verbs})\s+)?(?:in|during)\s+((?:19|20)\d\d)\b")):
        target = it.date_field(m.group(1))
        if target:
            y = m.group(2)
            it.add(target, "gte", f"{y}-01-01")
            it.add(target, "lte", f"{y}-12-31")
            t.take(m.start(), m.end())
    for m in reversed(t.finditer(rf"\b({verbs})\s+(before|after)\s+(today|yesterday|tomorrow)\b")):
        target = it.date_field(m.group(1))
        if target and it.add(target, "lt" if m.group(2) == "before" else "gt", m.group(3).upper()):
            t.take(m.start(), m.end())

    # Missing / present: "without email", "with no phone", "missing industry", "with contacts", "no opportunities"
    stop_after = r"(?=\s+(?:and|or|in|with|without|created|that|who|which|over|under|owned|but)\b|[,.?]|\s*$)"
    for m in reversed(t.finditer(rf"\b(without|with no|with out|no|missing|empty|blank|lacking|not having|with|has|having|have)\s+(?:an?\s+|any\s+)?([a-z][a-z ]{{1,40}}?){stop_after}")):
        neg = m.group(1) not in ("with", "has", "having", "have")
        phrase = m.group(2).strip()
        rel = next((c for c in children.values() if (c.get("label") or "").lower() in (phrase, phrase + "s") or c["name"].lower() == phrase), None)
        if rel and rel.get("primary", True):
            if it.add(rel["name"], "nochild" if neg else "haschild"):
                t.take(m.start(), m.end())
            continue
        target = _find_field(fields, phrase)
        if target and it.add(target, "blank" if neg else "notblank"):
            t.take(m.start(), m.end())

    # Picklist values: "web leads", "technology accounts", "high priority cases", "stage prospecting"
    found: list[tuple[int, int, str, str]] = []
    picklists = {n: f for n, f in fields.items() if _matchable_picklist(n, f)}
    for name, f in picklists.items():
        for p in f.get("picklistValues") or []:
            v = p.get("value")
            if not p.get("active", True) or not v or len(v) < 2 or v.lower() in _WEAK_VALUES:
                continue
            for m in re.finditer(rf"(?<![a-z0-9]){re.escape(v.lower())}(?![a-z0-9])", t.low):
                # Short codes ("IN", "CA") only count when typed the same way, so the word "in" isn't Indiana.
                if len(v) <= 3 and t.original(m.start(), m.end()) != v:
                    continue
                found.append((m.start(), m.end(), name, v))
    found.sort(key=lambda x: (-(x[1] - x[0]), x[0]))
    chosen: dict[str, list[str]] = {}
    for start, end, name, v in found:
        if t.low[start:end].strip() != v.lower():
            continue  # already used by a longer value
        chosen.setdefault(name, [])
        if v not in chosen[name]:
            chosen[name].append(v)
        t.take(start, end)
        for word in {fields[name].get("label", "").lower(), *[k for k, v in FIELD_ALIASES.items() if v == name]}:
            if not word:
                continue
            before = re.search(rf"\b{re.escape(word)}\s*(?:is|=|:)?\s*$", t.low[:start])
            if before:
                t.take(before.start(), before.end())
            after = re.match(rf"^\s*{re.escape(word)}\b", t.low[end:])
            if after:
                t.take(end, end + after.end())
    # A word that starts exactly one value of a common picklist: "web" -> "Website", "tech" -> "Technology".
    for m in t.finditer(r"\b[a-z][a-z-]{2,}\b"):
        word = m.group(0)
        if word in STOP or word in DATE_VERBS:
            continue
        hits = {(n, v) for n in PREFIX_FIELDS if n in picklists and n not in chosen
                for v in (p.get("value") for p in picklists[n].get("picklistValues") or [] if p.get("active", True))
                if v and v.lower().startswith(word) and v.lower() not in _WEAK_VALUES}
        if len(hits) == 1:
            n, v = hits.pop()
            chosen[n] = [v]
            t.take(m.start(), m.end())
    for name, values in chosen.items():
        it.add(name, "in", values) if len(values) > 1 else it.add(name, "eq", values[0])

    # Places: "in California", "from India", "based in New York"
    m = t.find(r"\b(?:located in|based in|in|from)\s+([a-z][a-z .'-]{1,30}?)(?=\s+(?:and|with|without|that|created|over|under|owned|who)\b|[,.?]|\s*$)")
    if m:
        place = m.group(1).strip()
        state_f, country_f = PLACES.get(obj, (None, None))
        if not state_f:
            state_f = next((n for n in fields if n.endswith("State") and kind(fields[n]) == "text"), None)
            country_f = next((n for n in fields if n.endswith("Country") and kind(fields[n]) == "text"), None)
        done = False
        if place in US_STATES and state_f:
            done = it.add(state_f, "in", [place.title(), US_STATES[place]])
        elif len(place) == 2 and place.upper() in US_STATES.values() and state_f and place not in COUNTRIES:
            st = next(k for k, v in US_STATES.items() if v == place.upper())
            done = it.add(state_f, "in", [st.title(), place.upper()])
        elif country_f and len(place.split()) <= 3 and place not in STOP:
            done = it.add(country_f, "in", COUNTRIES.get(place, [t.original(m.start(1), m.end(1)).strip().title()]))
        if done:
            t.take(m.start(), m.end())

    # Sorting: "top", "biggest", "newest", "oldest"
    m = t.find(r"\b(top|biggest|largest|highest|smallest|lowest|newest|latest|most recent|recent|oldest)\b(?:\s+\d+)?")
    if m:
        w = m.group(1)
        if w in ("top", "biggest", "largest", "highest", "smallest", "lowest"):
            target = it.money_field()
            if target:
                it.sort = (target, "asc" if w in ("smallest", "lowest") else "desc")
                t.take(m.start(), m.end())
        elif it.has("CreatedDate"):
            it.sort = ("CreatedDate", "asc" if w == "oldest" else "desc")
            t.take(m.start(), m.end())

    ignored = [w for w in t.leftover() if w not in DATE_VERBS and w not in ("named", "called", "owned")]
    return {
        "object": obj,
        "filters": [{**f, "label": label(fields, f, children)} for f in it.filters],
        "sort": it.sort[0] if it.sort else None,
        "dir": it.sort[1] if it.sort else None,
        "count_only": count_only,
        "ignored": list(dict.fromkeys(ignored))[:10],
    }


def ask(sf: SalesforceClient, question: str, prefer: list[str] | None, context: str | None) -> dict:
    known = explorer._global(sf)
    answer = interpret(
        question, known,
        describe=lambda n: explorer._describe(sf, n),
        children_of=lambda n: explorer.child_relationships(sf, n),
        prefer=[p for p in (prefer or []) if p in known], context=context,
    )
    obj = answer["object"]
    desc = explorer._describe(sf, obj)
    children = {c["name"]: c for c in explorer.child_relationships(sf, obj)}
    where = conditions(explorer._fields(desc), answer["filters"], children)
    soql = f"SELECT COUNT() FROM {obj}" + (" WHERE " + " AND ".join(where) if where else "")
    total = sf.query(soql).get("totalSize")
    g = known[obj]
    return {**answer, "question": question.strip(), "label": g.get("label") or obj,
            "label_plural": g.get("labelPlural") or obj, "total": total}
