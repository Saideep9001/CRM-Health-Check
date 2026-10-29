"""Data Quality health check engine, run against a fake org with known data."""
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.db import SessionLocal
from app.models import AssessmentRow
from app.salesforce import explorer

from .conftest import FakeSalesforce, connect

API = "/api/v1"


def _f(name, **kw):
    return {"name": name, "label": kw.pop("label", name), "type": kw.pop("type", "string"), "filterable": True, "groupable": True, "sortable": True, **kw}


DESCRIBE = {
    "Account": [_f("Id", type="id"), _f("Name"), _f("Website", type="url"), _f("Phone", type="phone"), _f("Industry"), _f("Type"), _f("BillingCountry"),
                _f("BillingState"), _f("BillingCity"),
                _f("NumberOfEmployees", type="int"), _f("LastModifiedDate", type="datetime"),
                _f("Used__c", custom=True), _f("Region_Code__c", custom=True), _f("Legacy_Notes_old__c", custom=True, label="Legacy Notes")],
    "Contact": [_f("Id", type="id"), _f("Email", type="email"), _f("Phone"), _f("MobilePhone"), _f("Title"), _f("AccountId", type="reference"),
                _f("MailingCountry"), _f("LastModifiedDate", type="datetime")],
    "Lead": [_f("Id", type="id"), _f("Email", type="email"), _f("Phone"), _f("Company"), _f("Title"), _f("LeadSource"), _f("Industry"), _f("Country"),
             _f("State"), _f("IsConverted", type="boolean")],
    "Opportunity": [_f("Id", type="id"), _f("Amount", type="currency"), _f("NextStep"), _f("LeadSource"), _f("Type")],
    # A custom object, checked with generic rules when chosen.
    "Invoice__c": [_f("Id", type="id"), _f("Name", nameField=True), _f("Status__c", custom=True, createable=True, nillable=True),
                   _f("Due_Date__c", type="date", custom=True, createable=True, nillable=True), _f("Notes_old__c", custom=True, label="Notes")],
}
PLURAL = {"Account": "Accounts", "Contact": "Contacts", "Lead": "Leads", "Opportunity": "Opportunities", "Invoice__c": "Invoices"}
TOTALS = {"Account": 100, "Contact": 200, "Lead": 50, "Opportunity": 30, "Invoice__c": 40}
DUPES = {("Account", "Name"): [("Acme", 3), ("Globex", 2)], ("Account", "Website"): [("acme.com", 2)], ("Contact", "Email"): [("a@x.com", 2)],
         ("Invoice__c", "Name"): [("INV-1", 4)]}
GROUPS = {("Account", "BillingCountry"): [("USA", 50), ("United States", 10), ("US", 5), ("Canada", 8)]}
MISSING = {("Contact", "Email"): 40, ("Lead", "Email"): 10}
# Accounts as typed by people. Duplicates (website, phone and address fields that are filled on both must match):
# 1 + 2 (same site and phone, written differently) and 4 + 5 (same site and city) = 2 extra. 3 has the Acme site but
# a different state spelling, so it isn't a copy. Odd formats: 2's website and phone, 3's state ("California" vs "CA").
ACCOUNT_ROWS = [
    {"Id": "001000000000001AAA", "Name": "Acme, Inc.", "Website": "acme.com", "Phone": "415-555-1234", "BillingCity": "San Francisco", "BillingState": "CA"},
    {"Id": "001000000000002AAA", "Name": "ACME Inc", "Website": "https://www.acme.com/", "Phone": "(415) 555-1234", "BillingCity": "San Francisco", "BillingState": "CA"},
    {"Id": "001000000000003AAA", "Name": "The Acme Company LLC", "Website": "acme.com", "Phone": None, "BillingCity": "San Francisco", "BillingState": "California"},
    {"Id": "001000000000004AAA", "Name": "Globex", "Website": "globex.io", "Phone": "212-555-0000", "BillingCity": "New York", "BillingState": "NY"},
    {"Id": "001000000000005AAA", "Name": "Globex Corp.", "Website": "globex.io", "Phone": None, "BillingCity": "New York", "BillingState": None},
    {"Id": "001000000000006AAA", "Name": "Initech", "Website": "initech.com", "Phone": "312-555-9999", "BillingCity": "Chicago", "BillingState": "IL"},
]
INVOICE_ROWS = [{"Id": f"a00000000000000{i}AA", "Name": "INV-1", "Status__c": "Open"} for i in range(4)] + [
    {"Id": "a000000000000009AA", "Name": "INV-2", "Status__c": "Open"}]
