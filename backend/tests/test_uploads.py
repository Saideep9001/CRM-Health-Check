"""Uploaded CSV/Excel data checked like a Salesforce org: reading files, SOQL over the rows, and a full check run."""
import io
import json
import zipfile

import pytest

from app.routers import uploads
from app.salesforce import explorer, local_org

API = "/api/v1"

ACCOUNTS = """Account Name,Website,Phone,Billing City,Billing State/Province,Billing Zip/Postal Code,Industry,Region Code
Acme Corp,acme.com,(415) 555-0100,San Francisco,CA,94105,Tech,
ACME CORP,www.acme.com,415-555-0100,San Francisco,CA,94105,Tech,
Globex,globex.com,,Springfield,IL,,Energy,
Initech,,,Austin,TX,73301,Tech,
Umbrella  Ltd,umbrella.co.uk,+44 20 7946 0000,London,,,Health,
"""
OPPS = """Opportunity Name,Account Name,Amount,Close Date,Stage
Acme renewal,Acme Corp,"$12,000",2026-03-01,Closed Won
Acme upsell,Acme Corp,5000,2026-12-15,Prospecting
Globex pilot,Globex,,,Closed Lost
New logo,Initech,800,03/15/2027,Negotiation
"""


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(local_org, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(uploads, "STAGING", tmp_path / "staging")
    explorer.clear_cache()


def _upload(client, text, filename, obj, org_id=None, name=None, mapping=None):
    r = client.post(f"{API}/uploads/preview", params={"filename": filename, "object": obj}, content=text.encode())
    assert r.status_code == 200, r.text
    p = r.json()
    body = {"token": p["token"], "object": obj, "mapping": mapping or {c["header"]: c["field"] for c in p["columns"]}}
    if org_id:
        body["orgId"] = org_id
    if name:
        body["name"] = name
    r = client.post(f"{API}/uploads/import", json=body)
    assert r.status_code == 200, r.text
    return p, r.json()


# ---------------- reading files and matching columns ----------------


def test_columns_are_matched_to_salesforce_fields():
    m = local_org.suggest_mapping("Account", ["Account Name", "Billing City", "City", "Phone Number", "Region Code"])
    assert m == {"Account Name": "Name", "Billing City": "BillingCity", "City": None, "Phone Number": "Phone", "Region Code": None}
    assert local_org.suggest_mapping("Opportunity", ["Stage", "Account Name", "Close Date"]) == {
        "Stage": "StageName", "Account Name": "AccountId", "Close Date": "CloseDate"}


def test_types_are_worked_out_from_the_values():
    assert local_org.infer_type(["a@b.com", "c@d.org"]) == "email"
    assert local_org.infer_type(["2024-01-05", "03/04/2025"]) == "date"
    assert local_org.infer_type(["$1,200", "$5"]) == "currency"
    assert local_org.infer_type(["yes", "no", ""]) == "boolean"
    assert local_org.infer_type(["(415) 555-0100", "+44 20 7946 0000"]) == "phone"
    assert local_org.infer_type(["Gold"] * 15 + ["Silver"] * 15) == "picklist"
    assert local_org.convert("03/15/2027", "date") == "2027-03-15"
    assert local_org.convert("15/03/2027", "date") == "2027-03-15"  # day first when it can only be that


def _xlsx(rows: list[list[str]]) -> bytes:
    cells = "".join(
        f'<row r="{i + 1}">' + "".join(f'<c r="{chr(65 + j)}{i + 1}" t="inlineStr"><is><t>{v}</t></is></c>' for j, v in enumerate(r)) + "</row>"
        for i, r in enumerate(rows))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   f"<sheetData>{cells}</sheetData></worksheet>")
    return buf.getvalue()


def test_excel_files_are_read():
    headers, rows = local_org.read_table("leads.xlsx", _xlsx([["Last Name", "Company"], ["Lovelace", "Analytical"], ["Turing", ""]]))
    assert headers == ["Last Name", "Company"] and rows == [["Lovelace", "Analytical"], ["Turing", ""]]
    with pytest.raises(local_org.UploadError, match="Save As"):
        local_org.read_table("old.xls", b"x")


# ---------------- SOQL over the uploaded rows ----------------


@pytest.fixture
def dataset():
    ds = local_org.new_dataset()
    h, rows = local_org.read_table("a.csv", ACCOUNTS.encode())
    local_org.load_object(ds, "Account", "a.csv", h, rows, local_org.suggest_mapping("Account", h))
    h, rows = local_org.read_table("o.csv", OPPS.encode())
    local_org.load_object(ds, "Opportunity", "o.csv", h, rows, local_org.suggest_mapping("Opportunity", h))
    return ds


