"""Read-only data explorer: list objects, describe fields, and page through records.

Every object and field name that goes into a SOQL string is checked against
Salesforce's own describe results first, and search text is escaped, so user
input can never change the shape of a query.
"""
import re
import time
from typing import Any
from urllib.parse import quote

from .client import SalesforceClient
from .errors import SalesforceError

CACHE_SECONDS = 600
PAGE_SIZE = 200  # Salesforce's smallest query batch size
MAX_COLUMNS = 25

# Objects most people care about, shown first.
COMMON = [
    "Account", "Contact", "Lead", "Opportunity", "Case", "Task", "Event", "Campaign",
    "Product2", "Pricebook2", "Quote", "Contract", "Order", "User",
]

# Housekeeping objects (history, sharing, feeds, change events…), hidden by default.
_SYSTEM_SUFFIXES = ("History", "Share", "Feed", "ChangeEvent", "__Tag", "__mdt", "__e", "__x", "__b")
_SYSTEM_PREFIXES = ("Apex", "Auth", "Setup", "Flow", "Permission", "Login", "Process", "Package", "Platform")

# Reference targets that always have a Name field, so we can show "Owner: Jane Doe" instead of an id.
_NAMED = {"Account", "Contact", "Lead", "User", "Group", "Opportunity", "Campaign", "Product2", "Pricebook2",
          "Case", "Quote", "Contract", "Order", "RecordType", "Profile", "UserRole"}

# Field types we can't show as a table column.
_NO_COLUMN = {"base64", "address", "location", "complexvalue", "anyType", "json"}

_PREFERRED = ["StageName", "Status", "Email", "Phone", "Company", "Title", "Industry", "Type", "Amount",
              "CloseDate", "LeadSource", "AccountId", "OwnerId", "IsActive", "CreatedDate", "LastModifiedDate"]

_ID_RE = re.compile(r"^[A-Za-z0-9]{15}([A-Za-z0-9]{3})?$")
_REST_CURSOR_RE = re.compile(r"^/services/data/v\d+\.\d+/query/[A-Za-z0-9]+-\d+$")


class _Cursor:
    """A REST query's nextRecordsUrl, or a Bulk job's results locator (see bulk.CURSOR_RE)."""

    @staticmethod
    def match(c: str) -> bool:
        from .bulk import CURSOR_RE
        return bool(_REST_CURSOR_RE.match(c) or CURSOR_RE.match(c))


_CURSOR_RE = _Cursor

_cache: dict[tuple, tuple[float, Any]] = {}


class NotFound(Exception):
    pass


def _cached(key: tuple, load):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = load()
    _cache[key] = (time.monotonic(), value)
    return value


def clear_cache() -> None:
    _cache.clear()


def _api(sf: SalesforceClient) -> str:
    return f"/services/data/{sf.settings.sf_api_version}"


def _org(sf: SalesforceClient) -> str:
    return sf.conn.org_id or sf.conn.instance_url


def is_system(name: str) -> bool:
    return name.endswith(_SYSTEM_SUFFIXES) or name.startswith(_SYSTEM_PREFIXES)


# ---------------------------------------------------------------- objects

def _global(sf: SalesforceClient) -> dict[str, dict]:
    def load():
        body = sf.get(f"{_api(sf)}/sobjects")
        return {
            o["name"]: o
            for o in body.get("sobjects", [])
            if o.get("queryable") and o.get("retrieveable") and not o.get("deprecatedAndHidden")
        }

    return _cached(("global", _org(sf)), load)


def _record_counts(sf: SalesforceClient) -> dict[str, int]:
    """Approximate counts for every object in one call (Salesforce updates these periodically)."""
    def load():
        try:
            body = sf.get(f"{_api(sf)}/limits/recordCount")
        except SalesforceError:
            return {}
        return {o["name"]: o.get("count", 0) for o in body.get("sObjects", [])}

    return _cached(("counts", _org(sf)), load)


