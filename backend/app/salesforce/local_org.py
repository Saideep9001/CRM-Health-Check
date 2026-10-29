"""Uploaded CRM data (CSV or Excel) as a "local org".

An upload is saved as a small SQLite file, one table per object (Account, Contact, Lead, Opportunity or any other name).
`LocalSalesforceClient` answers the same REST calls the checks make of Salesforce — describe from the file's columns,
SOQL translated to SQL over its rows — so every Area 1 and Area 2 check runs unchanged on uploaded data, with the same
rules and numbers. Things a spreadsheet can't hold (page layouts, flows, history, Setup) come back as "not supported",
which the checks already treat as "couldn't be checked".
"""

from __future__ import annotations

import csv
import io
import os
import re
import sqlite3
import threading
import uuid
import zipfile
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from xml.etree import ElementTree

import httpx

from ..config import DATA_DIR
from .client import SalesforceClient

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR") or DATA_DIR / "uploads")  # one SQLite file per upload
LOCAL_SCHEME = "local://"
MAX_ROWS = 200_000
MAX_COLUMNS = 500

# ---------------------------------------------------------------------------------------------------------------------
# The standard fields we recognise, per object: API name → (label, type, other headers that mean the same field)

_STD: dict[str, dict[str, tuple[str, str, tuple[str, ...]]]] = {
    "Account": {
        "Name": ("Account Name", "string", ("account", "company", "company name", "organization", "organisation", "name")),
        "AccountNumber": ("Account Number", "string", ()),
        "Website": ("Website", "url", ("web site", "url", "domain")),
        "Phone": ("Account Phone", "phone", ("phone", "phone number", "telephone", "main phone")),
        "Fax": ("Account Fax", "phone", ("fax",)),
        "Industry": ("Industry", "picklist", ()),
        "Type": ("Account Type", "picklist", ("type",)),
        "Rating": ("Account Rating", "picklist", ("rating",)),
        "Ownership": ("Ownership", "picklist", ()),
        "AnnualRevenue": ("Annual Revenue", "currency", ("revenue",)),
        "NumberOfEmployees": ("Employees", "int", ("number of employees", "employee count", "headcount")),
        "BillingStreet": ("Billing Street", "textarea", ("street", "address", "billing address")),
        "BillingCity": ("Billing City", "string", ("city",)),
        "BillingState": ("Billing State/Province", "string", ("state", "province", "billing state", "state/province", "region")),
        "BillingPostalCode": ("Billing Zip/Postal Code", "string", ("zip", "zip code", "postal code", "postcode", "billing zip", "billing postal code")),
        "BillingCountry": ("Billing Country", "string", ("country",)),
        "ShippingStreet": ("Shipping Street", "textarea", ()),
        "ShippingCity": ("Shipping City", "string", ()),
        "ShippingState": ("Shipping State/Province", "string", ("shipping state",)),
        "ShippingPostalCode": ("Shipping Zip/Postal Code", "string", ("shipping zip", "shipping postal code")),
        "ShippingCountry": ("Shipping Country", "string", ()),
        "Description": ("Account Description", "textarea", ("description", "notes")),
        "AccountSource": ("Account Source", "picklist", ("source", "lead source")),
    },
    "Contact": {
        "FirstName": ("First Name", "string", ("first", "given name")),
        "LastName": ("Last Name", "string", ("last", "surname", "family name")),
        "Name": ("Full Name", "string", ("name", "contact name", "contact")),
        "AccountId": ("Account Name", "reference", ("account", "company", "company name", "organization", "organisation")),
        "Title": ("Title", "string", ("job title", "position", "role")),
        "Department": ("Department", "string", ()),
        "Email": ("Email", "email", ("email address", "e-mail", "work email")),
        "Phone": ("Business Phone", "phone", ("phone", "phone number", "telephone", "work phone")),
        "MobilePhone": ("Mobile Phone", "phone", ("mobile", "cell", "cell phone")),
        "MailingStreet": ("Mailing Street", "textarea", ("street", "address", "mailing address")),
        "MailingCity": ("Mailing City", "string", ("city",)),
        "MailingState": ("Mailing State/Province", "string", ("state", "province", "mailing state", "state/province", "region")),
        "MailingPostalCode": ("Mailing Zip/Postal Code", "string", ("zip", "zip code", "postal code", "postcode", "mailing zip", "mailing postal code")),
        "MailingCountry": ("Mailing Country", "string", ("country",)),
        "LeadSource": ("Lead Source", "picklist", ("source",)),
        "Birthdate": ("Birthdate", "date", ("birthday", "date of birth")),
        "Description": ("Description", "textarea", ("notes",)),
    },
    "Lead": {
        "FirstName": ("First Name", "string", ("first", "given name")),
        "LastName": ("Last Name", "string", ("last", "surname", "family name")),
        "Name": ("Full Name", "string", ("name", "lead name", "lead")),
        "Company": ("Company", "string", ("company name", "account", "account name", "organization", "organisation")),
        "Title": ("Title", "string", ("job title", "position", "role")),
        "Email": ("Email", "email", ("email address", "e-mail", "work email")),
        "Phone": ("Phone", "phone", ("phone number", "telephone", "work phone")),
        "MobilePhone": ("Mobile Phone", "phone", ("mobile", "cell", "cell phone")),
        "Website": ("Website", "url", ("web site", "url", "domain")),
        "Status": ("Lead Status", "picklist", ("status", "stage")),
        "LeadSource": ("Lead Source", "picklist", ("source",)),
        "Industry": ("Industry", "picklist", ()),
        "Rating": ("Rating", "picklist", ()),
        "AnnualRevenue": ("Annual Revenue", "currency", ("revenue",)),
        "NumberOfEmployees": ("No. of Employees", "int", ("employees", "number of employees", "employee count", "headcount")),
        "Street": ("Street", "textarea", ("address",)),
        "City": ("City", "string", ()),
        "State": ("State/Province", "string", ("province", "region")),
        "PostalCode": ("Zip/Postal Code", "string", ("zip", "zip code", "postal code", "postcode")),
        "Country": ("Country", "string", ()),
        "IsConverted": ("Converted", "boolean", ("is converted",)),
        "Description": ("Description", "textarea", ("notes",)),
    },
    "Opportunity": {
        "Name": ("Opportunity Name", "string", ("opportunity", "deal", "deal name", "name")),
        "AccountId": ("Account Name", "reference", ("account", "company", "company name", "customer")),
        "Amount": ("Amount", "currency", ("value", "deal value", "deal amount", "opportunity amount")),
        "CloseDate": ("Close Date", "date", ("expected close date", "close", "closing date")),
        "StageName": ("Stage", "picklist", ("stage name", "status", "deal stage")),
        "Probability": ("Probability (%)", "percent", ("probability",)),
        "Type": ("Type", "picklist", ("opportunity type", "deal type")),
        "LeadSource": ("Lead Source", "picklist", ("source",)),
        "NextStep": ("Next Step", "string", ("next action", "next steps")),
        "ForecastCategoryName": ("Forecast Category", "picklist", ()),
        "IsClosed": ("Closed", "boolean", ("is closed",)),
        "IsWon": ("Won", "boolean", ("is won",)),
        "Description": ("Description", "textarea", ("notes",)),
    },
}
# On every object: the record's id and dates, filled from the file when it has them.
_COMMON = {
    "Id": ("Record ID", "id", ("id", "record id", "record id#", "sfdc id", "salesforce id")),
    "CreatedDate": ("Created Date", "datetime", ("created", "created on", "date created", "created at")),
    "LastModifiedDate": ("Last Modified Date", "datetime", ("last modified", "modified", "updated", "updated at", "last updated")),
    "LastActivityDate": ("Last Activity", "date", ("last activity date", "last activity on", "last contacted")),
}
_PREFIX = {"Account": "001", "Contact": "003", "Lead": "00Q", "Opportunity": "006"}
_PLURAL = {"Account": "Accounts", "Contact": "Contacts", "Lead": "Leads", "Opportunity": "Opportunities"}
_READ_ONLY = {"Id", "CreatedDate", "LastModifiedDate", "LastActivityDate", "IsClosed", "IsWon", "IsConverted"}
STANDARD_OBJECTS = tuple(_STD)


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def standard_fields(obj: str) -> dict[str, tuple[str, str, tuple[str, ...]]]:
    return {**_COMMON, **_STD.get(obj, {"Name": ("Name", "string", ("name",))})}