USAGE = {"Used__c": 80, "Region_Code__c": 0}


class FakeOrg(FakeSalesforce):
    """Fake Salesforce whose data (counts, duplicates, spellings) is fixed above."""

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        if request.headers.get("authorization", "").removeprefix("Bearer ") in self.valid_access:
            if url.path.endswith("/sobjects"):
                return httpx.Response(200, json={"sobjects": [{"name": n, "label": n, "labelPlural": PLURAL[n], "queryable": True, "retrieveable": True} for n in DESCRIBE]})
            m = re.search(r"/sobjects/(\w+)/describe$", url.path)
            if m:
                return httpx.Response(200, json={"name": m[1], "fields": DESCRIBE[m[1]]})
            if url.path.endswith("/query"):
                q = parse_qs(url.query)["q"][0]
                if "FROM Organization" not in q:
                    self.soql.append(q)
                    return httpx.Response(200, json=self.answer(q))
        return super().handler(request)

    @staticmethod
    def answer(q: str) -> dict:
        obj = re.search(r"FROM (\w+)", q)[1]
        if q.startswith("SELECT COUNT()"):
            if "NOT IN (SELECT AccountId" in q:
                n = 25
            elif "BillingCountry IN (" in q:  # records with an odd spelling ("United States", "US")
                n = 15
            elif m := re.search(r"(\w+__c) != null", q):
                n = USAGE.get(m[1], 0)
            elif m := re.search(r"(\w+) = null", q):
                n = MISSING.get((obj, m[1]), 10)
            else:
                n = TOTALS[obj]
            return {"totalSize": n, "done": True, "records": []}
        if q.startswith("SELECT COUNT(") and " f0" in q:  # several fields counted at once
            fields = re.findall(r"COUNT\((\w+)\) f\d+", q)
            rec = {f"f{n}": (USAGE[f] if f in USAGE else TOTALS[obj] - MISSING.get((obj, f), 10)) for n, f in enumerate(fields)}
            return {"totalSize": 1, "done": True, "records": [rec]}
        if q.startswith("SELECT Id,") and obj in ("Account", "Invoice__c"):  # rows for duplicates and formats
            rows = ACCOUNT_ROWS if obj == "Account" else INVOICE_ROWS
            return {"totalSize": len(rows), "done": True, "records": rows}
        if not re.search(r"SELECT (\w+) v", q):  # a plain record list (e.g. a problem's affected records)
            return {"totalSize": 2, "done": True, "records": [
                {"Id": "003000000000001AAA", "Name": "Ada Lovelace", "Email": None},
                {"Id": "003000000000002AAA", "Name": "Alan Turing", "Email": None},
            ]}
        fld = re.search(r"SELECT (\w+) v", q)[1]
        rows = (DUPES if "HAVING" in q else GROUPS).get((obj, fld), [])
        return {"totalSize": len(rows), "done": True, "records": [{"v": v, "c": c} for v, c in rows]}


@pytest.fixture
def sf():
    explorer.clear_cache()
    return FakeOrg()


def start(client, areas=("area-1", "area-2"), **scope):
    conn = client.get(f"{API}/salesforce/connection").json()
    body = {"categoryIds": ["data-quality"], "areaIds": list(areas), "staleLeadDays": 30, "stuckOpportunityDays": 60, **scope}
    return client.post(f"{API}/assessments", json={"name": "Q4 check", "connectionId": conn["id"], "scope": body})


def test_requires_connection(client):
    r = client.post(f"{API}/assessments", json={"name": "x", "connectionId": "x", "scope": {"areaIds": ["area-1"]}})
    assert r.status_code == 409