def list_objects(sf: SalesforceClient) -> list[dict]:
    counts = _record_counts(sf)
    rank = {n: i for i, n in enumerate(COMMON)}
    out = [
        {
            "name": o["name"],
            "label": o.get("label") or o["name"],
            "label_plural": o.get("labelPlural") or o.get("label") or o["name"],
            "custom": bool(o.get("custom")),
            "common": o["name"] in rank,
            "system": is_system(o["name"]),
            "approx_count": counts.get(o["name"]),
        }
        for o in _global(sf).values()
    ]
    out.sort(key=lambda o: (rank.get(o["name"], 999), o["label"].lower()))
    return out


# ---------------------------------------------------------------- describe

def _describe(sf: SalesforceClient, name: str) -> dict:
    if name not in _global(sf):
        raise NotFound(name)
    return _cached(("describe", _org(sf), name), lambda: sf.get(f"{_api(sf)}/sobjects/{quote(name)}/describe"))


def _fields(desc: dict) -> dict[str, dict]:
    return {f["name"]: f for f in desc.get("fields", [])}


def _name_field(desc: dict) -> str | None:
    return next((f["name"] for f in desc.get("fields", []) if f.get("nameField")), None)


def default_columns(desc: dict) -> list[str]:
    fields = _fields(desc)
    if desc.get("uploadColumns"):  # an uploaded file: all its columns, in the file's order
        return ["Id", *[c for c in desc["uploadColumns"] if c != "Id" and c in fields]][:MAX_COLUMNS]
    cols = ["Id"]
    name = _name_field(desc)
    if name:
        cols.append(name)
    for f in _PREFERRED:
        if f in fields and f not in cols and fields[f]["type"] not in _NO_COLUMN:
            cols.append(f)
        if len(cols) >= 8:
            return cols
    for f in desc.get("fields", []):
        if len(cols) >= 8:
            break
        if f["name"] not in cols and f["type"] not in _NO_COLUMN and not f.get("calculated") and f["type"] != "textarea":
            cols.append(f["name"])
    return cols


def describe_object(sf: SalesforceClient, name: str) -> dict:
    desc = _describe(sf, name)
    g = _global(sf)[name]
    return {
        "name": name,
        "label": desc.get("label") or name,
        "label_plural": desc.get("labelPlural") or name,
        "custom": bool(desc.get("custom")),
        "name_field": _name_field(desc),
        "searchable": bool(_search_fields(desc)),
        "default_columns": default_columns(desc),
        "child_relationships": child_relationships(sf, name),
        "approx_count": _record_counts(sf).get(name),
        "salesforce_url": f"{sf.base}/lightning/o/{quote(name)}/list" if g.get("keyPrefix") else None,
        "fields": [
            {
                "name": f["name"],
                "label": f.get("label") or f["name"],
                "type": f["type"],
                "custom": bool(f.get("custom")),
                "required": not f.get("nillable", True) and f.get("createable", False) and not f.get("defaultedOnCreate", False),
                "sortable": bool(f.get("sortable")),
                "filterable": bool(f.get("filterable")),
                "groupable": bool(f.get("groupable")),
                "column": f["type"] not in _NO_COLUMN,
                "reference_to": f.get("referenceTo") or [],
                "help_text": f.get("inlineHelpText"),
                "picklist_values": [p["value"] for p in f.get("picklistValues") or [] if p.get("active")][:100],
            }
            for f in desc.get("fields", [])
        ],
    }


# ---------------------------------------------------------------- related records

# Related lists people look at most, shown first (e.g. an Account's Contacts and Opportunities).
RELATED_FIRST = ["Contact", "Opportunity", "Case", "Task", "Event", "Quote", "OpportunityLineItem", "Order",
                 "Contract", "Asset", "CampaignMember", "Lead", "Account"]
RELATED_LIMIT = 50