def q(ds, soql):
    return local_org.run_soql(ds, soql)


def test_counts_nulls_and_subqueries(dataset):
    assert q(dataset, "SELECT COUNT() FROM Account")[2] == 5
    assert q(dataset, "SELECT COUNT() FROM Account WHERE (Website = null OR Phone = null)")[2] == 2  # Globex, Initech
    assert q(dataset, "SELECT COUNT() FROM Account WHERE Id NOT IN (SELECT AccountId FROM Opportunity WHERE IsClosed = false AND AccountId != null)")[2] == 3
    rec = q(dataset, "SELECT COUNT(Website) f0, COUNT(Phone) f1 FROM Account")[1][0]
    assert (rec["f0"], rec["f1"]) == (4, 3)
    assert q(dataset, "SELECT COUNT() FROM Opportunity WHERE IsClosed = true AND IsWon = false")[2] == 1


def test_group_by_is_case_insensitive_like_salesforce(dataset):
    rows = q(dataset, "SELECT Name v, COUNT(Id) c FROM Account WHERE Name != null GROUP BY Name HAVING COUNT(Id) > 1")[1]
    assert [(r["v"].lower(), r["c"]) for r in rows] == [("acme corp", 2)]


def test_relationships_dates_and_ordering(dataset):
    _, rows, _ = q(dataset, "SELECT Name, Account.Name, Amount, CloseDate FROM Opportunity WHERE CloseDate < LAST_N_DAYS:30 ORDER BY Name")
    assert [(r["Name"], r["Account"]["Name"], r["Amount"]) for r in rows] == [("Acme renewal", "Acme Corp", 12000)]
    assert q(dataset, "SELECT COUNT() FROM Opportunity WHERE CloseDate > TODAY")[2] == 2
    _, rows, _ = q(dataset, "SELECT Name FROM Account WHERE Name LIKE 'acme%' ORDER BY Name DESC NULLS LAST LIMIT 1")
    assert len(rows) == 1


def test_unknown_fields_and_objects_fail_like_salesforce(dataset):
    with pytest.raises(local_org.SOQLError) as e:
        q(dataset, "SELECT COUNT() FROM Account WHERE LastActivityDate = null")
    assert e.value.code == "INVALID_FIELD"
    with pytest.raises(local_org.SOQLError) as e:
        q(dataset, "SELECT COUNT() FROM Contact")
    assert e.value.code == "INVALID_TYPE"


def test_string_values_are_kept_exactly(dataset):
    assert q(dataset, "SELECT COUNT() FROM Account WHERE Name = 'Umbrella  Ltd'")[2] == 1  # two spaces, as uploaded
    assert q(dataset, "SELECT COUNT() FROM Account WHERE Name IN ('globex', 'Initech')")[2] == 2


# ---------------- end to end: upload, then run the Data Quality check ----------------


def test_upload_and_check(client):
    more = "".join(f"Company {n},company{n}.com,(212) 555-{1000 + n},New York,NY,{10000 + n},Retail,\n" for n in range(20))  # enough for field cards
    preview, first = _upload(client, ACCOUNTS + more, "accounts.csv", "Account", name="Acme export")
    assert preview["rows"] == 25 and {c["header"]: c["field"] for c in preview["columns"]}["Region Code"] is None
    org = first["orgId"]
    _, second = _upload(client, OPPS, "opps.csv", "Opportunity", org_id=org)
    assert [o["name"] for o in second["objects"]] == ["Account", "Opportunity"]

    conn = client.get(f"{API}/salesforce/connection").json()
    assert conn["environment"] == "upload" and conn["organizationName"] == "Acme export" and conn["status"] == "connected"
    objs = client.get(f"{API}/data/objects").json()
    assert {o["name"] for o in (objs["items"] if isinstance(objs, dict) else objs)} >= {"Account", "Opportunity"}

    scope = {"categoryIds": ["data-quality"], "areaIds": ["area-1", "area-2"], "objects": ["Account", "Opportunity"],
             "staleLeadDays": 30, "stuckOpportunityDays": 60}
    r = client.post(f"{API}/assessments", json={"name": "Upload check", "connectionId": conn["id"], "scope": scope})
    assert r.status_code == 201, r.text
    a = client.get(f"{API}/assessments/{r.json()['id']}").json()
    assert a["status"] == "completed", a
    res = client.get(f"{API}/assessments/{a['id']}/results").json()
    ind = {i["label"]: i for area in res["areas"] for i in area["indicators"]}
    assert ind["Duplicate Accounts"]["value"] >= 1  # Acme Corp / ACME CORP
    assert ind["All Fields (Accounts)"]["value"] >= 8
    used = {f["name"]: f["note"] for f in ind["Unused & Low-Completion Fields (Accounts)"]["fieldList"]}
    assert used.get("Region_Code__c") == "Never filled in"
    assert "Accounts Without Contacts" not in ind  # no Contacts uploaded: that card can't be worked out, so it isn't shown

    # removing the upload deletes its data
    assert client.delete(f"{API}/salesforce/connection").status_code == 204
    assert not list(local_org.UPLOAD_DIR.glob("*.db"))


