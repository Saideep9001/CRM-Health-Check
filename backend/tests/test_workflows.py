"""Workflows & Automation checks (areas 3–7), run against a fake sales org with known data."""
import re
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.salesforce import explorer

from .conftest import FakeSalesforce, connect

API = "/api/v1"
AREAS = ("area-3", "area-4", "area-5", "area-6", "area-7")


def _f(name, **kw):
    return {"name": name, "label": kw.pop("label", name), "type": kw.pop("type", "string"), "filterable": True, "groupable": True, "nillable": True, **kw}


DESCRIBE = {
    "Account": [_f("Id", type="id"), _f("Name"), _f("ParentId", type="reference"), _f("Industry"), _f("Phone"), _f("Type")],
    "Contact": [_f("Id", type="id"), _f("LastName"), _f("Email"), _f("AccountId", type="reference")],
    "Lead": [_f("Id", type="id"), _f("Company"), _f("Email"), _f("Phone"), _f("IsConverted", type="boolean"),
             _f("LeadSource", type="picklist", picklistValues=[{"value": "Web", "active": True}, {"value": "Phone Inquiry", "active": True}])],
    "Opportunity": [_f("Id", type="id"), _f("Amount", type="currency"), _f("NextStep"), _f("LeadSource"), _f("Type"), _f("StageName"),
                    _f("LastStageChangeDate", type="datetime"), _f("Description", type="textarea", filterable=False),
                    _f("Loss_Reason__c", type="picklist", custom=True, label="Loss Reason")],
    "Task": [_f("Id", type="id")], "Event": [_f("Id", type="id")], "EmailTemplate": [_f("Id", type="id")], "User": [_f("Id", type="id")],
}
USERS = {"005000000000001": "Ann Lee", "005000000000002": "Bob Ray", "005000000000003": "Agentforce Agent User1"}

# COUNT() answers: first rule whose substrings all appear in the query wins.
COUNTS = [
    (("FROM Lead", "Owner.Type = 'Queue'", "LAST_N_DAYS:10"), 3),  # stuck in a queue 10+ days (Critical, with a 5-day setting)
    (("FROM Lead", "Owner.Type = 'Queue'", "LAST_N_DAYS:5"), 8),  # stuck in a queue 5+ days
    (("FROM Lead", "Owner.Type = 'Queue'"), 12),
    (("FROM Lead", "Owner.Type = 'User'"), 40),
    (("FROM Lead", "LeadSource IN", "LAST_N_DAYS:90"), 25),
    (("FROM Lead", "LeadSource IN", "LAST_N_DAYS:14"), 0),
    (("FROM Lead", "LeadHistory WHERE Field = 'Status' AND"), 20),  # stale: no Status change (Lead History)
    (("FROM Lead", "LastModifiedDate < LAST_N_DAYS"), 20),  # stale, where Status changes aren't tracked
    (("CloseDate < TODAY",), 8),
    (("NOT IN (SELECT OpportunityId",), 15),
    (("LastStageChangeDate",), 10),
    (("NextStep = null",), 18),
    (("IsWon = false", "Loss_Reason__c = null"), 6),
    (("IsWon = false",), 10),
    (("FROM Opportunity", "LastActivityDate"), 22),
    (("Amount = null",), 4),
    (("FROM Account", "NOT IN (SELECT AccountId FROM Contact"), 30),
    (("ParentId != null",), 0),
    (("FROM Contact", "AccountId = null"), 9),
    (("FROM EmailTemplate",), 2),
    (("= null",), 5),
    (("FROM Account",), 100), (("FROM Contact",), 120), (("FROM Lead",), 60), (("FROM Opportunity",), 40),
]