def child_relationships(sf: SalesforceClient, name: str) -> list[dict]:
    """Related lists for an object: child objects that point at it and can be queried by this user."""
    desc = _describe(sf, name)
    g = _global(sf)
    out = []
    for r in desc.get("childRelationships") or []:
        child, fld, rel = r.get("childSObject"), r.get("field"), r.get("relationshipName")
        if not rel or not fld or child not in g or is_system(child) or r.get("deprecatedAndHidden"):
            continue
        out.append({"name": rel, "object": child, "field": fld, "label": g[child].get("labelPlural") or child})
    per_child: dict[str, int] = {}
    for o in out:
        per_child[o["object"]] = per_child.get(o["object"], 0) + 1
    primary = {f"{name}Id", "ParentId"}  # the standard link, e.g. Contact.AccountId for an Account
    for o in out:
        o["primary"] = o["field"] in primary
        if per_child[o["object"]] > 1 and not o["primary"]:  # extra links to the same child: say which link
            o["label"] = f"{o['label']} ({o['field'].removesuffix('__c').removesuffix('Id').replace('_', ' ')})"
    rank = {n: i for i, n in enumerate(RELATED_FIRST)}
    out.sort(key=lambda o: (rank.get(o["object"], 999), not o["primary"], o["label"].lower()))
    return out


def related_records(sf: SalesforceClient, name: str, record_id: str, relationship: str) -> dict:
    """Up to 50 records from one related list of one record, plus the total count."""
    if not _ID_RE.match(record_id):
        raise NotFound(record_id)
    rel = next((r for r in child_relationships(sf, name) if r["name"] == relationship), None)
    if rel is None:
        raise NotFound(relationship)
    child = rel["object"]
    cdesc = _describe(sf, child)
    cf = _fields(cdesc)
    link = cf.get(rel["field"])
    if not link or not link.get("filterable"):
        raise NotFound(relationship)
    cols = ["Id"] + [c for c in default_columns(cdesc) if c not in ("Id", rel["field"])][:5]
    refs = _ref_paths(cf, cols)
    where = f"WHERE {rel['field']} = '{record_id}'"  # field from describe, id checked by _ID_RE
    order = next((f" ORDER BY {f} DESC NULLS LAST" for f in ("LastModifiedDate", "CreatedDate") if f in cf and cf[f].get("sortable")), "")
    body = sf.query(f"SELECT {', '.join(cols + list(refs.values()))} FROM {child} {where}{order} LIMIT {RELATED_LIMIT}")
    total = sf.query(f"SELECT COUNT() FROM {child} {where}").get("totalSize")
    return {
        "relationship": relationship,
        "object": child,
        "label": rel["label"],
        "name_field": _name_field(cdesc),
        "columns": [{"name": c, "label": cf[c].get("label") or c, "type": cf[c]["type"]} for c in cols],
        "records": [_row(r, cols, refs) for r in body.get("records", [])],
        "total_size": total,
        "salesforce_url": f"{sf.base}/lightning/r/{quote(name)}/{record_id}/related/{quote(relationship)}/view",
    }


# ---------------------------------------------------------------- records

def _soql_text(value: str) -> str:
    """Escape user text for a LIKE '%…%' literal."""
    out = value.replace("\\", "\\\\").replace("'", "\\'").replace("%", "\\%").replace("_", "\\_")
    return out


_SEARCH_TYPES = {"string", "email", "phone", "url", "picklist", "combobox", "textarea"}
MAX_SEARCH_FIELDS = 60


def _search_fields(desc: dict) -> list[str]:
    """Text fields the search box looks in: the name first, then standard fields, then custom ones."""
    name = _name_field(desc)
    text = [f for f in desc.get("fields", []) if f.get("type") in _SEARCH_TYPES and f.get("filterable") and not f.get("encrypted")]
    text.sort(key=lambda f: (f["name"] != name, bool(f.get("custom"))))
    return [f["name"] for f in text][:MAX_SEARCH_FIELDS]


def _ref_paths(fields: dict[str, dict], cols: list[str]) -> dict[str, str]:
    """Map reference columns (e.g. OwnerId) to a related-name path (Owner.Name) where safe."""
    paths = {}
    for c in cols:
        f = fields[c]
        targets = f.get("referenceTo") or []
        if f["type"] == "reference" and f.get("relationshipName") and targets and all(t in _NAMED for t in targets):
            paths[c] = f"{f['relationshipName']}.Name"
    return paths