def test_full_data_quality_run(client, sf):
    connect(client)
    r = start(client, areas=("area-1", "area-2"))
    assert r.status_code == 201 and r.json()["status"] == "queued"
    aid = r.json()["id"]

    a = client.get(f"{API}/assessments/{aid}").json()  # the background task has already run
    assert a["status"] == "completed", a
    assert a["progress"] == 100 and a["organizationName"] == "Acme Inc" and a["findingsCount"] > 0
    assert a["recordsAssessed"] == 100 + 200 + 50 + 30

    res = client.get(f"{API}/assessments/{aid}/results").json()
    areas = {x["areaId"]: x for x in res["areas"]}
    ind = {i["label"]: i for i in areas["area-1"]["indicators"]}
    labels = [i["label"] for i in areas["area-1"]["indicators"]]
    # Each object's cards together: Accounts get the four core cards plus two of their own.
    assert labels[:6] == ["Duplicate Accounts", "Missing Key Fields (Accounts)", "Data Standardization Issues (Accounts)",
                          "No Activity in 6 Months (Accounts)", "Accounts Without Contacts", "Accounts Without Open Opportunities"]
    assert {"Duplicate Contacts", "Missing Key Fields (Contacts)", "Data Standardization Issues (Contacts)", "No Activity in 6 Months (Contacts)",
            "Duplicate Leads", "Missing Key Fields (Leads)", "Missing Key Fields (Opportunities)"} <= set(ind)
    assert ind["Duplicate Accounts"]["value"] == 2 and ind["Duplicate Contacts"]["value"] == 0
    mk = ind["Missing Key Fields (Contacts)"]  # Email or Phone empty on 40 of 200 (the first condition counted by the fake)
    assert {k: mk[k] for k in ("value", "unit", "direction")} == {"value": 20.0, "unit": "%", "direction": "lower-better"}
    assert ind["Data Standardization Issues (Accounts)"]["value"] == 5  # all 4 phones lack a country code (e.g. "415-555-1234"), and "California" vs "CA"
    assert ind["Accounts Without Contacts"]["value"] == 25
    # each data card charts its own number per field
    dup = {f["field"]: f for f in ind["Duplicate Accounts"]["fieldScores"]}
    assert dup["Website"] == {"field": "Website", "label": "Website", "count": 5, "of": 6, "pct": 83.3}  # acme.com ×3, globex.io ×2
    assert dup["BillingCity"]["count"] == 5  # every default field gets a bar: records sharing their city (the card itself doesn't match on a city alone)
    empty = {f["field"]: f for f in ind["Missing Key Fields (Accounts)"]["fieldScores"]}
    assert (empty["Website"]["count"], empty["Website"]["of"]) == (10, 100)
    odd = {f["field"]: f for f in ind["Data Standardization Issues (Accounts)"]["fieldScores"]}
    assert (odd["BillingState"]["count"], odd["BillingState"]["of"]) == (1, 5)  # "California" vs "CA"
    assert ind["No Activity in 6 Months (Accounts)"]["fieldScores"] is None
    ind2 = {i["label"]: i for i in areas["area-2"]["indicators"]}
    labels2 = [i["label"] for i in areas["area-2"]["indicators"]]
    # each object's field cards together, then one scorecard
    assert labels2[:5] == ["All Fields (Accounts)", "Unused & Low-Completion Fields (Accounts)", "Outdated Fields (Accounts)", "Look-alike Fields (Accounts)",
                           "Empty Fields Others Depend On (Accounts)"]
    assert labels2[-1] == "Data Quality Scorecard"
    used = ind2["Unused & Low-Completion Fields (Accounts)"]
    assert {f["name"]: f["note"] for f in used["fieldList"]}["Region_Code__c"] == "Never filled in"
    assert [f["name"] for f in ind2["Outdated Fields (Accounts)"]["fieldList"]] == ["Legacy_Notes_old__c"]
    scores = dict(ind2["Data Quality Scorecard"]["criteria"])
    assert list(scores)[:3] == ["Account score", "Lead score", "Contact score"] and "Overall Data Quality score" in scores  # Account, Lead, Contact, Opportunity order
    assert "Area 1: " in scores["Account score"] and "Area 2: " in scores["Account score"] and "%" in scores["Account score"]  # both areas, each half
    assert res["categories"][0]["categoryId"] == "data-quality"
    assert res["overallScore"] == res["dataQualityScore"] == res["categories"][0]["score"]
    assert 0 < res["overallScore"] < 100 and res["salesProcessScore"] is None

    findings = client.get(f"{API}/assessments/{aid}/findings").json()["items"]
    names = [f["name"] for f in findings]
    assert "Duplicate Accounts" in names and "State and Country picklists are turned off" in names
    assert "Duplicate Contacts" not in names  # 1 extra of 200 is too small to report
    unused = next(f for f in findings if f["name"] == "Unused and low-completion fields on Accounts")
    assert unused["objectName"] == "Account" and unused["measure"] == "Unused & Low-Completion Fields (Accounts)" and "Region" in unused["description"]
    old = next(f for f in findings if f["name"] == "Outdated-looking fields on Accounts")
    assert old["measure"] == "Outdated Fields (Accounts)" and "Legacy Notes" in old["description"]
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    assert [order[f["severity"]] for f in findings] == sorted(order[f["severity"]] for f in findings)
    assert all(f["priority"] in ("P1", "P2", "P3", "P4") and f["areaId"] in ("area-1", "area-2") for f in findings)
    by_obj = {o["name"]: o for o in res["objects"]}
    assert list(by_obj) == ["Account", "Contact", "Lead", "Opportunity"]  # default objects, in order
    assert by_obj["Account"]["records"] == 100 and by_obj["Account"]["duplicates"] == 2 and by_obj["Account"]["problems"] >= 2
    assert 0 < by_obj["Contact"]["completeness"] < 100
    assert not any("Invoice__c" in q for q in sf.soql)  # not chosen, not queried
    assert sf.soql and all(q.startswith("SELECT") for q in sf.soql)