def suggest_mapping(obj: str, headers: list[str]) -> dict[str, str | None]:
    """Header → API name for the headers that match a standard field (by API name, label or a usual alternative);
    None for the rest, which become custom fields."""
    std = standard_fields(obj)
    exact = {_key(api): api for api in std}
    by_label = {_key(label): api for api, (label, _, _) in std.items()}
    alt = {_key(a): api for api, (_, _, alts) in std.items() for a in alts}
    out: dict[str, str | None] = {}
    used: set[str] = set()
    for pass_ in (exact, by_label, alt):  # the closest match first, so "Billing City" isn't taken by "City"
        for h in headers:
            if h in out:
                continue
            api = pass_.get(_key(h)) or pass_.get(_key(re.sub(r"__c$", "", h)))
            if api and api not in used:
                out[h], _ = api, used.add(api)
    return {h: out.get(h) for h in headers}


def custom_name(header: str, taken: set[str]) -> str:
    base = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]+", "_", header)).strip("_") or "Field"
    if base[0].isdigit():
        base = f"X{base}"
    base = base[:36]
    name, n = f"{base}__c", 2
    while name.lower() in taken:
        name, n = f"{base}{n}__c", n + 1
    taken.add(name.lower())
    return name


# ---------------------------------------------------------------------------------------------------------------------
# Reading files


class UploadError(ValueError):
    """A file we can't read, with a message for the user."""


def read_table(filename: str, data: bytes) -> tuple[list[str], list[list[str]]]:
    """Headers and rows (as text) from a CSV or .xlsx file."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        rows = _read_xlsx(data)
    elif name.endswith(".xls"):
        raise UploadError("Old .xls files can’t be read. In Excel, choose File → Save As → Excel Workbook (.xlsx) or CSV, then upload that.")
    elif name.endswith((".csv", ".txt", ".tsv")):
        rows = _read_csv(data)
    else:
        raise UploadError("Upload a CSV file (.csv) or an Excel workbook (.xlsx).")
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise UploadError("The file is empty.")
    headers = [h.strip() for h in rows[0]]
    while headers and not headers[-1]:
        headers.pop()
    if not headers:
        raise UploadError("The first row should hold the column names.")
    if len(headers) > MAX_COLUMNS:
        raise UploadError(f"The file has {len(headers)} columns; up to {MAX_COLUMNS} can be checked.")
    seen: dict[str, int] = {}
    for i, h in enumerate(headers):
        h = h or f"Column {i + 1}"
        seen[h] = seen.get(h, 0) + 1
        headers[i] = h if seen[h] == 1 else f"{h} ({seen[h]})"
    body = [(r + [""] * len(headers))[: len(headers)] for r in rows[1:]]
    if len(body) > MAX_ROWS:
        raise UploadError(f"The file has {len(body):,} rows; up to {MAX_ROWS:,} can be checked at once. Split it into smaller files.")
    return headers, body


def _read_csv(data: bytes) -> list[list[str]]:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:20_000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [list(r) for r in csv.reader(io.StringIO(text), dialect)]


_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_DATE_FORMATS = {14, 15, 16, 17, 22, 27, 30, 36, 45, 46, 47, 50, 57}


def _read_xlsx(data: bytes) -> list[list[str]]:
    """The first worksheet of an .xlsx file, read with the standard library (an .xlsx is a zip of XML files)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UploadError("That doesn’t look like an Excel workbook (.xlsx).") from exc
    names = set(z.namelist())
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for si in ElementTree.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
    date_styles: set[int] = set()
    if "xl/styles.xml" in names:
        st = ElementTree.fromstring(z.read("xl/styles.xml"))
        custom = {int(n.get("numFmtId")): n.get("formatCode", "") for n in st.findall("m:numFmts/m:numFmt", _NS)}
        for i, xf in enumerate(st.findall("m:cellXfs/m:xf", _NS)):
            fid = int(xf.get("numFmtId", 0))
            code = re.sub(r'"[^"]*"|\[[^\]]*\]', "", custom.get(fid, "")).lower()
            if fid in _DATE_FORMATS or (fid in custom and re.search(r"[dy]", code) and "general" not in code):
                date_styles.add(i)
    sheet = "xl/worksheets/sheet1.xml"
    if "xl/workbook.xml" in names and "xl/_rels/workbook.xml.rels" in names:  # the first sheet in tab order
        wb = ElementTree.fromstring(z.read("xl/workbook.xml"))
        first = wb.find("m:sheets/m:sheet", _NS)
        rels = {r.get("Id"): r.get("Target") for r in ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        target = rels.get(first.get(_REL)) if first is not None else None
        if target:
            sheet = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
    if sheet not in names:
        raise UploadError("The workbook has no worksheet to read.")
    rows: list[list[str]] = []
    for row in ElementTree.fromstring(z.read(sheet)).iterfind("m:sheetData/m:row", _NS):
        out: list[str] = []
        for c in row.findall("m:c", _NS):
            ref = c.get("r", "")
            col = _col_index(ref) if ref else len(out)
            while len(out) < col:
                out.append("")
            t, v = c.get("t"), c.find("m:v", _NS)
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{_NS['m']}}}t"))
            elif t == "b" and v is not None:
                val = "true" if v.text == "1" else "false"
            elif v is not None and v.text is not None:
                val = v.text
                if int(c.get("s", 0)) in date_styles and t not in ("str", "e"):
                    val = _excel_date(val)
                elif re.fullmatch(r"-?\d+\.0", val):
                    val = val[:-2]
            else:
                val = ""
            out.append(val)
        rows.append(out)
    return rows


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def _excel_date(serial: str) -> str:
    try:
        d = datetime(1899, 12, 30) + timedelta(days=float(serial))
    except (ValueError, OverflowError):
        return serial
    return d.strftime("%Y-%m-%d") if d.hour == d.minute == d.second == 0 else d.strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------------------------------------------------