def _row(rec: dict, cols: list[str], refs: dict[str, str]) -> dict:
    values = {c: rec.get(c) for c in cols}
    names = {}
    for col, path in refs.items():
        rel = rec.get(path.split(".")[0])
        if isinstance(rel, dict) and rel.get("Name"):
            names[col] = rel["Name"]
    return {"id": rec.get("Id"), "values": values, "ref_names": names}


def list_records(
    sf: SalesforceClient,
    name: str,
    columns: list[str] | None,
    search: str | None,
    sort: str | None,
    direction: str,
    cursor: str | None,
    ids: list[str] | None = None,
    filters: list[dict] | None = None,
) -> dict:
    if ids is not None and (not ids or len(ids) > 200 or not all(_ID_RE.match(i) for i in ids)):
        raise ValueError("Invalid record ids.")
    desc = _describe(sf, name)
    fields = _fields(desc)
    cols = [c for c in (columns or default_columns(desc)) if c in fields and fields[c]["type"] not in _NO_COLUMN]
    if "Id" not in cols:
        cols.insert(0, "Id")
    cols = cols[:MAX_COLUMNS]
    refs = _ref_paths(fields, cols)

    if cursor:
        if not _CURSOR_RE.match(cursor):
            raise ValueError("Invalid page cursor.")
        body = sf.query_more(cursor, PAGE_SIZE)
    else:
        select = ", ".join(cols + list(refs.values()))
        soql = f"SELECT {select} FROM {name}"
        conds = _record_conditions(sf, name, desc, search, filters, ids)
        if conds:
            soql += " WHERE " + " AND ".join(conds)
        order = sort if sort in fields and fields[sort].get("sortable") else None
        if order is None:
            order = next((f for f in ("LastModifiedDate", "CreatedDate", "SystemModstamp") if f in fields), None)
            direction = "desc"
        if order:
            soql += f" ORDER BY {order} {'ASC' if direction == 'asc' else 'DESC'} NULLS LAST"
        body = sf.query_page(soql, PAGE_SIZE)

    next_url = body.get("nextRecordsUrl")
    return {
        "columns": cols,
        "records": [_row(r, cols, refs) for r in body.get("records", [])],
        "total_size": body.get("totalSize"),
        "next_cursor": next_url if next_url and _CURSOR_RE.match(next_url) else None,
    }


def _record_conditions(sf: SalesforceClient, name: str, desc: dict, search: str | None, filters: list[dict] | None,
                       ids: list[str] | None = None) -> list[str]:
    """WHERE conditions for the records list: filters, chosen ids and the search box."""
    conds = []
    if filters:
        from .finder import conditions  # finder imports this module

        children = {c["name"]: c for c in child_relationships(sf, name)}
        conds += conditions(_fields(desc), filters, children)
    if ids:
        conds.append("Id IN (" + ", ".join(f"'{i}'" for i in ids) + ")")  # ids checked by _ID_RE
    searched = _search_fields(desc) if search and search.strip() else []
    if searched:  # any text field: name, address, phone, email, picklists, custom text…
        text = _soql_text(search.strip()[:100])
        conds.append("(" + " OR ".join(f"{f} LIKE '%{text}%'" for f in searched) + ")")
    return conds


MAX_VALUES = 2000  # Salesforce returns at most 2,000 groups


