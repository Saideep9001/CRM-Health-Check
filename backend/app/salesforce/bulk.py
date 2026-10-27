"""Bulk API 2.0 record queries, returned in the same shape as a REST query so callers don't change.

A query job is created, waited on, and its CSV results read page by page (Sforce-Locator). CSV values are turned
back into what REST returns using the object's field types: booleans, numbers, None for blanks, and parent fields
("Owner.Name") as nested records ({"Owner": {"Name": …}}).

Bulk API 2.0 can't run aggregate queries (COUNT(), SUM(), GROUP BY), OFFSET, TYPEOF, subqueries or formatting
functions: those stay on REST (`eligible`). A job Salesforce refuses raises Unsupported, and the client falls back.
"""
import csv
import io
import logging
import re
import time
from typing import TYPE_CHECKING, Any

from .errors import SalesforceAuthExpired, SalesforceError

if TYPE_CHECKING:
    from .client import SalesforceClient

log = logging.getLogger("aquarient.salesforce")

CURSOR_RE = re.compile(r"^bulk:[A-Za-z0-9]{15,18}:[A-Za-z0-9_]{1,80}~[A-Za-z0-9_=+/-]{1,200}$")  # bulk:<job id>:<object>~<locator>
_NOT_BULK = re.compile(
    r"\b(COUNT|COUNT_DISTINCT|SUM|AVG|MIN|MAX|toLabel|FORMAT|convertCurrency|GROUPING)\s*\(|\bGROUP\s+BY\b|\bOFFSET\b|\bTYPEOF\b"
    r"|\(\s*SELECT\b|\bFOR\s+(VIEW|REFERENCE|UPDATE)\b",
    re.IGNORECASE,
)
_FROM = re.compile(r"\bFROM\s+([A-Za-z0-9_]+)", re.IGNORECASE)
_ORDER = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)
_DONE = {"JobComplete"}
_FAILED = {"Failed", "Aborted"}
_INT = {"int", "long"}
_FLOAT = {"double", "currency", "percent"}


class Unsupported(Exception):
    """Salesforce won't run this query as a Bulk job (unsupported object, field or clause)."""


def eligible(soql: str) -> bool:
    return not _NOT_BULK.search(soql)


def _jobs(sf: "SalesforceClient") -> str:
    return f"/services/data/{sf.settings.sf_api_version}/jobs/query"


def start(sf: "SalesforceClient", soql: str) -> dict:
    """Create the job and wait until its results are ready; the finished job's info."""
    try:
        job = sf.request("POST", _jobs(sf), json={"operation": "query", "query": soql, "contentType": "CSV",
                                                   "columnDelimiter": "COMMA", "lineEnding": "LF"}).json()
    except SalesforceAuthExpired:
        raise
    except SalesforceError as exc:
        if exc.status in (400, 404):  # a clause, field or object Bulk doesn't support
            raise Unsupported(str(exc)) from exc
        raise
    deadline = time.monotonic() + sf.settings.sf_bulk_timeout_seconds
    wait = 0.25
    while True:
        info = sf.request("GET", f"{_jobs(sf)}/{job['id']}").json()
        state = info.get("state")
        if state in _DONE:
            return info
        if state in _FAILED:
            raise Unsupported(info.get("errorMessage") or f"Bulk job {state.lower()}")
        if time.monotonic() > deadline:
            sf.request("PATCH", f"{_jobs(sf)}/{job['id']}", json={"state": "Aborted"}, ok_errors=True)
            raise SalesforceError("Salesforce took too long to prepare the records. Try again in a moment.", 504)
        sf._sleep(wait)
        wait = min(wait * 1.6, 3.0)


def page(sf: "SalesforceClient", soql_or_obj: str, job_id: str, locator: str | None, max_records: int | None) -> tuple[list[dict], str | None]:
    """One page of a finished job's results, as REST-style records; and the locator of the next page (None at the end)."""
    params = {k: v for k, v in (("maxRecords", max_records), ("locator", locator)) if v}
    resp = sf.request("GET", f"{_jobs(sf)}/{job_id}/results", params=params, accept="text/csv")
    nxt = resp.headers.get("Sforce-Locator")
    obj = _object(soql_or_obj)
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    return [_record(sf, obj, r) for r in rows], (nxt if nxt and nxt != "null" else None)