def test_lookback_limits_records(client, sf):
    connect(client)
    start(client, areas=("area-1",), lookbackDays=90)
    assert any("LAST_N_DAYS:90" in q for q in sf.soql if "FROM Account" in q)


def test_only_unbuilt_areas_rejected(client):
    connect(client)
    assert start(client, areas=("area-99",)).status_code == 422


def test_one_run_at_a_time_and_cancel(client):
    connect(client)
    with SessionLocal() as db:
        db.add(AssessmentRow(id="run-1", name="busy", connection_id="x", org_id="00Dxx0000001", status="running", scope={"areaIds": ["area-1"]}))
        db.add(AssessmentRow(id="run-other", name="other org", connection_id="y", org_id="00Dyy0000002", status="running", scope={"areaIds": ["area-1"]}))
        db.commit()
    assert start(client).status_code == 409
    assert client.post(f"{API}/assessments/run-1/cancel").json()["status"] == "cancelled"
    assert client.post(f"{API}/assessments/run-1/cancel").status_code == 409
    assert client.get(f"{API}/assessments/run-1/results").status_code == 404


def test_update_finding(client, sf):
    connect(client)
    aid = start(client).json()["id"]
    f = client.get(f"{API}/assessments/{aid}/findings").json()["items"][0]
    r = client.patch(f"{API}/findings/{f['id']}", json={"status": "in-review", "notes": "  Owner: Jane  "}).json()
    assert r["status"] == "in-review" and r["notes"] == "Owner: Jane"
    assert client.patch(f"{API}/findings/{f['id']}", json={"status": "bogus"}).status_code == 422
    assert client.patch(f"{API}/findings/nope", json={"status": "resolved"}).status_code == 404


def test_expired_session_fails_run(client, sf):
    connect(client)
    sf.valid_access, sf.refresh_ok = set(), False
    aid = start(client).json()["id"]
    a = client.get(f"{API}/assessments/{aid}").json()
    assert a["status"] == "failed" and "timed out" in a["errorMessage"]
    assert client.get(f"{API}/salesforce/connection").json()["status"] == "expired"


def test_list_sorted_and_filtered(client, sf):
    connect(client)
    aid = start(client).json()["id"]
    r = client.get(f"{API}/assessments", params={"status": "completed", "sort": "-completedAt"}).json()
    assert r["total"] == 1 and r["items"][0]["id"] == aid and r["items"][0]["scope"]["areaIds"] == ["area-1", "area-2"]


def test_only_chosen_objects_are_checked(client, sf):
    connect(client)
    aid = start(client, objects=["Contact"]).json()["id"]
    res = client.get(f"{API}/assessments/{aid}/results").json()
    assert [o["name"] for o in res["objects"]] == ["Contact"]
    ind = {i["label"] for a in res["areas"] for i in a["indicators"]}
    assert "Duplicate Contacts" in ind and "Duplicate Accounts" not in ind and "Accounts Without Contacts" not in ind
    assert not any(" FROM Account" in q or " FROM Lead" in q for q in sf.soql)
    findings = client.get(f"{API}/assessments/{aid}/findings").json()["items"]
    assert findings and all(f["objectName"] in ("Contact", None) for f in findings)