def field_values(sf: SalesforceClient, name: str, field: str, search: str | None, filters: list[dict] | None,
                 base_where: str | None = None) -> dict:
    """The distinct values of one column and how many records have each (like Excel's filter list).

    Counts follow the search box and the other columns' filters, so the list shows what's left to pick from.
    `base_where` keeps it to a fixed set of records the health check chose (never user input).
    """
    desc = _describe(sf, name)
    fields = _fields(desc)
    f = fields.get(field)
    if not f or not f.get("groupable"):
        raise ValueError(f"You can’t list the values of {field}.")
    others = [x for x in (filters or []) if x.get("field") != field]
    conds = ([f"({base_where})"] if base_where else []) + _record_conditions(sf, name, desc, search, others)
    where = " WHERE " + " AND ".join(conds) if conds else ""
    rel = _ref_paths(fields, [field]).get(field)  # e.g. Owner.Name, to show names instead of ids
    select = f"{field} v" + (f", {rel} n" if rel else "")
    group = field + (f", {rel}" if rel else "")
    soql = f"SELECT {select}, COUNT(Id) c FROM {name}{where} GROUP BY {group} ORDER BY COUNT(Id) DESC LIMIT {MAX_VALUES}"
    rows = sf.query(soql).get("records", [])
    values, blanks = [], 0
    for r in rows:
        v, c = r.get("v"), int(r.get("c") or 0)
        if v is None or v == "":
            blanks += c
            continue
        values.append({"value": v, "label": str(r.get("n") or v), "count": c})
    values.sort(key=lambda x: x["label"].lower() if isinstance(x["value"], str) else x["value"])  # A→Z, or smallest first
    return {"field": field, "values": values, "blanks": blanks, "truncated": len(rows) >= MAX_VALUES}


def records_matching(sf: SalesforceClient, name: str, where: str | None, cursor: str | None = None, page_size: int = PAGE_SIZE,
                     columns: list[str] | None = None, order: str | None = None, filters: list[dict] | None = None) -> dict:
    """Records of `name` matching a filter the health check engine built (never user input).

    `columns` (shown first) and `order` come from the engine too; any the object doesn't have are skipped.
    `filters` are the person's column filters ({field, op, value}), checked and escaped like everywhere else.
    """
    desc = _describe(sf, name)
    fields = _fields(desc)
    descending = bool(order and order.startswith("-"))  # "-Amount" = biggest first
    order_field = (order or "").lstrip("-") or None
    by_account = order_field == "Account.Name" and "AccountId" in fields  # rows grouped by their Account (sorted_by AccountId)
    first = list(dict.fromkeys(c for c in (columns or []) if c in fields))  # each once: Salesforce refuses a field selected twice
    cols = (first + [c for c in default_columns(desc) if c not in first])[: max(8, len(first) + 2)]
    refs = _ref_paths(fields, cols)
    size = max(200, min(page_size, 2000))
    if cursor:
        if not _CURSOR_RE.match(cursor):
            raise ValueError("Invalid page cursor.")
        body = sf.query_more(cursor, size)
    else:
        if by_account:  # grouped by Account: A→Z by its name, then the records' own names
            sort = " ORDER BY Account.Name ASC NULLS LAST" + (", Name ASC" if "Name" in fields else "")
        elif order_field in fields and fields[order_field].get("sortable"):
            sort = f" ORDER BY {order_field} {'DESC' if descending else 'ASC'} NULLS LAST"
        else:
            latest = next((f for f in ("LastModifiedDate", "CreatedDate") if f in fields and fields[f].get("sortable")), None)
            sort = f" ORDER BY {latest} DESC" if latest else ""
        extra = _record_conditions(sf, name, desc, None, filters)
        conds = ([f"({where})" if extra else where] if where else []) + extra  # brackets only when combining
        soql = f"SELECT {', '.join(cols + list(refs.values()))} FROM {name}" + (f" WHERE {' AND '.join(conds)}" if conds else "") + sort
        body = sf.query_page(soql, size)
    next_url = body.get("nextRecordsUrl")
    return {
        "object": name,
        "columns": [{"name": c, "label": fields[c].get("label") or c, "type": fields[c]["type"]} for c in cols],
        "records": [_row(r, cols, refs) for r in body.get("records", [])],
        "total_size": body.get("totalSize"),
        "next_cursor": next_url if next_url and _CURSOR_RE.match(next_url) else None,
        "record_url_prefix": f"{sf.base}/",
        "sorted_by": "AccountId" if by_account else order_field if order_field in fields and fields[order_field].get("sortable") else None,
    }