# Values: types worked out from the column, and text turned into what Salesforce would store

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URL = re.compile(r"^(https?://|www\.)\S+$|^[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?$", re.I)
_PHONE = re.compile(r"^\+?[\d\s().\-/]{7,}(\s*(x|ext\.?)\s*\d+)?$", re.I)
_TRUE, _FALSE = {"true", "yes", "y", "1", "t", "x", "checked"}, {"false", "no", "n", "0", "f", "", "unchecked"}


def _number(v: str) -> float | None:
    s = re.sub(r"[\s,$€£¥]", "", v)
    if s.endswith("%"):
        s = s[:-1]
    if re.fullmatch(r"\(\d+(\.\d+)?\)", s):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


_DATE_PATTERNS = [
    (re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})?$"), "ymd"),
    (re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})(?:[ T,]+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])?)?$"), "mdy"),
]


def _date(v: str, day_first: bool = False) -> tuple[str, bool] | None:
    """('YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS', has a time) or None."""
    s = v.strip()
    for rx, kind in _DATE_PATTERNS:
        m = rx.match(s)
        if not m:
            continue
        g = m.groups()
        if kind == "ymd":
            y, mo, d, hh, mi, ss = int(g[0]), int(g[1]), int(g[2]), g[3], g[4], g[5]
        else:
            a, b, y = int(g[0]), int(g[1]), int(g[2])
            y += 2000 if y < 100 else 0
            mo, d = (b, a) if day_first or a > 12 else (a, b)
            hh, mi, ss = g[3], g[4], g[5]
            if hh and g[6]:
                hh = str(int(hh) % 12 + (12 if g[6].lower() == "pm" else 0))
        try:
            dt = datetime(y, mo, d, int(hh or 0), int(mi or 0), int(ss or 0))
        except ValueError:
            return None
        return (dt.strftime("%Y-%m-%dT%H:%M:%S"), True) if hh else (dt.strftime("%Y-%m-%d"), False)
    return None


def infer_type(values: list[str]) -> str:
    """The Salesforce field type a column of text most likely is."""
    vals = [v.strip() for v in values if v and v.strip()]
    if not vals:
        return "string"
    low = {v.lower() for v in vals}
    if low <= (_TRUE | _FALSE) and len(low) <= 2 and not low <= {"0", "1"} or low <= {"true", "false"}:
        return "boolean"
    if all(_EMAIL.match(v) for v in vals):
        return "email"
    nums = [_number(v) for v in vals]
    if all(n is not None for n in nums):
        if any(v.endswith("%") for v in vals):
            return "percent"
        if any(re.search(r"[$€£¥]", v) for v in vals):
            return "currency"
        if all(re.fullmatch(r"-?[\d,]+", v) for v in vals) and not any(len(re.sub(r"\D", "", v)) >= 9 for v in vals):
            return "int"
        if not any(len(re.sub(r"\D", "", v)) >= 9 and not re.search(r"[.,]\d{1,2}$", v) for v in vals):
            return "double"
    day_first = any((m := re.match(r"^(\d{1,2})[/.-]", v)) and int(m[1]) > 12 for v in vals)
    dates = [_date(v, day_first) for v in vals]
    if all(dates):
        return "datetime" if any(d[1] for d in dates) else "date"
    if all(_URL.match(v) for v in vals) and not all(_PHONE.match(v) for v in vals):
        return "url"
    if all(_PHONE.match(v) and 7 <= len(re.sub(r"\D", "", v)) <= 15 for v in vals):
        return "phone"
    longest = max(len(v) for v in vals)
    if longest > 255:
        return "textarea"
    distinct = len(low)
    if len(vals) >= 20 and distinct <= 30 and distinct / len(vals) <= 0.2 and longest <= 40:
        return "picklist"
    return "string"


def convert(v: str, ftype: str, day_first: bool = False):
    """A cell as Salesforce would store it in a field of this type; text that doesn't fit is kept as typed."""
    s = (v or "").strip()
    if not s:
        return False if ftype == "boolean" else None
    if ftype == "boolean":
        return 1 if s.lower() in _TRUE else 0
    if ftype in ("int", "double", "currency", "percent"):
        n = _number(s)
        return s if n is None else (int(n) if ftype == "int" and n.is_integer() else n)
    if ftype in ("date", "datetime"):
        d = _date(s, day_first)
        if not d:
            return s
        return d[0][:10] if ftype == "date" else (d[0] if d[1] else f"{d[0]}T00:00:00")
    return s


# ---------------------------------------------------------------------------------------------------------------------
# Datasets: one SQLite file per upload