def test_bad_files_are_explained(client):
    r = client.post(f"{API}/uploads/preview", params={"filename": "x.pdf"}, content=b"%PDF")
    assert r.status_code == 422 and "CSV" in r.json()["detail"]
    r = client.post(f"{API}/uploads/preview", params={"filename": "x.csv"}, content=b"")
    assert r.status_code == 422


# ---------------- Your Data: the uploaded rows as a table with Excel-style filters ----------------


def test_your_data_filters_search_values_and_paging(client):
    rows = "".join(f"Shop {n}{' 50%_off' if n == 3 else ''},shop{n}.com,,Boston,{'MA' if n % 2 else 'NY'},,{'Retail' if n % 3 else 'Tech'},{n * 100},\n"
                   for n in range(450))
    _upload(client, ACCOUNTS + rows, "accounts.csv", "Account", name="Shops")
    _, opps = _upload(client, OPPS, "opps.csv", "Opportunity", org_id=client.get(f"{API}/salesforce/connection").json()["orgId"])

    def records(**params):
        r = client.get(f"{API}/data/objects/Account/records", params=params)
        assert r.status_code == 200, r.text
        return r.json()

    def f(*filters):
        return json.dumps([{"field": a, "op": b, "value": c} for a, b, c in filters])

    page = records(fields="Name,BillingState,Industry,Region_Code__c")
    assert page["totalSize"] == 455 and len(page["records"]) == 200 and page["nextCursor"]
    seen = len(page["records"])
    while page["nextCursor"]:  # every page, like scrolling to the end of the table
        page = records(cursor=page["nextCursor"])
        seen += len(page["records"])
    assert seen == 455

    assert records(filters=f(("BillingState", "in", ["MA"])))["totalSize"] == 225
    assert records(filters=f(("BillingState", "in", ["CA", None])))["totalSize"] == 3  # Acme ×2, and Umbrella (no state)
    assert records(filters=f(("Industry", "eq", "Tech"), ("BillingState", "notin", ["NY"])))["totalSize"] == 3 + 75  # Acme ×2, Initech, shops
    assert records(filters=f(("BillingState", "ne", "NY")))["totalSize"] == 455 - 225  # like Salesforce, includes the blank one
    assert records(filters=f(("Region_Code__c", "gte", 40000)))["totalSize"] == 50
    assert records(filters=f(("Website", "blank", None)))["totalSize"] == 1
    assert records(filters=f(("Name", "contains", "50%_off")))["totalSize"] == 1  # % and _ are plain text here
    assert records(q="shop 44")["totalSize"] == 11  # Shop 44, Shop 440 … 449
    top = records(sort="Region_Code__c", dir="desc", fields="Name,Region_Code__c")["records"][0]
    assert top["values"]["Name"] == "Shop 449"

    vals = client.get(f"{API}/data/objects/Account/values", params={"field": "BillingState"}).json()
    assert {v["value"]: v["count"] for v in vals["values"]} == {"CA": 2, "IL": 1, "MA": 225, "NY": 225, "TX": 1} and vals["blanks"] == 1
    vals = client.get(f"{API}/data/objects/Account/values", params={"field": "Industry", "filters": f(("BillingState", "in", ["MA"]))}).json()
    assert sum(v["count"] for v in vals["values"]) == 225  # follows the other columns' filters

    opp = client.get(f"{API}/data/objects/Opportunity/records", params={"fields": "Name,AccountId,StageName"}).json()
    named = {r["values"]["Name"]: r["refNames"].get("AccountId") for r in opp["records"]}
    assert named["Acme renewal"] == "Acme Corp" and named["New logo"] == "Initech"  # the account's name, not its id
    assert opps["rows"] == 4