class FakeSalesOrg(FakeSalesforce):
    tooling_ok = True

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        if request.headers.get("authorization", "").removeprefix("Bearer ") not in self.valid_access:
            return super().handler(request)
        if url.path.endswith("/sobjects"):
            return httpx.Response(200, json={"sobjects": [{"name": n, "label": n, "labelPlural": n + "s", "queryable": True, "retrieveable": True} for n in DESCRIBE]})
        if m := re.search(r"/sobjects/(\w+)/describe$", url.path):
            return httpx.Response(200, json={"name": m[1], "fields": DESCRIBE[m[1]]})
        if url.path.endswith("/query"):
            q = parse_qs(url.query)["q"][0]
            if "FROM Organization" in q:
                return super().handler(request)
            self.soql.append(q)
            if "/tooling/" in url.path:
                if not self.tooling_ok:
                    return httpx.Response(403, json=[{"message": "Insufficient access", "errorCode": "INSUFFICIENT_ACCESS"}])
                return httpx.Response(200, json={"records": self.tooling(q), "done": True})
            return httpx.Response(200, json={"records": self.records(q), "totalSize": self.count(q), "done": True})
        return super().handler(request)

    @staticmethod
    def count(q: str) -> int:
        return next(n for subs, n in COUNTS if all(s in q for s in subs)) if q.startswith("SELECT COUNT()") else 1

    @staticmethod
    def records(q: str) -> list[dict]:
        if q.startswith("SELECT COUNT()"):
            return []
        if "SUM(Amount) a FROM" in q and "GROUP BY" not in q:
            return [{"a": 50000}]
        if "GROUP BY Owner.Name" in q:
            return [{"o": "Jane Doe", "c": 5, "a": 1000}]
        if q.startswith("SELECT OwnerId o"):
            if "FROM Task" in q:
                return [{"o": "005000000000001", "c": 3}]
            if "FROM Event" in q:
                return []
            return [{"o": u, "c": 2} for u in USERS] + [{"o": "00G000000000001", "c": 4}]
        if "FROM User" in q:
            return [{"Id": i, "Name": n, "UserType": "Standard", "Profile": {"Name": "Sales"}} for i, n in USERS.items()]
        if "Owner.Type = 'Queue' ORDER BY CreatedDate" in q:
            return [{"Name": "Old Lead", "CreatedDate": "2026-01-01T00:00:00.000+0000"}]
        if q.startswith("SELECT Name, StageName"):
            return [{"Name": "Big Deal", "StageName": "Proposal", "Amount": 90000}]
        if q.startswith("SELECT Id, NextStep, Description FROM Opportunity"):
            return [{"NextStep": "tbd"}, {"Description": "test"}, {"NextStep": "Call Monday", "Description": "Real notes"}]
        if m := re.search(r"SELECT (\w+) v, COUNT\(Id\) c FROM (\w+)", q):
            return {("Company", "Lead"): [{"v": "[not provided]", "c": 3}, {"v": "Acme", "c": 5}], ("Name", "Account"): [{"v": "test", "c": 1}]}.get((m[1], m[2]), [])
        if "FROM AssignmentRule" in q or "FROM FlowDefinitionView" in q:
            return []
        if "FROM OpportunityStage" in q:
            return [{"Id": f"01J00000000000{i}AAA", "MasterLabel": s, "ApiName": s, "IsClosed": False} for i, s in enumerate(("Prospecting", "Proposal"))] + [{"MasterLabel": "Closed Won", "IsClosed": True}]
        return []

    @staticmethod
    def tooling(q: str) -> list[dict]:
        if "FROM ValidationRule" in q and "'Opportunity'" in q:
            return [{"ValidationName": "Amount_Required", "Active": True, "ErrorMessage": "Error"}]
        return []


@pytest.fixture
def sf():
    explorer.clear_cache()
    return FakeSalesOrg()


def run(client, **scope):
    conn = client.get(f"{API}/salesforce/connection").json()
    body = {"categoryIds": ["workflows"], "areaIds": list(AREAS), "staleLeadDays": 14, "stuckOpportunityDays": 45, "queueLeadDays": 5, **scope}
    aid = client.post(f"{API}/assessments", json={"name": "Workflows", "connectionId": conn["id"], "scope": body}).json()["id"]
    a = client.get(f"{API}/assessments/{aid}").json()
    res = client.get(f"{API}/assessments/{aid}/results").json()
    findings = client.get(f"{API}/assessments/{aid}/findings").json()["items"]
    return a, res, findings