def _path(dataset: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", dataset):
        raise UploadError("Unknown upload.")
    return UPLOAD_DIR / f"{dataset}.db"


def new_dataset() -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ds = uuid.uuid4().hex
    with sqlite3.connect(_path(ds)) as db:
        db.execute("CREATE TABLE _fields (object TEXT, name TEXT, label TEXT, type TEXT, custom INTEGER, source TEXT, position INTEGER)")
        db.execute("CREATE TABLE _objects (name TEXT PRIMARY KEY, label TEXT, plural TEXT, filename TEXT, rows INTEGER, loaded_at TEXT)")
        db.execute("CREATE TABLE _names (id TEXT PRIMARY KEY, name TEXT)")
    return ds


def delete_dataset(dataset: str) -> None:
    _CACHE.drop(dataset)
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(f"{_path(dataset)}{suffix}").unlink(missing_ok=True)


def _connect(dataset: str) -> sqlite3.Connection:
    p = _path(dataset)
    if not p.exists():
        raise UploadError("This upload no longer exists. Upload the file again.")
    db = sqlite3.connect(p, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def load_object(dataset: str, obj: str, filename: str, headers: list[str], rows: list[list[str]],
                mapping: dict[str, str | None]) -> int:
    """Replace `obj`'s table with the file's rows. `mapping` is header → API name (None or "" = keep as a custom field,
    "-" = leave the column out). Returns the number of records loaded."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", obj):
        raise UploadError("Object names use letters, numbers and underscores, e.g. Account or Invoice__c.")
    std = standard_fields(obj)
    taken = {a.lower() for a in std}
    cols: list[tuple[int, str, str, str, bool]] = []  # (header index, api name, label, type, custom)
    used: set[str] = set()
    for i, h in enumerate(headers):
        target = mapping.get(h)
        if target == "-":
            continue
        if target and target in std and target not in used:
            label, ftype, _ = std[target]
            used.add(target)
            cols.append((i, target, label, ftype, False))
        else:
            cols.append((i, custom_name(h, taken), h, infer_type([r[i] for r in rows]), True))
    if not cols:
        raise UploadError("Choose at least one column to check.")

    day_first = {}
    for i, api, _, ftype, _ in cols:
        if ftype in ("date", "datetime"):
            day_first[i] = any((m := re.match(r"^\s*(\d{1,2})[/.-]", r[i] or "")) and int(m[1]) > 12 for r in rows)

    db = _connect(dataset)
    try:
        db.execute(f"DROP TABLE IF EXISTS {_ident(obj)}")
        db.execute("DELETE FROM _fields WHERE object = ?", (obj,))
        apis = [c[1] for c in cols]
        extra: list[tuple[str, str, str]] = []  # fields worked out, not in the file
        if "Id" not in apis:
            extra.append(("Id", "Record ID", "id"))
        if obj in ("Contact", "Lead"):
            if "Name" not in apis and ("FirstName" in apis or "LastName" in apis):
                extra.append(("Name", "Full Name", "string"))
            if "Name" in apis and "LastName" not in apis:
                extra += [("FirstName", "First Name", "string"), ("LastName", "Last Name", "string")]
        if obj == "Lead" and "IsConverted" not in apis:
            extra.append(("IsConverted", "Converted", "boolean"))
        if obj == "Opportunity" and "StageName" in apis:
            extra += [(f, label, "boolean") for f, label in (("IsClosed", "Closed"), ("IsWon", "Won")) if f not in apis]
        coldefs = [f"{_ident(api)} {'TEXT COLLATE NOCASE' if t not in ('int', 'double', 'currency', 'percent', 'boolean') else 'NUMERIC'}"
                   for api, t in [(c[1], c[3]) for c in cols] + [(e[0], e[2]) for e in extra]]
        db.execute(f"CREATE TABLE {_ident(obj)} ({', '.join(coldefs)})")
        names: dict[str, str] = {}  # Account Name → its id, for AccountId columns that hold names
        if any(c[1] == "AccountId" for c in cols):
            if obj != "Account" and db.execute("SELECT 1 FROM _objects WHERE name = 'Account'").fetchone():
                for r in db.execute('SELECT "Id", "Name" FROM "Account" WHERE "Name" IS NOT NULL ORDER BY rowid'):
                    names.setdefault(r[1].lower(), r[0])  # the first Account with that name
        prefix = _PREFIX.get(obj, "a0U")
        out_rows = []
        for n, r in enumerate(rows, 1):
            rec: dict[str, object] = {}
            for i, api, _, ftype, _ in cols:
                if ftype == "reference":
                    raw = (r[i] or "").strip()
                    if not raw:
                        rec[api] = None
                    elif re.fullmatch(r"[a-zA-Z0-9]{15}([a-zA-Z0-9]{3})?", raw) and not raw.isalpha():
                        rec[api] = raw
                    else:  # a name: the uploaded Account with that name, else a stand-in id that remembers the name
                        rid = names.get(raw.lower()) or f"001UPN{uuid.uuid5(uuid.NAMESPACE_OID, raw.lower()).hex[:12].upper()}"
                        db.execute("INSERT OR IGNORE INTO _names (id, name) VALUES (?, ?)", (rid, raw))
                        rec[api] = rid
                else:
                    rec[api] = convert(r[i], ftype, day_first.get(i, False))
            if "Id" not in apis or not rec.get("Id"):
                rec["Id"] = f"{prefix}UPL{n:012d}"
            if obj in ("Contact", "Lead"):
                first, last, full = rec.get("FirstName"), rec.get("LastName"), rec.get("Name")
                if "Name" not in apis and ("FirstName" in apis or "LastName" in apis):
                    rec["Name"] = " ".join(str(x) for x in (first, last) if x) or None
                if "Name" in apis and "LastName" not in apis and full:
                    parts = str(full).rsplit(" ", 1)
                    rec["FirstName"], rec["LastName"] = (parts[0], parts[1]) if len(parts) == 2 else (None, parts[0])
            if obj == "Lead" and "IsConverted" not in apis:
                rec["IsConverted"] = 1 if re.search(r"convert", str(rec.get("Status") or ""), re.I) else 0
            if obj == "Opportunity" and "StageName" in apis:
                stage = str(rec.get("StageName") or "")
                closed = bool(re.search(r"closed|won|lost", stage, re.I))
                rec.setdefault("IsClosed", 1 if closed else 0)
                rec.setdefault("IsWon", 1 if re.search(r"\bwon\b", stage, re.I) else 0)
            out_rows.append(rec)
        all_cols = [c[1] for c in cols] + [e[0] for e in extra]
        db.executemany(f"INSERT INTO {_ident(obj)} ({', '.join(map(_ident, all_cols))}) VALUES ({', '.join('?' * len(all_cols))})",
                       [[rec.get(c) for c in all_cols] for rec in out_rows])
        db.execute(f"CREATE INDEX {_ident('ix_' + obj + '_id')} ON {_ident(obj)} (\"Id\")")
        fields = [(obj, api, label, ftype, int(custom), headers[i], pos) for pos, (i, api, label, ftype, custom) in enumerate(cols)]
        fields += [(obj, api, label, ftype, 0, None, len(cols) + k) for k, (api, label, ftype) in enumerate(extra)]
        db.executemany("INSERT INTO _fields VALUES (?, ?, ?, ?, ?, ?, ?)", fields)
        label = obj.removesuffix("__c").replace("_", " ")
        plural = _PLURAL.get(obj) or (label if label.endswith("s") else f"{label}s")
        db.execute("INSERT OR REPLACE INTO _objects VALUES (?, ?, ?, ?, ?, ?)",
                   (obj, label, plural, filename, len(out_rows), datetime.now(timezone.utc).isoformat()))
        if obj == "Account":  # Contacts/Opportunities loaded earlier with account names now point at these Accounts
            match = 'SELECT a."Id" FROM "Account" a JOIN _names n ON lower(a."Name") = lower(n.name) WHERE n.id = {t}."AccountId"'
            for child in ("Contact", "Opportunity"):
                if db.execute("SELECT 1 FROM _objects WHERE name = ?", (child,)).fetchone() and _has_col(db, child, "AccountId"):
                    t = _ident(child)
                    db.execute(f'UPDATE {t} SET "AccountId" = ({match.format(t=t)} LIMIT 1) '
                               f"WHERE \"AccountId\" LIKE '001UPN%' AND EXISTS ({match.format(t=t)})")
        db.commit()
    finally:
        db.close()
    _CACHE.drop(dataset)
    return len(out_rows)


def _has_col(db: sqlite3.Connection, table: str, col: str) -> bool:
    return any(r[1] == col for r in db.execute(f"PRAGMA table_info({_ident(table)})"))


def remove_object(dataset: str, obj: str) -> None:
    db = _connect(dataset)
    try:
        db.execute(f"DROP TABLE IF EXISTS {_ident(obj)}")
        db.execute("DELETE FROM _fields WHERE object = ?", (obj,))
        db.execute("DELETE FROM _objects WHERE name = ?", (obj,))
        db.commit()
    finally:
        db.close()
    _CACHE.drop(dataset)


def objects(dataset: str) -> list[dict]:
    db = _connect(dataset)
    try:
        return [dict(r) for r in db.execute("SELECT name, label, plural, filename, rows, loaded_at FROM _objects ORDER BY name")]
    finally:
        db.close()


# ---------------------------------------------------------------------------------------------------------------------
# Describe: Salesforce-shaped metadata from the stored columns


class _Meta:
    def __init__(self, dataset: str):
        db = _connect(dataset)
        try:
            self.objects = {r["name"]: dict(r) for r in db.execute("SELECT * FROM _objects")}
            self.fields: dict[str, dict[str, dict]] = {o: {} for o in self.objects}
            for r in db.execute("SELECT * FROM _fields ORDER BY object, position"):
                if r["object"] in self.fields:
                    self.fields[r["object"]][r["name"]] = dict(r)
            self.picklists: dict[tuple[str, str], list[str]] = {}
            for o, fs in self.fields.items():
                for f in fs.values():
                    if f["type"] == "picklist":
                        vals = [v[0] for v in db.execute(f"SELECT DISTINCT {_ident(f['name'])} FROM {_ident(o)} WHERE {_ident(f['name'])} IS NOT NULL LIMIT 200")]
                        self.picklists[(o, f["name"])] = sorted(str(v) for v in vals)
        finally:
            db.close()

    def describe(self, obj: str) -> dict:
        info = self.objects[obj]
        out = []
        for f in self.fields[obj].values():
            name, ftype = f["name"], f["type"]
            d = {
                "name": name, "label": f["label"], "type": ftype, "custom": bool(f["custom"]),
                "nillable": name != "Id", "createable": name not in _READ_ONLY, "updateable": name not in _READ_ONLY,
                "defaultedOnCreate": name in ("Id", "CreatedDate", "LastModifiedDate", "IsConverted"),
                "calculated": False, "autoNumber": False, "filterable": True, "sortable": ftype != "textarea",
                "groupable": ftype not in ("textarea", "double", "currency", "percent", "datetime"),
                "nameField": name == "Name", "idLookup": name == "Id", "externalId": False, "unique": False,
                "length": 255 if ftype in ("string", "phone", "url", "email", "picklist") else (32000 if ftype == "textarea" else 0),
                "inlineHelpText": None, "picklistValues": [], "referenceTo": [], "relationshipName": None,
            }
            if ftype == "picklist":
                d["picklistValues"] = [{"value": v, "label": v, "active": True, "defaultValue": False} for v in self.picklists.get((obj, name), [])]
            if ftype == "reference":
                target = "Account" if name == "AccountId" else name.removesuffix("Id")
                d["referenceTo"], d["relationshipName"] = [target], target
            out.append(d)
        children = [{"childSObject": c, "field": "AccountId", "relationshipName": _PLURAL.get(c, c + "s"), "cascadeDelete": False}
                    for c, fs in self.fields.items() if obj == "Account" and "AccountId" in fs]
        return {"name": obj, "label": info["label"], "labelPlural": info["plural"], "custom": obj.endswith("__c"),
                "keyPrefix": _PREFIX.get(obj, "a0U"), "queryable": True, "retrieveable": True, "searchable": True,
                "createable": False, "updateable": False, "fields": out, "childRelationships": children, "recordTypeInfos": [],
                # the file's own columns, in its order: Your Data shows them all, like the spreadsheet
                "uploadColumns": [f["name"] for f in self.fields[obj].values() if f["source"] is not None]}

    def sobjects(self) -> list[dict]:
        return [{"name": o, "label": i["label"], "labelPlural": i["plural"], "custom": o.endswith("__c"), "keyPrefix": _PREFIX.get(o, "a0U"),
                 "queryable": True, "retrieveable": True, "searchable": True, "createable": False, "updateable": False,
                 "layoutable": True, "triggerable": False} for o, i in self.objects.items()]


class _MetaCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._items: dict[str, _Meta] = {}

    def get(self, dataset: str) -> _Meta:
        with self._lock:
            if dataset not in self._items:
                self._items[dataset] = _Meta(dataset)
            return self._items[dataset]

    def drop(self, dataset: str) -> None:
        with self._lock:
            self._items.pop(dataset, None)
            for k in [k for k in _PAGES if k.startswith(dataset)]:
                _PAGES.pop(k, None)


_CACHE = _MetaCache()
_PAGES: OrderedDict[str, tuple[str, list[dict], int]] = OrderedDict()  # cursor key → (object, records, total)

# ---------------------------------------------------------------------------------------------------------------------
# SOQL → SQLite


class SOQLError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


_TOKEN = re.compile(r"""\s*(?:
    (?P<str>'(?:\\.|[^'\\])*')
  | (?P<dt>\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?)(?![\w.])
  | (?P<num>-?\d+(?:\.\d+)?)
  | (?P<dlit>[A-Z_]+_N_[A-Z_]+:\d+|N_[A-Z_]+_AGO:\d+)
  | (?P<id>[A-Za-z_][\w.]*)
  | (?P<op>!=|<>|<=|>=|=|<|>)
  | (?P<p>[(),])
)""", re.X)
_KEYWORDS = {"select", "from", "where", "and", "or", "not", "in", "like", "group", "by", "having", "order", "asc", "desc",
             "nulls", "first", "last", "limit", "offset", "includes", "excludes", "with", "rollup", "cube"}
_AGG = {"count", "sum", "max", "min", "avg", "count_distinct"}
_NAMED_DATES = {"YESTERDAY", "TODAY", "TOMORROW", "LAST_WEEK", "THIS_WEEK", "NEXT_WEEK", "LAST_MONTH", "THIS_MONTH",
                "NEXT_MONTH", "LAST_90_DAYS", "NEXT_90_DAYS", "THIS_QUARTER", "LAST_QUARTER", "NEXT_QUARTER",
                "THIS_YEAR", "LAST_YEAR", "NEXT_YEAR"}


def _tokens(soql: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    s = soql.strip()
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if not m or m.end() == pos:
            if s[pos:].strip() == "":
                break
            raise SOQLError("MALFORMED_QUERY", f"Unexpected text near “{s[pos:pos + 20]}”.")
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        pos = m.end()
    return out


def _quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def _date_range(lit: str, today: date | None = None) -> tuple[date, date]:
    """[start, end) of a SOQL date literal."""
    t = today or datetime.now(timezone.utc).date()
    name, _, num = lit.partition(":")
    n = int(num) if num else 0
    month, quarter = date(t.year, t.month, 1), _quarter_start(t)
    week = t - timedelta(days=(t.weekday() + 1) % 7)  # Salesforce weeks start on Sunday
    ranges = {
        "TODAY": (t, t + timedelta(1)), "YESTERDAY": (t - timedelta(1), t), "TOMORROW": (t + timedelta(1), t + timedelta(2)),
        "THIS_WEEK": (week, week + timedelta(7)), "LAST_WEEK": (week - timedelta(7), week), "NEXT_WEEK": (week + timedelta(7), week + timedelta(14)),
        "THIS_MONTH": (month, _add_months(month, 1)), "LAST_MONTH": (_add_months(month, -1), month), "NEXT_MONTH": (_add_months(month, 1), _add_months(month, 2)),
        "THIS_QUARTER": (quarter, _add_months(quarter, 3)), "LAST_QUARTER": (_add_months(quarter, -3), quarter),
        "NEXT_QUARTER": (_add_months(quarter, 3), _add_months(quarter, 6)),
        "THIS_YEAR": (date(t.year, 1, 1), date(t.year + 1, 1, 1)), "LAST_YEAR": (date(t.year - 1, 1, 1), date(t.year, 1, 1)),
        "NEXT_YEAR": (date(t.year + 1, 1, 1), date(t.year + 2, 1, 1)),
        "LAST_90_DAYS": (t - timedelta(90), t + timedelta(1)), "NEXT_90_DAYS": (t + timedelta(1), t + timedelta(91)),
        "LAST_N_DAYS": (t - timedelta(n), t + timedelta(1)), "NEXT_N_DAYS": (t + timedelta(1), t + timedelta(n + 1)),
        "N_DAYS_AGO": (t - timedelta(n), t - timedelta(n - 1)),
        "LAST_N_WEEKS": (week - timedelta(7 * n), week), "NEXT_N_WEEKS": (week + timedelta(7), week + timedelta(7 * (n + 1))),
        "LAST_N_MONTHS": (_add_months(month, -n), month), "NEXT_N_MONTHS": (_add_months(month, 1), _add_months(month, n + 1)),
        "LAST_N_QUARTERS": (_add_months(quarter, -3 * n), quarter), "NEXT_N_QUARTERS": (_add_months(quarter, 3), _add_months(quarter, 3 * (n + 1))),
        "LAST_N_YEARS": (date(t.year - n, 1, 1), date(t.year, 1, 1)), "NEXT_N_YEARS": (date(t.year + 1, 1, 1), date(t.year + n + 1, 1, 1)),
    }
    if name not in ranges:
        raise SOQLError("MALFORMED_QUERY", f"Date literal {lit} isn’t supported for uploaded data.")
    return ranges[name]


def _sql_string(body: str, like: bool = False) -> str:
    """A SOQL string literal's text as an SQLite literal. SOQL escapes with a backslash (\\' \\\\ and, in LIKE, \\% \\_);
    in a LIKE pattern the escaped % and _ stay literal characters (ESCAPE '\\')."""
    out, i = [], 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            out.append("\\" + nxt if like and nxt in "%_\\" else {"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    lit = "'" + "".join(out).replace("'", "''") + "'"
    return f"{lit} ESCAPE '\\'" if like else lit


class _Translator:
    def __init__(self, meta: _Meta):
        self.meta = meta
        self.depth = 0

    def table(self, obj: str) -> str:
        for o in self.meta.objects:
            if o.lower() == obj.lower():
                return o
        raise SOQLError("INVALID_TYPE", f"sObject type '{obj}' is not supported. (It isn’t in the uploaded files.)")

    def column(self, obj: str, alias: str, name: str) -> tuple[str, dict | None]:
        """SQL for a field reference (Name, Account.Name) and its field info."""
        fields = self.meta.fields[obj]
        if "." in name:
            rel, fld = name.split(".", 1)
            if rel.lower() == obj.lower():
                return self.column(obj, alias, fld)
            ref = next((f for f in fields.values() if f["type"] == "reference"
                        and (f["name"].removesuffix("Id").lower() == rel.lower() or (f["name"] == "AccountId" and rel.lower() == "account"))), None)
            if ref is None:
                raise SOQLError("INVALID_FIELD", f"Didn't understand relationship '{rel}' in field path. (It isn’t in the uploaded file.)")
            target = "Account" if ref["name"] == "AccountId" else ref["name"].removesuffix("Id")
            tgt = next((o for o in self.meta.objects if o.lower() == target.lower()), None)
            parts = []
            if tgt:
                sub = next((f for f in self.meta.fields[tgt] if f.lower() == fld.lower()), None)
                if sub:
                    parts.append(f"(SELECT r.{_ident(sub)} FROM {_ident(tgt)} r WHERE r.\"Id\" = {alias}.{_ident(ref['name'])})")
            if fld.lower() == "name":
                parts.append(f"(SELECT n.name FROM _names n WHERE n.id = {alias}.{_ident(ref['name'])})")
            if not parts:
                raise SOQLError("INVALID_FIELD", f"No such column '{fld}' on {target} in the uploaded files.")
            return (parts[0] if len(parts) == 1 else f"COALESCE({', '.join(parts)})"), {"type": "string"}
        f = next((v for k, v in fields.items() if k.lower() == name.lower()), None)
        if f is None:
            raise SOQLError("INVALID_FIELD", f"No such column '{name}' on entity '{obj}'. (It isn’t in the uploaded file.)")
        return f"{alias}.{_ident(f['name'])}", f

    # -- expressions -------------------------------------------------------------------------------------------------

    def expr(self, toks: list[tuple[str, str]], obj: str, alias: str) -> str:
        out: list[str] = []
        i = 0
        while i < len(toks):
            kind, text = toks[i]
            low = text.lower()
            if kind == "p" and text == "(" and i + 1 < len(toks) and toks[i + 1][1].lower() == "select":
                j = self._close(toks, i)
                out.append("(" + self.select(toks[i + 2:j])[0] + ")")  # the tokens after its SELECT
                i = j + 1
                continue
            if kind == "id" and low in _AGG and i + 1 < len(toks) and toks[i + 1][1] == "(":
                j = self._close(toks, i + 1)
                inner = toks[i + 2:j]
                if low == "count_distinct":
                    out.append(f"COUNT(DISTINCT {self.expr(inner, obj, alias)})")
                elif low == "count" and (not inner or inner[0][1].lower() == "id"):
                    out.append("COUNT(*)" if not inner else f"COUNT({self.expr(inner, obj, alias)})")
                else:
                    out.append(f"{low.upper()}({self.expr(inner, obj, alias)})")
                i = j + 1
                continue
            if kind == "id" and low in _KEYWORDS:
                out.append(low.upper())
                i += 1
                continue
            if kind == "id" and low in ("true", "false"):
                out.append("1" if low == "true" else "0")
                i += 1
                continue
            if kind == "id" and low == "null":
                out.append("NULL")
                i += 1
                continue
            if kind == "id":  # a field, maybe compared with null or a date literal
                col, info = self.column(obj, alias, text)
                if i + 2 < len(toks) and toks[i + 1][0] == "op":
                    op, (rk, rt) = toks[i + 1][1], toks[i + 2]
                    if rk == "id" and rt.lower() == "null" and op in ("=", "!=", "<>"):
                        out.append(f"{col} IS {'NOT ' if op != '=' else ''}NULL")
                        i += 3
                        continue
                    if rk == "dlit" or (rk == "id" and rt.upper() in _NAMED_DATES):
                        out.append(self._date_cmp(col, op, rt.upper(), info))
                        i += 3
                        continue
                    if op in ("!=", "<>"):  # in SOQL, "not equal" also matches records where the field is empty
                        out.append(f"({col} != {self.expr([toks[i + 2]], obj, alias)} OR {col} IS NULL)")
                        i += 3
                        continue
                if i + 3 < len(toks) and [t[1].lower() for t in toks[i + 1:i + 3]] == ["not", "in"] and toks[i + 3][1] == "(":
                    j = self._close(toks, i + 3)  # NOT IN, likewise: empty fields count as "not in the list"
                    out.append(f"({col} NOT IN {self.expr(toks[i + 3:j + 1], obj, alias)} OR {col} IS NULL)")
                    i = j + 1
                    continue
                out.append(col)
                i += 1
                continue
            if kind == "str":
                out.append(_sql_string(text[1:-1], like=bool(out) and out[-1] == "LIKE"))
            elif kind == "dt":
                out.append("'" + (text[:19] if "T" in text else text) + "'")
            elif kind == "op":
                out.append("!=" if text == "<>" else text)
            elif kind == "dlit":
                raise SOQLError("MALFORMED_QUERY", f"Unexpected date literal {text}.")
            else:
                out.append(text)
            i += 1
        return " ".join(out)

    @staticmethod
    def _date_cmp(col: str, op: str, lit: str, info: dict | None) -> str:
        start, end = (d.isoformat() for d in _date_range(lit))
        return {
            "=": f"({col} >= '{start}' AND {col} < '{end}')",
            "!=": f"NOT ({col} >= '{start}' AND {col} < '{end}')", "<>": f"NOT ({col} >= '{start}' AND {col} < '{end}')",
            "<": f"{col} < '{start}'", "<=": f"{col} < '{end}'", ">": f"{col} >= '{end}'", ">=": f"{col} >= '{start}'",
        }[op]

    @staticmethod
    def _close(toks: list[tuple[str, str]], i: int) -> int:
        depth = 0
        for j in range(i, len(toks)):
            if toks[j][1] == "(":
                depth += 1
            elif toks[j][1] == ")":
                depth -= 1
                if depth == 0:
                    return j
        raise SOQLError("MALFORMED_QUERY", "Unbalanced brackets.")

    # -- SELECT ------------------------------------------------------------------------------------------------------

    def select(self, toks: list[tuple[str, str]]) -> tuple[str, dict]:
        """SQL for one SELECT (tokens after the SELECT keyword), and how to shape its results."""
        clauses: dict[str, list] = {"select": []}
        current, depth, i = "select", 0, 0
        names = {"from", "where", "group", "having", "order", "limit", "offset"}
        while i < len(toks):
            kind, text = toks[i]
            low = text.lower()
            if text == "(":
                depth += 1
            elif text == ")":
                depth -= 1
            if depth == 0 and kind == "id" and low in names:
                current = low
                clauses[current] = []
                i += 2 if low in ("group", "order") and i + 1 < len(toks) and toks[i + 1][1].lower() == "by" else 1
                continue
            clauses[current].append(toks[i])
            i += 1
        if not clauses.get("from"):
            raise SOQLError("MALFORMED_QUERY", "Missing FROM.")
        obj = self.table(clauses["from"][0][1])
        self.depth += 1
        alias = f"t{self.depth}"
        try:
            items, depth, cur = [], 0, []
            for t in clauses["select"]:
                if t[1] == "(":
                    depth += 1
                elif t[1] == ")":
                    depth -= 1
                if t[1] == "," and depth == 0:
                    items.append(cur)
                    cur = []
                else:
                    cur.append(t)
            if cur:
                items.append(cur)
            count_only = len(items) == 1 and [t[1].lower() for t in items[0]] == ["count", "(", ")"]
            cols, shape, n_expr = [], [], 0
            for it in items:
                if count_only:
                    cols.append('COUNT(*) AS "__count"')
                    continue
                key = None
                if len(it) > 1 and it[-1][0] == "id" and it[-1][1].lower() not in _KEYWORDS and it[-2][0] in ("id", "p") \
                        and not (it[-2][1] == "(" ):
                    if it[-2][1] == ")" or (it[-2][0] == "id" and len(it) == 2):
                        key, it = it[-1][1], it[:-1]
                is_agg = it[0][1].lower() in _AGG
                if key is None:
                    if is_agg:
                        key, n_expr = f"expr{n_expr}", n_expr + 1
                    else:
                        key = it[0][1] if len(it) == 1 else f"expr{n_expr}"
                        if len(it) == 1:
                            key = self._canonical(obj, it[0][1])
                info = self.column(obj, alias, it[0][1])[1] if len(it) == 1 and it[0][0] == "id" else None
                cols.append(f"{self.expr(it, obj, alias)} AS {_ident(key)}")
                shape.append((key, (info or {}).get("type")))
            sql = f"SELECT {', '.join(cols)} FROM {_ident(obj)} {alias}"
            if clauses.get("where"):
                sql += " WHERE " + self.expr(clauses["where"], obj, alias)
            if clauses.get("group"):
                sql += " GROUP BY " + self.expr(clauses["group"], obj, alias)
            if clauses.get("having"):
                sql += " HAVING " + self.expr(clauses["having"], obj, alias)
            if clauses.get("order"):
                sql += " ORDER BY " + self.expr(clauses["order"], obj, alias)
            if clauses.get("limit"):
                sql += f" LIMIT {int(clauses['limit'][0][1])}"
            if clauses.get("offset"):
                sql += ("" if clauses.get("limit") else " LIMIT -1") + f" OFFSET {int(clauses['offset'][0][1])}"
        finally:
            self.depth -= 1
        return sql, {"object": obj, "count_only": count_only, "shape": shape}

    def _canonical(self, obj: str, name: str) -> str:
        if "." in name:
            rel, fld = name.split(".", 1)
            return f"{rel}.{fld}"
        return next((k for k in self.meta.fields[obj] if k.lower() == name.lower()), name)


def run_soql(dataset: str, soql: str) -> tuple[str, list[dict], int]:
    """(object, records, totalSize) for a SOQL query over the uploaded data."""
    m = re.match(r"\s*select\s", soql, re.I)
    if not m:
        raise SOQLError("MALFORMED_QUERY", "Only SELECT queries can run on uploaded data.")
    meta = _CACHE.get(dataset)
    if re.search(r"\bfrom\s+organization\b", soql, re.I):
        return "Organization", [{"attributes": {"type": "Organization"}, "Name": _org_name(dataset), "OrganizationType": "Uploaded file",
                                 "Id": "00DUPLOAD" + dataset[:9].upper(), "IsSandbox": False}], 1
    toks = _tokens(soql)
    sql, how = _Translator(meta).select(toks[1:])
    db = _connect(dataset)
    try:
        rows = db.execute(sql).fetchall()
    except sqlite3.Error as exc:
        raise SOQLError("MALFORMED_QUERY", f"Couldn’t run this query on the uploaded data: {exc}") from exc
    finally:
        db.close()
    obj = how["object"]
    if how["count_only"]:
        return obj, [], int(rows[0][0]) if rows else 0
    out = []
    aggregate = any(k.startswith("expr") for k, _ in how["shape"]) or "group by" in soql.lower()
    for r in rows:
        rec: dict = {"attributes": {"type": "AggregateResult" if aggregate else obj}}
        for (key, ftype), val in zip(how["shape"], tuple(r)):
            if ftype == "boolean" and val is not None:
                val = bool(val)
            elif isinstance(val, float) and val.is_integer() and ftype in ("int",):
                val = int(val)
            if "." in key:
                rel, fld = key.split(".", 1)
                if val is None and not isinstance(rec.get(rel), dict):
                    rec[rel] = None
                else:
                    rec[rel] = {**(rec.get(rel) or {"attributes": {"type": rel}}), fld: val}
            else:
                rec[key] = val
        out.append(rec)
    return obj, out, len(out)


def _org_name(dataset: str) -> str:
    db = _connect(dataset)
    try:
        row = db.execute("SELECT value FROM _info WHERE key = 'name'").fetchone() if db.execute(
            "SELECT 1 FROM sqlite_master WHERE name = '_info'").fetchone() else None
        return row[0] if row else "Uploaded data"
    finally:
        db.close()


def set_name(dataset: str, name: str) -> None:
    db = _connect(dataset)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS _info (key TEXT PRIMARY KEY, value TEXT)")
        db.execute("INSERT OR REPLACE INTO _info VALUES ('name', ?)", (name,))
        db.commit()
    finally:
        db.close()


def record(dataset: str, obj: str, record_id: str) -> dict | None:
    meta = _CACHE.get(dataset)
    if obj not in meta.objects:
        return None
    fields = list(meta.fields[obj])
    _, rows, _ = run_soql(dataset, f"SELECT {', '.join(fields)} FROM {obj} WHERE Id = '{record_id.replace(chr(39), '')}'")
    return rows[0] if rows else None


# ---------------------------------------------------------------------------------------------------------------------
# The client: Salesforce's REST API, answered from the uploaded files


def dataset_of(instance_url: str) -> str | None:
    return instance_url[len(LOCAL_SCHEME):].strip("/") if instance_url.startswith(LOCAL_SCHEME) else None


def _err(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json=[{"errorCode": code, "message": message}])


def handle(dataset: str, version: str, method: str, url: str, headers: dict[str, str]) -> httpx.Response:
    parsed = urlparse(url)
    path = unquote(parsed.path)
    path = re.sub(r"^/services/data/v[\d.]+", "", path)
    query = parse_qs(parsed.query)
    if method != "GET":
        return _err(405, "METHOD_NOT_ALLOWED", "Uploaded data is read-only.")
    try:
        meta = _CACHE.get(dataset)
        if path == "/limits":
            return httpx.Response(200, json={"DailyApiRequests": {"Max": 1_000_000, "Remaining": 1_000_000},
                                             "DailyBulkV2QueryJobs": {"Max": 0, "Remaining": 0}})
        if path == "/limits/recordCount":
            return httpx.Response(200, json={"sObjects": [{"name": o, "count": i["rows"]} for o, i in meta.objects.items()]})
        if path in ("/sobjects", "/sobjects/"):
            return httpx.Response(200, json={"encoding": "UTF-8", "maxBatchSize": 200, "sobjects": meta.sobjects()})
        if m := re.fullmatch(r"/sobjects/(\w+)/describe/?", path):
            obj = next((o for o in meta.objects if o.lower() == m[1].lower()), None)
            return httpx.Response(200, json=meta.describe(obj)) if obj else _err(404, "NOT_FOUND", f"The requested resource does not exist: {m[1]}")
        if re.fullmatch(r"/sobjects/\w+/describe/.*", path):
            return _err(404, "NOT_FOUND", "Page layouts aren’t part of uploaded data.")
        if m := re.fullmatch(r"/sobjects/(\w+)/(\w+)", path):
            rec = record(dataset, m[1], m[2])
            return httpx.Response(200, json=rec) if rec else _err(404, "NOT_FOUND", "The requested resource does not exist")
        if path.startswith("/tooling/"):
            return httpx.Response(200, json={"size": 0, "totalSize": 0, "done": True, "records": []})
        if m := re.fullmatch(r"/query(?:All)?/(LOCAL[A-Za-z0-9]+-\d+)", path):
            return _page(m[1], _batch(headers))
        if path in ("/query", "/queryAll", "/query/", "/queryAll/"):
            soql = (query.get("q") or [""])[0]
            obj, records, total = run_soql(dataset, soql)
            size = _batch(headers)
            if size and len(records) > size:
                key = f"LOCAL{dataset}{uuid.uuid4().hex[:12]}"  # letters and digits only, like a Salesforce query locator
                _PAGES[key] = (obj, records, total)
                while len(_PAGES) > 30:
                    _PAGES.popitem(last=False)
                return _page(key, size, version)
            return httpx.Response(200, json={"totalSize": total, "done": True, "records": records})
        if path.startswith("/parameterizedSearch"):
            return httpx.Response(200, json={"searchRecords": _search(dataset, (query.get("q") or [""])[0])})
        return _err(404, "NOT_FOUND", "That isn’t available for uploaded data.")
    except SOQLError as exc:
        return _err(400, exc.code, str(exc))
    except UploadError as exc:
        return _err(404, "NOT_FOUND", str(exc))


def _batch(headers: dict[str, str]) -> int | None:
    m = re.search(r"batchSize=(\d+)", headers.get("Sforce-Query-Options", "") or headers.get("sforce-query-options", ""))
    return int(m[1]) if m else None


def _page(key: str, size: int | None, version: str = "v61.0") -> httpx.Response:
    """A page of a stored result. Cursors look like Salesforce's (…/query/<locator>-<offset>), so the record tables
    page through uploaded data exactly as they do through Salesforce."""
    base, _, offset = key.rpartition("-")
    if not base:
        base, offset = key, "0"
    start = int(offset) if offset.isdigit() else 0
    if base not in _PAGES:
        return _err(400, "INVALID_QUERY_LOCATOR", "This list has expired. Reload the page.")
    _, records, total = _PAGES[base]
    size = size or 2000
    chunk = records[start:start + size]
    end = start + len(chunk)
    body = {"totalSize": total, "done": end >= len(records), "records": chunk}
    if end < len(records):
        body["nextRecordsUrl"] = f"/services/data/{version}/query/{base}-{end}"
    return httpx.Response(200, json=body)


def _search(dataset: str, term: str) -> list[dict]:
    term = term.strip().strip("*")
    if len(term) < 2:
        return []
    meta = _CACHE.get(dataset)
    out: list[dict] = []
    like = term.replace("'", "").replace("%", "")
    for obj, fields in meta.fields.items():
        if "Name" not in fields:
            continue
        searchable = [f for f in ("Name", "Email", "Phone", "Company", "Website") if f in fields]
        cond = " OR ".join(f"{f} LIKE '%{like}%'" for f in searchable)
        _, rows, _ = run_soql(dataset, f"SELECT Id, {', '.join(searchable)} FROM {obj} WHERE {cond} LIMIT 10")
        out += rows
    return out[:50]


class LocalSalesforceClient(SalesforceClient):
    """A SalesforceClient whose org is an uploaded file: same calls, answered locally, never sent anywhere."""

    @property
    def dataset(self) -> str:
        return dataset_of(self.conn.instance_url) or ""

    def _send(self, path: str, extra: dict[str, str], method: str = "GET", json: dict | None = None,
              params: dict | None = None) -> httpx.Response:
        url = path if path.startswith(("http", LOCAL_SCHEME)) else f"/{path.lstrip('/')}"
        url = re.sub(r"^local://[^/]*", "", url)
        return handle(self.dataset, self.settings.sf_api_version, method, url, extra)

    def _refresh(self) -> None:  # nothing to refresh: the data is local
        return None

    def _bulk(self, soql: str) -> bool:
        return False


def summarize(headers: list[str], rows: list[list[str]], obj: str) -> dict:
    """What the upload screen shows: columns with the field each will become and its type, and a few rows."""
    mapping = suggest_mapping(obj, headers)
    std = standard_fields(obj)
    cols = []
    for i, h in enumerate(headers):
        values = [r[i] for r in rows]
        filled = sum(1 for v in values if v and v.strip())
        target = mapping.get(h)
        cols.append({"header": h, "field": target, "type": std[target][1] if target else infer_type(values),
                     "filled": filled, "sample": next((v for v in values if v and v.strip()), "")[:80]})
    return {"columns": cols, "rows": len(rows), "preview": [dict(zip(headers, r)) for r in rows[:5]],
            "standardFields": [{"name": api, "label": label, "type": t} for api, (label, t, _) in std.items()]}