def test_custom_object_gets_generic_checks(client, sf):
    connect(client)
    aid = start(client, objects=["Invoice__c"]).json()["id"]
    a = client.get(f"{API}/assessments/{aid}").json()
    assert a["status"] == "completed", a
    res = client.get(f"{API}/assessments/{aid}/results").json()
    inv = res["objects"][0]
    assert inv["name"] == "Invoice__c" and inv["label"] == "Invoices" and inv["records"] == 40 and inv["duplicates"] == 3
    names = [f["name"] for f in client.get(f"{API}/assessments/{aid}/findings").json()["items"]]
    assert "Duplicate Invoices" in names and "Outdated-looking fields on Invoices" in names
    area1 = next(x for x in res["areas"] if x["areaId"] == "area-1")
    assert area1["status"] == "assessed" and area1["message"] is None


def test_rejects_bad_object_names(client):
    connect(client)
    assert start(client, objects=["Account; DELETE"]).status_code == 422
    assert start(client, objects=[f"Obj{i}__c" for i in range(16)]).status_code == 422


def test_checking_one_area_keeps_the_other_areas_results(client, sf):
    connect(client)
    first = start(client, areas=("area-1",)).json()["id"]
    f1 = next(f for f in client.get(f"{API}/assessments/{first}/findings").json()["items"] if f["areaId"] == "area-1")
    client.patch(f"{API}/findings/{f1['id']}", json={"status": "in-review"})

    second = start(client, areas=("area-2",)).json()["id"]
    res = client.get(f"{API}/assessments/{second}/results").json()
    areas = {a["areaId"]: a for a in res["areas"]}
    assert areas["area-1"]["status"] == "assessed" and areas["area-1"]["sourceAssessmentId"] == first
    assert areas["area-2"]["status"] == "assessed" and areas["area-2"]["sourceAssessmentId"] == second
    assert areas["area-1"]["checkedAt"] <= areas["area-2"]["checkedAt"]
    assert res["categories"][0]["score"] == round((areas["area-1"]["score"] + areas["area-2"]["score"]) / 2)

    findings = client.get(f"{API}/assessments/{second}/findings").json()["items"]
    assert {f["areaId"] for f in findings} == {"area-1", "area-2"}
    carried = next(f for f in findings if f["id"] == f1["id"])
    assert carried["status"] == "in-review"  # same problem, not a copy
    objs = {o["name"]: o for o in res["objects"]}
    assert objs["Account"]["duplicates"] == 2 and objs["Account"]["completeness"] is not None  # from check 1 and check 2
    assert objs["Account"]["problems"] == sum(1 for f in findings if f["objectName"] == "Account")
    latest = client.get(f"{API}/assessments/{second}").json()
    assert latest["findingsCount"] == len(findings) and latest["overallScore"] == res["overallScore"]

    # Checking Area 1 again replaces only Area 1's result and problems.
    third = start(client, areas=("area-1",)).json()["id"]
    areas3 = {a["areaId"]: a["sourceAssessmentId"] for a in client.get(f"{API}/assessments/{third}/results").json()["areas"]}
    assert areas3 == {"area-1": third, "area-2": second}
    ids3 = {f["id"] for f in client.get(f"{API}/assessments/{third}/findings").json()["items"]}
    assert f1["id"] not in ids3



def _findings(client, aid):
    return {f["name"]: f for f in client.get(f"{API}/assessments/{aid}/findings").json()["items"]}


def test_problems_list_and_export_their_records(client, sf):
    connect(client)
    aid = start(client, areas=("area-1",)).json()["id"]
    found = _findings(client, aid)

    no_email = found["Contacts missing key fields"]
    assert no_email["recordsAvailable"] is True and no_email["fixUrl"].endswith("/FieldsAndRelationships/view")
    page = client.get(f"{API}/findings/{no_email['id']}/records").json()
    assert page["object"] == "Contact" and [r["id"] for r in page["records"]] == ["003000000000001AAA", "003000000000002AAA"]
    assert page["recordUrlPrefix"].endswith("/")
    assert any("FROM Contact WHERE (Email = null OR Phone = null)" in q for q in sf.soql)  # exactly the records the check counted

    csv = client.get(f"{API}/findings/{no_email['id']}/records.csv")
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    lines = csv.text.lstrip("\ufeff").splitlines()
    assert lines[0].endswith("Salesforce link") and lines[1].endswith("/003000000000001AAA") and len(lines) == 3

    dupes = found["Duplicate Accounts"]
    assert dupes["affectedRecords"] == 2 and dupes["fixUrl"].endswith("/lightning/setup/DuplicateRules/home")
    client.get(f"{API}/findings/{dupes['id']}/records")
    q = next(x for x in sf.soql if x.startswith("SELECT") and "FROM Account WHERE Id IN" in x)
    assert "'001000000000001AAA'" in q and "'001000000000005AAA'" in q
    assert "'001000000000003AAA'" not in q and "'001000000000006AAA'" not in q  # different state spelling; Initech has no copy
    assert "match another record on Name, Website, Phone, BillingState, BillingCity (2 groups)" in dupes["description"]