def test_all_workflow_areas(client, sf):
    connect(client)
    a, res, findings = run(client)
    assert a["status"] == "completed", a
    areas = {x["areaId"]: x for x in res["areas"]}
    assert all(areas[i]["status"] == "assessed" and areas[i]["score"] is not None for i in AREAS), areas
    ind = {i["label"]: i["value"] for x in res["areas"] for i in x["indicators"]}
    assert set(ind) >= {"Stuck Leads in Queue", "Leads Not Assigned to Any Queue"}
    assert ind["Stuck Leads in Queue"] == 8 and ind["Leads Not Assigned to Any Queue"] == 40
    assert {i["label"] for i in areas["area-3"]["indicators"]} == {"Stuck Leads in Queue", "Leads Not Assigned to Any Queue"}
    assert ind["Missing Contact Roles"] == 15 and ind["Orphaned Contacts"] == 9 and ind["Missing Account relationships"] == 30
    assert ind["Account hierarchy issues"] == 2  # no parents on 100 accounts; no AccountContactRelation
    assert ind["Stuck Opportunities"] == 10 and ind["Missing Next Steps"] == 18 and ind["Missing Closed Lost reasons"] == 6
    assert ind["Sales stage guidance gaps"] == 2  # no Path: both open stages unguided
    assert ind["Missing sales activities"] == 1  # Bob owns work but logged nothing
    assert ind["Web-to-Lead issues"] == 1 and ind["Email template availability"] == 2 and ind["Activity capture gaps"] == 22
    assert ind["Missing validation rules"] == 3 and ind["Potential junk data"] == 6  # 2 opps + 3 leads + 1 account
    assert res["salesProcessScore"] == res["categories"][0]["score"] and res["categories"][0]["categoryId"] == "workflows"

    assert not any("unexpected error" in (x["message"] or "") for x in res["areas"]), res["areas"]
    names = {f["name"]: f for f in findings}
    assert "Placeholder or junk values" in names
    assert "Website leads have stopped arriving" in names and names["Website leads have stopped arriving"]["severity"] == "critical"
    assert "Bob Ray" in names["Reps with no logged activity"]["description"]
    stuck = names["Leads stuck in a queue"]
    assert stuck["severity"] == "critical" and "3 of them for more than 10 days" in stuck["description"] and "Jane Doe" in stuck["description"]
    assert "“Big Deal” (Proposal, 90,000)" in names["Stuck deals"]["description"]
    assert "Loss Reason" in names["Lost deals with no reason"]["description"]
    assert "Unclear validation error messages" in names
    assert names["Open deals with no contact roles"]["objectName"] == "Opportunity"
    assert all(q.lstrip().upper().startswith("SELECT") for q in sf.soql)
    assert any("LAST_N_DAYS:5" in q and "Owner.Type = 'Queue'" in q and "LeadHistory WHERE Field = 'Owner'" in q for q in sf.soql)  # queue setting used
    assert any("LAST_N_DAYS:45" in q and "LastStageChangeDate" in q for q in sf.soql)  # stuck-deal setting used


def test_setup_checks_skipped_without_setup_access(client, sf):
    sf.tooling_ok = False
    connect(client)
    a, res, findings = run(client)
    assert a["status"] == "completed"
    areas = {x["areaId"]: x for x in res["areas"]}
    labels = {i["label"] for i in areas["area-7"]["indicators"]}
    assert "Missing validation rules" not in labels and "Potential junk data" in labels  # record checks still ran
    assert "View Setup" in (areas["area-7"]["message"] or "")
    assert areas["area-3"]["status"] == "assessed"


def test_path_guidance_matched_by_stage_id(client, sf):
    """Path is on; only "Prospecting" (stage id 01J000000000000) has guidance text."""
    sf.tooling = staticmethod(lambda q: (
        [{"Id": "0Ph000000000001AAA", "SobjectType": "Opportunity", "IsActive": True}] if "FROM PathAssistant " in q + " " and "StepInfo" not in q
        else [{"DeveloperName": "X1_01J000000000000AAA_null_Opportunity_StageName", "Info": "<p>Qualify budget</p>"},
              {"DeveloperName": "X2_01J000000000001AAA_null_Opportunity_StageName", "Info": "<p> </p>"},
              {"DeveloperName": "X3_01J000000000001AAA_null_Lead_Status", "Info": "<p>Lead tip</p>"}] if "StepInfo" in q
        else []))
    connect(client)
    _, res, findings = run(client)
    ind = {i["label"]: i["value"] for x in res["areas"] for i in x["indicators"]}
    assert ind["Sales stage guidance gaps"] == 1
    gap = next(f for f in findings if f["name"] == "Sales stages without guidance")
    assert "Proposal" in gap["description"] and "Prospecting" not in gap["description"]