def get_record(sf: SalesforceClient, name: str, record_id: str) -> dict:
    if not _ID_RE.match(record_id):
        raise NotFound(record_id)
    desc = _describe(sf, name)
    body = sf.get(f"{_api(sf)}/sobjects/{quote(name)}/{record_id}")
    values = {k: v for k, v in body.items() if k != "attributes"}
    fields = _fields(desc)
    refs = {c: p for c, p in _ref_paths(fields, [c for c in values if c in fields]).items()}
    names: dict[str, str] = {}
    if refs:
        # One small query for the related names (Owner, Account, …).
        soql = f"SELECT {', '.join(refs.values())} FROM {name} WHERE Id = '{record_id}'"  # id checked by _ID_RE
        try:
            res = sf.query(soql)
            rec = (res.get("records") or [{}])[0]
            names = _row(rec, [], refs)["ref_names"]
        except SalesforceError:
            names = {}
    return {
        "id": values.get("Id", record_id),
        "values": values,
        "ref_names": names,
        "salesforce_url": f"{sf.base}/{record_id}",
    }


def record_type_fields(sf: SalesforceClient, name: str) -> dict:
    """Each active record type of `name` and the fields on its page layout; fields on no record type's layout are "other".

    Salesforce ties fields to record types through page layouts (Setup → Record Type → Page Layout Assignment); the layout
    describe gives the one the connected user sees for each record type."""
    from ..engine.data_quality import _fillable, _own  # engine imports salesforce, so import here

    def layout_fields(rt_id: str) -> list[str]:
        body = sf.get(f"{_api(sf)}/sobjects/{quote(name)}/describe/layouts/{rt_id}")
        out: list[str] = []

        def walk(components: list[dict]) -> None:
            for c in components or []:
                if c.get("type") == "Field" and c.get("value"):
                    out.append(c["value"])
                walk(c.get("components") or [])  # parts of a compound field (an address's street, city…)

        for section in (body.get("detailLayoutSections") or []) + (body.get("editLayoutSections") or []):
            for row in section.get("layoutRows") or []:
                for item in row.get("layoutItems") or []:
                    walk(item.get("layoutComponents") or [])
        return list(dict.fromkeys(out))

    def load():
        desc = _describe(sf, name)
        fields = _fields(desc)
        types = [rt for rt in desc.get("recordTypeInfos") or [] if rt.get("active", True) and not rt.get("master")]
        record_types = []
        for rt in types:
            try:
                on = [f for f in layout_fields(rt["recordTypeId"]) if f in fields]
            except SalesforceError:
                continue  # a record type the connected user can't see
            record_types.append({"name": rt.get("name") or rt.get("developerName"), "id": rt["recordTypeId"], "fields": on})
        placed = {f for rt in record_types for f in rt["fields"]}
        # Each field's page in Setup: standard fields by name, custom ones by their id (Tooling API).
        setup = f"{sf.base}/lightning/setup/ObjectManager/{quote(name)}/FieldsAndRelationships"
        ids: dict[str, str] = {}
        try:
            soql = f"SELECT Id, DeveloperName, NamespacePrefix FROM CustomField WHERE TableEnumOrId = '{name}'"  # name: a described object
            for r in sf.get(f"{_api(sf)}/tooling/query?q={quote(soql)}").get("records", []):
                ns = f"{r['NamespacePrefix']}__" if r.get("NamespacePrefix") else ""
                ids[f"{ns}{r.get('DeveloperName')}__c"] = r.get("Id")
        except SalesforceError:
            ids = {}  # no Setup access: custom fields link to the field list instead
        links = {f: f"{setup}/{ids[f] if f in ids else f}/view" if (f in ids or not meta.get("custom")) else f"{setup}/view"
                 for f, meta in fields.items()}
        return {
            "setup_links": links,
            "record_types": record_types,
            "other": [f for f in fields if f not in placed] if record_types else [],
            "fillable": _fillable(fields),
            "own_custom": [f for f, meta in fields.items() if _own(meta)],
        }

    return _cached(("record-types", _org(sf), name), load)