def query(sf: "SalesforceClient", soql: str, max_rows: int | None = None) -> dict:
    """All results (or the first `max_rows`) of one query, shaped like a finished REST query."""
    info = start(sf, soql)
    out: list[dict] = []
    locator = None
    while True:
        want = None if max_rows is None else max_rows - len(out)
        recs, locator = page(sf, soql, info["id"], locator, min(want, 50_000) if want else None)
        out += recs
        if not locator or (max_rows is not None and len(out) >= max_rows):
            break
    sf.request("DELETE", f"{_jobs(sf)}/{info['id']}", ok_errors=True)  # results read: tidy up (Salesforce would after 7 days)
    if not _ORDER.search(soql):  # Bulk gives no fixed order: sort by record id so every run reads the same way
        out.sort(key=lambda r: r.get("Id") or "")
    total = int(info.get("numberRecordsProcessed") or len(out))
    return {"totalSize": total, "done": True, "records": out[:max_rows] if max_rows is not None else out}


def first_page(sf: "SalesforceClient", soql: str, page_size: int) -> dict:
    """The first `page_size` results, and a cursor for the rest (for record tables)."""
    info = start(sf, soql)
    recs, locator = page(sf, soql, info["id"], None, page_size)
    obj = _object(soql)
    return {"totalSize": int(info.get("numberRecordsProcessed") or len(recs)), "done": not locator, "records": recs,
            "nextRecordsUrl": f"bulk:{info['id']}:{obj}~{locator}" if locator else None}


def next_page(sf: "SalesforceClient", cursor: str, page_size: int) -> dict:
    _, job_id, rest = cursor.split(":", 2)
    obj, locator = rest.split("~", 1)
    recs, nxt = page(sf, f"FROM {obj}", job_id, locator, page_size)
    return {"totalSize": None, "done": not nxt, "records": recs, "nextRecordsUrl": f"bulk:{job_id}:{obj}~{nxt}" if nxt else None}


# ---------------------------------------------------------------- CSV → REST-style records

def _object(soql: str) -> str:
    m = _FROM.search(soql)
    return m.group(1) if m else ""


def _describe(sf: "SalesforceClient", obj: str) -> dict:
    from . import explorer  # explorer imports the client, which imports this module
    try:
        return explorer._describe(sf, obj)
    except Exception:  # an object we can't describe: values stay text
        return {"fields": []}


def _field(sf: "SalesforceClient", obj: str, path: str) -> tuple[list[str], str | None]:
    """The canonical spelling of a column ("owner.name" → ["Owner", "Name"]) and its field type."""
    names, kind = [], None
    for n, part in enumerate(path.split(".")):
        fields = _describe(sf, obj).get("fields", []) if obj else []
        last = n == len(path.split(".")) - 1
        if last:
            f = next((f for f in fields if f["name"].lower() == part.lower()), None)
            names.append(f["name"] if f else part)
            kind = f.get("type") if f else None
        else:
            f = next((f for f in fields if (f.get("relationshipName") or "").lower() == part.lower()), None)
            names.append(f["relationshipName"] if f else part)
            obj = (f.get("referenceTo") or [""])[0] if f else ""
    return names, kind


_columns: dict[tuple[str, str, str], tuple[list[str], str | None]] = {}


def _record(sf: "SalesforceClient", obj: str, row: dict[str, str]) -> dict:
    rec: dict[str, Any] = {"attributes": {"type": obj}}
    for col, raw in row.items():
        key = (sf.conn.org_id or sf.base, obj, col)
        if key not in _columns:
            _columns[key] = _field(sf, obj, col)
        names, kind = _columns[key]
        value = _value(raw, kind)
        node = rec
        for parent in names[:-1]:  # Owner.Name → {"Owner": {"Name": …}}
            if not isinstance(node.get(parent), dict):
                node[parent] = {}
            node = node[parent]
        node[names[-1]] = value
    return _drop_empty_parents(rec)


def _drop_empty_parents(rec: dict) -> dict:
    """A parent with every value blank is a missing lookup: REST gives null for it."""
    for k, v in list(rec.items()):
        if isinstance(v, dict) and k != "attributes":
            v = _drop_empty_parents(v)
            rec[k] = v if any(x is not None for x in v.values()) else None
    return rec


def _value(raw: str | None, kind: str | None) -> Any:
    if raw is None or raw == "":
        return None
    try:
        if kind == "boolean":
            return raw.lower() == "true"
        if kind in _INT:
            return int(float(raw))
        if kind in _FLOAT:
            return float(raw)
    except ValueError:
        return raw
    return raw