def test_second_check_compares_and_keeps_triage(client, sf):
    connect(client)
    first = start(client, areas=("area-1",)).json()["id"]
    f1 = _findings(client, first)
    assert all(f["change"] == "new" for f in f1.values())
    client.patch(f"{API}/findings/{f1['Contacts missing key fields']['id']}", json={"status": "in-review", "notes": "Marketing owns this"})
    client.patch(f"{API}/findings/{f1['Duplicate Accounts']['id']}", json={"status": "resolved"})

    lead_fields = ("LastName", "Title", "Company", "Email", "Phone", "State", "City", "PostalCode", "LeadSource")
    saved = dict(MISSING)
    MISSING.update({("Lead", f): 0 for f in lead_fields})  # leads fixed …
    MISSING[("Contact", "Email")] = 60  # … contacts got worse
    try:
        second = start(client, areas=("area-1",)).json()["id"]
    finally:
        MISSING.clear()
        MISSING.update(saved)
    f2 = _findings(client, second)
    no_email = f2["Contacts missing key fields"]
    assert no_email["change"] == "worse" and no_email["previousAffected"] == 40 and no_email["affectedRecords"] == 60
    assert no_email["status"] == "in-review" and no_email["notes"] == "Marketing owns this"  # triage carried over
    assert f2["Duplicate Accounts"]["change"] == "same" and f2["Duplicate Accounts"]["status"] == "open"  # came back: reopened
    resolved = client.get(f"{API}/assessments/{second}/results").json()["resolved"]
    assert [r["name"] for r in resolved] == ["Open Leads missing key fields"] and resolved[0]["previousAffected"] == 10


def test_every_problem_links_to_the_measure_that_raised_it(client, sf):
    connect(client)
    aid = start(client, areas=("area-1", "area-2")).json()["id"]
    res = client.get(f"{API}/assessments/{aid}/results").json()
    labels = {(a["areaId"], i["label"]) for a in res["areas"] for i in a["indicators"]}
    found = client.get(f"{API}/assessments/{aid}/findings", params={"pageSize": 500}).json()["items"]
    assert found and all((f["areaId"], f["measure"]) in labels for f in found)
    dup = next(f for f in found if f["name"] == "Duplicate Accounts")
    assert dup["measure"] == "Duplicate Accounts"


def test_older_problems_find_their_measure_by_the_same_records(client, sf):
    from app.models import FindingRow

    connect(client)
    aid = start(client, areas=("area-1",)).json()["id"]
    with SessionLocal() as db:  # as if saved before problems recorded their measure
        for f in db.query(FindingRow).filter(FindingRow.assessment_id == aid):
            f.measure = None
        db.commit()
    found = client.get(f"{API}/assessments/{aid}/findings", params={"pageSize": 500}).json()["items"]
    missing = [f for f in found if f["name"].endswith("missing key fields")]
    assert missing and all(f["measure"].startswith("Missing Key Fields (") for f in missing)
    assert next(f for f in found if f["name"] == "Contacts missing key fields")["measure"] == "Missing Key Fields (Contacts)"
    assert next(f for f in found if f["name"] == "Duplicate Accounts")["measure"] == "Duplicate Accounts"


def test_field_scores_saved_in_an_older_shape_are_skipped():
    from app.schemas import IndicatorValue

    old = {"label": "Duplicate Accounts", "value": 3, "unit": "count", "direction": "lower-better",
           "fieldScores": [{"field": "Website", "label": "Website", "filled": 90.0, "unique": 16.7, "consistent": 83.3}]}
    assert IndicatorValue.model_validate(old).field_scores is None
    new = {**old, "fieldScores": [{"field": "Website", "label": "Website", "count": 5, "of": 6, "pct": 83.3}]}
    assert IndicatorValue.model_validate(new).field_scores[0].count == 5
