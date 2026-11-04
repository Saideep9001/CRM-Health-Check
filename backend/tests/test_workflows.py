"""Workflows & Automation checks (areas 3–7), run against a fake sales org with known data."""
import re
import sys
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
             _f("LeadSource", label="Lead Source", type="picklist", picklistValues=[{"value": "Web", "active": True}, {"value": "Phone Inquiry", "active": True}])],
    "Opportunity": [_f("Id", type="id"), _f("Amount", type="currency"), _f("NextStep"), _f("LeadSource"), _f("Type"), _f("StageName"),
                    _f("LastStageChangeDate", type="datetime"), _f("Description", type="textarea", filterable=False),
                    _f("Loss_Reason__c", type="picklist", custom=True, label="Loss Reason")],
    "Task": [_f("Id", type="id")], "Event": [_f("Id", type="id")], "EmailTemplate": [_f("Id", type="id")], "User": [_f("Id", type="id")],
}
USERS = {"005000000000001": "Ann Lee", "005000000000002": "Bob Ray", "005000000000003": "Agentforce Agent User1"}

# Lead Assignment Rules (Metadata API): "Standard" is active (Web leads to the Web queue, phone enquiries to Ann); "Old Rule"
# (everything to Bob) and "Partner Rule" (partner leads to the Partner queue) are inactive.
RULES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns="http://soap.sforce.com/2006/04/metadata"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><soapenv:Body><readMetadataResponse><result>
<records xsi:type="AssignmentRules"><fullName>Lead</fullName>
 <assignmentRule><fullName>Old Rule</fullName><active>false</active><ruleEntry><assignedTo>bob@acme.test</assignedTo><assignedToType>User</assignedToType></ruleEntry></assignmentRule>
 <assignmentRule><fullName>Partner Rule</fullName><active>false</active>
  <ruleEntry><assignedTo>Partner_Queue</assignedTo><assignedToType>Queue</assignedToType>
   <criteriaItems><field>Lead.LeadSource</field><operation>equals</operation><value>Partner</value></criteriaItems></ruleEntry></assignmentRule>
 <assignmentRule><fullName>Standard</fullName><active>true</active>
  <ruleEntry><assignedTo>Web_Queue</assignedTo><assignedToType>Queue</assignedToType>
   <criteriaItems><field>Lead.LeadSource</field><operation>equals</operation><value>Web</value></criteriaItems></ruleEntry>
  <ruleEntry><assignedTo>ann@acme.test</assignedTo><assignedToType>User</assignedToType>
   <criteriaItems><field>Lead.LeadSource</field><operation>equals</operation><value>Phone Inquiry,Phone</value></criteriaItems></ruleEntry>
 </assignmentRule></records></result></readMetadataResponse></soapenv:Body></soapenv:Envelope>"""
# Opportunity page layouts (Metadata API): the Contact Roles related list is on the first, missing from the second.
LAYOUT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns="http://soap.sforce.com/2006/04/metadata"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><soapenv:Body><readMetadataResponse><result>
<records xsi:type="Layout"><fullName>Opportunity-Opportunity Layout</fullName>
 <relatedLists><relatedList>RelatedContactRoleList</relatedList></relatedLists><relatedLists><relatedList>RelatedNoteList</relatedList></relatedLists></records>
<records xsi:type="Layout"><fullName>Opportunity-Sales %28Marketing%29 Layout</fullName>
 <relatedLists><relatedList>RelatedNoteList</relatedList></relatedLists></records>
</result></readMetadataResponse></soapenv:Body></soapenv:Envelope>"""
# Contact Roles on open deals: Pat is on two (Multi-Deal Contacts), Sam on one.
ROLES = [
    {"ContactId": "003000000000001", "Role": "Influencer", "Opportunity": {"Name": "Acme Renewal"}},
    {"ContactId": "003000000000001", "Role": "Decision Maker", "Opportunity": {"Name": "Globex Expansion"}},
    {"ContactId": "003000000000002", "Role": None, "Opportunity": {"Name": "Acme Renewal"}},
]
LEADS = [  # open Leads read to compare with the rules
    {"Id": "00Q000000000001", "OwnerId": "00G000000000002", "Owner": {"Name": "Web Queue"}, "CreatedById": "005000000000009", "LeadSource": "Web"},  # active entry 1
    {"Id": "00Q000000000002", "OwnerId": "005000000000002", "Owner": {"Name": "Bob Ray"}, "CreatedById": "005000000000002", "LeadSource": "Partner"},  # no match, waiting
    {"Id": "00Q000000000003", "OwnerId": "005000000000001", "Owner": {"Name": "Ann Lee"}, "CreatedById": "005000000000009", "LeadSource": None},  # no match, assigned by hand
    {"Id": "00Q000000000004", "OwnerId": "005000000000001", "Owner": {"Name": "Ann Lee"}, "CreatedById": "005000000000009", "LeadSource": "phone"},  # active entry 2
]

# COUNT() answers: first rule whose substrings all appear in the query wins.
COUNTS = [
    (("FROM Lead", "OwnerId IN ('00G000000000003AAA', '00G000000000002AAA')"), 4),  # in the inactive queues, with no active rule
    (("FROM Lead", "OwnerId IN ('00G000000000003AAA')"), 1),  # in the inactive Partner queue
    (("FROM Lead", "Owner.Type = 'Queue'", "LAST_N_DAYS:7"), 3),  # in a queue more than 7 days (Critical)
    (("FROM Lead", "Owner.Type = 'Queue'", "LAST_N_DAYS:5"), 5),  # more than 5 days (High)
    (("FROM Lead", "Owner.Type = 'Queue'", "LAST_N_DAYS:3"), 8),  # more than 3 days (the card's threshold)
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
    rules_xml = RULES_XML

    def __init__(self):
        super().__init__()
        self.soap: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        if request.headers.get("authorization", "").removeprefix("Bearer ") not in self.valid_access:
            return super().handler(request)
        if url.path.startswith("/services/Soap/m/"):
            self.soap.append(request.content.decode())
            xml = LAYOUT_XML if "<met:type>Layout</met:type>" in self.soap[-1] else self.rules_xml
            return httpx.Response(200, text=xml, headers={"Content-Type": "text/xml"})
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
        if q.startswith("SELECT Id, OwnerId, Owner.Name, CreatedById, CreatedDate, LeadSource FROM Lead"):
            return LEADS
        if "Queue.DeveloperName FROM QueueSobject" in q:  # Lead queues with API names: the active rule routes to Web_Queue only
            return [{"QueueId": "00G000000000002AAA", "Queue": {"Name": "Web Queue", "DeveloperName": "Web_Queue"}},
                    {"QueueId": "00G000000000003AAA", "Queue": {"Name": "Partner Queue", "DeveloperName": "Partner_Queue"}}]
        if "FROM QueueSobject" in q:  # Lead queues; "Jane Doe" isn't listed, so it's found by name
            return [{"QueueId": "00G000000000002AAA", "Queue": {"Name": "Web Queue"}}]
        if "FROM Group WHERE Type = 'Queue' AND Name IN" in q:
            return [{"Id": "00G000000000001AAA", "Name": "Jane Doe"}] if "'Jane Doe'" in q else []
        if "FROM LeadHistory WHERE Field = 'Owner' AND LeadId IN" in q:
            return [{"LeadId": "00Q000000000003"}]  # its owner was changed after it was created
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
        if "FROM AssignmentRule WHERE SobjectType = 'Lead'" in q:  # rule ids, for links into Setup
            return [{"Id": "01Q000000000001AAA", "Name": "Partner Rule"}]
        if q.startswith("SELECT ContactId, Account.Name, IsDirect FROM AccountContactRelation WHERE ContactId IN"):
            return [{"ContactId": "003000000000001AAA", "Account": {"Name": "OakStone Retail Group"}, "IsDirect": True},
                    {"ContactId": "003000000000001AAA", "Account": {"Name": "Titan Manufacturing Corp"}, "IsDirect": False}]
        if "FROM OpportunityContactRole WHERE Opportunity.IsClosed = false" in q:
            return ROLES
        if "FROM FlowDefinitionView" in q:
            return []
        if "FROM OpportunityStage" in q:
            return [{"Id": f"01J00000000000{i}AAA", "MasterLabel": s, "ApiName": s, "IsClosed": False} for i, s in enumerate(("Prospecting", "Proposal"))] + [{"MasterLabel": "Closed Won", "IsClosed": True}]
        return []

    @staticmethod
    def tooling(q: str) -> list[dict]:
        if q.startswith("SELECT Name, NamespacePrefix FROM Layout WHERE TableEnumOrId = 'Opportunity'"):
            return [{"Name": "Opportunity Layout", "NamespacePrefix": None}, {"Name": "Sales (Marketing) Layout", "NamespacePrefix": None}]
        if "FROM ValidationRule" in q and "'Opportunity'" in q:
            return [{"ValidationName": "Amount_Required", "Active": True, "ErrorMessage": "Error"}]
        return []


@pytest.fixture
def sf():
    explorer.clear_cache()
    return FakeSalesOrg()


def run(client, **scope):
    conn = client.get(f"{API}/salesforce/connection").json()
    body = {"categoryIds": ["workflows"], "areaIds": list(AREAS), "staleLeadDays": 14, "stuckOpportunityDays": 45, **scope}
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
    assert [i["label"] for i in areas["area-3"]["indicators"]] == ["Stuck Queue-Owned Leads", "Inactive Lead Assignment Rules", "Lead Assignment Criteria Mismatches"]
    assert ind["Stuck Queue-Owned Leads"] == 8  # in a queue more than 3 days
    assert ind["Inactive Lead Assignment Rules"] == 1 and ind["Lead Assignment Criteria Mismatches"] == 2  # 1 Lead in an inactive queue
    rule_reads = [x for x in sf.soap if "<met:type>AssignmentRules</met:type>" in x]
    assert len(rule_reads) == 1 and "<fullNames>Lead</fullNames>" in rule_reads[0]  # read once for both cards
    assert [i["label"] for i in areas["area-4"]["indicators"]] == ["Opportunities Without Contact Roles", "Orphaned Contacts",
                                                                   "Contacts to Multiple Accounts", "Multi-Deal Contacts"]
    assert ind["Opportunities Without Contact Roles"] == 15 and ind["Orphaned Contacts"] == 9
    assert ind["Contacts to Multiple Accounts"] == 0 and ind["Multi-Deal Contacts"] == 1  # the feature is off; Pat is on 2 open deals
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
    assert names["Leads with no assignment path"]["description"] == ("1 open Leads match no entry of the active Lead Assignment Rule “Standard” and "
                                                                     "haven’t been assigned by hand; 1 more were assigned by hand. Most are with: Bob Ray (1).")
    stuck = names["Leads stuck in a queue"]
    assert stuck["severity"] == "critical" and "8 open Leads have waited in a queue more than 3 days" in stuck["description"]
    assert "3 of them more than 7 days" in stuck["description"] and "Jane Doe" in stuck["description"]
    review = names["Inactive Lead Assignment Rules match existing Leads"]
    assert review["severity"] == "low" and review["affectedRecords"] == 4 and "“Old Rule” (4), “Partner Rule” (1)" in review["description"]
    assert "“Big Deal” (Proposal, 90,000)" in names["Stuck deals"]["description"]
    assert "Loss Reason" in names["Lost deals with no reason"]["description"]
    assert "Unclear validation error messages" in names
    assert names["Open deals with no contact roles"]["objectName"] == "Opportunity"
    assert names["Contacts can’t be related to multiple Accounts"]["severity"] == "low"
    assert "isn’t on 1 of 2 Opportunity page layouts (Sales (Marketing) Layout)" in names["Contact Roles missing from Opportunity layouts"]["description"]
    assert all(q.lstrip().upper().startswith("SELECT") for q in sf.soql)
    assert any("LAST_N_DAYS:7" in q and "Owner.Type = 'Queue'" in q and "LeadHistory WHERE Field = 'Owner'" in q for q in sf.soql)  # waited 7+ days
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


def _lead_query(sf):
    return next(q for q in reversed(sf.soql) if "FROM Lead WHERE" in q and "LeadHistory WHERE Field = 'Owner' AND LeadId" not in q)


def test_stuck_queue_owned_leads_by_queue_and_days(client, sf):
    connect(client)
    a, res, _ = run(client)
    card = next(i for x in res["areas"] for i in x["indicators"] if i["label"] == "Stuck Queue-Owned Leads")
    assert dict(card["criteria"])["By days in queue"] == "More than 3 days: 8 (Medium) · more than 5: 5 (High) · more than 7: 3 (Critical)"
    base = f"{API}/assessments/{a['id']}/areas/area-3"
    params = {"label": "Stuck Queue-Owned Leads", "object": "Lead"}
    queues = client.get(f"{base}/indicator-queues", params=params)
    # every Lead queue, the empty ones too (0), most stuck Leads first; counted past the card's threshold
    assert queues.status_code == 200 and queues.json() == [
        {"id": "00G000000000001AAA", "name": "Jane Doe", "count": 5}, {"id": "00G000000000002AAA", "name": "Web Queue", "count": 0}]
    grouped = next(q for q in sf.soql if "GROUP BY Owner.Name" in q and "Owner.Type = 'Queue'" in q and "LAST_N_DAYS:3" in q)
    assert "LeadHistory WHERE Field = 'Owner' AND CreatedDate = LAST_N_DAYS:3" in grouped

    for path in ("indicator-records", "indicator-records.csv"):
        assert client.get(f"{base}/{path}", params={**params, "queue": "00G000000000001AAA"}).status_code == 200
        q = _lead_query(sf)
        assert "FROM Lead WHERE IsConverted = false AND" in q and "AND OwnerId = '00G000000000001AAA'" in q  # sub-select not bracketed
        assert "CreatedDate < LAST_N_DAYS:3" in q  # the card's threshold by default
    assert client.get(f"{base}/indicator-records", params={**params, "days": 7}).status_code == 200
    assert "CreatedDate < LAST_N_DAYS:7" in _lead_query(sf) and "LAST_N_DAYS:3" not in _lead_query(sf)
    assert client.get(f"{base}/indicator-records", params={**params, "days": 0}).status_code == 200
    assert "LAST_N_DAYS" not in _lead_query(sf)  # every Lead in a queue
    assert client.get(f"{base}/indicator-records", params={**params, "days": 4}).status_code == 422
    assert client.get(f"{base}/indicator-records", params={**params, "queue": "x' OR Id != null"}).status_code == 422
    other = {"label": "Lead Assignment Criteria Mismatches", "object": "Lead"}
    assert client.get(f"{base}/indicator-records", params={**other, "queue": "00G000000000001AAA"}).status_code == 422
    assert client.get(f"{base}/indicator-records", params={**other, "days": 3}).status_code == 422
    assert client.get(f"{base}/indicator-queues", params=other).status_code == 422


def _page(monkeypatch, ids):
    page = {"object": "Lead", "columns": [{"name": "Name", "label": "Full Name", "type": "string"}, {"name": "OwnerId", "label": "Owner ID", "type": "reference"},
                                          {"name": "CreatedDate", "label": "Created Date", "type": "datetime"}],
            "total_size": len(ids), "next_cursor": None, "record_url_prefix": "https://acme.my.salesforce.com/",
            "records": [{"id": i, "values": {"Name": "Pat"}, "ref_names": {}} for i in ids]}
    monkeypatch.setattr(explorer, "records_matching", lambda *a, **k: page)


def test_criteria_mismatches_say_why_and_who_assigned_them(client, sf, monkeypatch):
    connect(client)
    a, res, _ = run(client)
    card = next(i for x in res["areas"] for i in x["indicators"] if i["label"] == "Lead Assignment Criteria Mismatches")
    crit = dict(card["criteria"])
    assert crit["Active rule entries"] == ("Entry 1: Lead Source equals “Web” → queue Web_Queue · "
                                           "Entry 2: Lead Source equals “Phone Inquiry” or “Phone” → ann@acme.test")
    assert crit["What's counted"] == "2 of 60 open Leads (3%) match no active rule entry: 1 with no assignment path, 1 already assigned by hand"
    _page(monkeypatch, ["00Q000000000002", "00Q000000000003"])
    params = {"label": "Lead Assignment Criteria Mismatches", "object": "Lead"}
    body = client.get(f"{API}/assessments/{a['id']}/areas/area-3/indicator-records", params=params).json()
    assert [c["label"] for c in body["columns"]] == ["Full Name", "Current Owner", "Created Date", "Assignment Gap Reason"]
    waiting, by_hand = (r["values"]["AssignmentGapReason"] for r in body["records"])
    assert waiting == ("No assignment path: still with Bob Ray — no active rule entry matches: Entry 1 needs Lead Source equals “Web” "
                       "(it’s “Partner”); Entry 2 needs Lead Source equals “Phone Inquiry” or “Phone” (it’s “Partner”)")
    assert by_hand.startswith("Assigned by hand to Ann Lee — no active rule entry matches: Entry 1 needs Lead Source equals “Web” (it’s blank)")
    csv = client.get(f"{API}/assessments/{a['id']}/areas/area-3/indicator-records.csv", params=params).text
    assert "Assignment Gap Reason" in csv.splitlines()[0] and "No assignment path" in csv


def test_inactive_rules_are_potential_matches(client, sf, monkeypatch):
    connect(client)
    a, res, _ = run(client)
    card = next(i for x in res["areas"] for i in x["indicators"] if i["label"] == "Inactive Lead Assignment Rules")
    crit = dict(card["criteria"])
    assert card["score"] is None and crit["Rules read"] == "3 Lead Assignment Rules in Setup; active: “Standard”"
    assert crit["“Old Rule” (inactive)"] == "1 entry; 4 open Leads would potentially match — Entry 1: no criteria (every Lead) → bob@acme.test: 4"
    assert crit["“Partner Rule” (inactive)"].endswith("Entry 1: Lead Source equals “Partner” → queue Partner_Queue: 1")
    rules = card["ruleList"]  # inactive rules (most potential matches first), then the active one; each links to Setup
    assert [(r["name"], r["active"], r["matches"]) for r in rules] == [("Old Rule", False, 4), ("Partner Rule", False, 1), ("Standard", True, None)]
    assert rules[1]["url"] == "https://acme.my.salesforce.com/lightning/setup/LeadRules/page?address=%2F01Q000000000001AAA"
    assert rules[0]["url"].endswith("/lightning/setup/LeadRules/home")  # no id found: the rules list
    assert rules[1]["entries"] == [{"order": 1, "criteria": "Lead Source equals “Partner”", "assignedTo": "queue Partner_Queue", "matches": 1}]
    assert rules[2]["entries"][1]["matches"] is None
    # the table: the open Leads in the inactive Lead queues (those the active rule never assigns to), one queue when picked
    assert crit["Inactive Lead queues"] == "Lead queues the active rule never assigns to: Partner Queue"
    base = f"{API}/assessments/{a['id']}/areas/area-3"
    params = {"label": "Inactive Lead Assignment Rules", "object": "Lead"}
    queues = client.get(f"{base}/indicator-queues", params=params)
    assert queues.status_code == 200 and [(q["id"], q["name"]) for q in queues.json()] == [("00G000000000003AAA", "Partner Queue")]
    assert client.get(f"{base}/indicator-records", params={**params, "queue": "00G000000000003AAA"}).status_code == 200
    q = _lead_query(sf)
    assert "FROM Lead WHERE IsConverted = false AND OwnerId IN ('00G000000000003AAA') AND OwnerId = '00G000000000003AAA'" in q
    assert client.get(f"{base}/indicator-records", params={**params, "queue": "00G000000000002AAA"}).status_code == 422  # active routing
    assert client.get(f"{base}/indicator-records", params={**params, "days": 3}).status_code == 422  # days are card 1's
    _page(monkeypatch, ["00Q000000000005"])
    body = client.get(f"{base}/indicator-records", params=params).json()
    assert body["columns"][-1]["label"] == "Potential Match (inactive rule)"
    assert body["records"][0]["values"]["PotentialMatch"] == "No inactive rule entry matches this Lead"


def test_no_active_rule_no_lead_has_a_routing_path(client, sf):
    sf.rules_xml = RULES_XML.replace("<fullName>Standard</fullName><active>true</active>", "<fullName>Standard</fullName><active>false</active>")
    connect(client)
    _, res, findings = run(client)
    ind = {i["label"]: i for x in res["areas"] for i in x["indicators"]}
    gap = ind["Lead Assignment Criteria Mismatches"]
    assert gap["value"] == 4 and dict(gap["criteria"])["Active rule"] == "None is active, so no Lead has an automatic routing path"
    assert ind["Inactive Lead Assignment Rules"]["value"] == 4  # no active rule: every Lead queue is inactive
    names = {f["name"]: f for f in findings}
    assert names["No active Lead Assignment Rule"]["severity"] == "high"
    assert names["Leads with no assignment path"]["affectedRecords"] == 3  # Ann's was assigned by hand


def test_picked_fields_are_the_columns(client, sf):
    connect(client)
    a, _, _ = run(client)
    base = f"{API}/assessments/{a['id']}/areas/area-3"
    params = {"label": "Stuck Queue-Owned Leads", "object": "Lead", "fields": "Email,Company,NoSuchField"}
    assert client.get(f"{base}/indicator-records", params=params).status_code == 200
    q = next(q for q in reversed(sf.soql) if "FROM Lead WHERE" in q and "LeadHistory WHERE Field = 'Owner' AND LeadId" not in q)
    assert q.startswith("SELECT Id, Email, Company FROM Lead")  # only the picked ones (unknown fields dropped), not topped up
    assert client.get(f"{base}/indicator-records.csv", params=params).status_code == 200
    too_many = ",".join(f"F{i}" for i in range(11))
    assert client.get(f"{base}/indicator-records", params={**params, "fields": too_many}).status_code == 422
    assert client.get(f"{base}/indicator-records", params={**params, "fields": "Email) FROM User --"}).status_code == 422


def test_inactive_queues_shown_with_no_inactive_rule(client, sf):
    import re as re_
    sf.rules_xml = re_.sub(r"<assignmentRule><fullName>(Old Rule|Partner Rule)</fullName>.*?</assignmentRule>", "", RULES_XML, flags=re_.S)
    connect(client)
    a, res, _ = run(client)
    card = next(i for x in res["areas"] for i in x["indicators"] if i["label"] == "Inactive Lead Assignment Rules")
    assert card["value"] == 1 and [r["name"] for r in card["ruleList"]] == ["Standard"]
    queues = client.get(f"{API}/assessments/{a['id']}/areas/area-3/indicator-queues", params={"label": card["label"], "object": "Lead"}).json()
    assert [q["name"] for q in queues] == ["Partner Queue"]


def test_contact_roles_layouts_and_fields(client, sf):
    connect(client)
    a, res, _ = run(client)
    card = next(i for x in res["areas"] for i in x["indicators"] if i["label"] == "Opportunities Without Contact Roles")
    crit = dict(card["criteria"])
    assert crit["Contact Roles on the page"] == "Missing from 1 of 2 Opportunity layouts: Sales (Marketing) Layout"
    assert crit["By owner"] == "Jane Doe: 5 (1,000)"
    layout_read = next(x for x in sf.soap if "<met:type>Layout</met:type>" in x)
    assert "<fullNames>Opportunity-Sales %28Marketing%29 Layout</fullNames>" in layout_read  # names encoded the Metadata API way
    base = f"{API}/assessments/{a['id']}/areas/area-4"
    params = {"label": "Opportunities Without Contact Roles", "object": "Opportunity"}
    assert client.get(f"{base}/indicator-queues", params=params).status_code == 422  # no owner chips
    assert client.get(f"{base}/indicator-records", params={**params, "queue": "005000000000001"}).status_code == 422
    assert client.get(f"{base}/indicator-records", params={**params, "fields": "Name,Amount"}).status_code == 200  # fields picked


def test_multi_deal_contacts_list_their_roles(client, sf, monkeypatch):
    connect(client)
    a, res, _ = run(client)
    card = next(i for x in res["areas"] for i in x["indicators"] if i["label"] == "Multi-Deal Contacts")
    crit = dict(card["criteria"])
    assert card["score"] is None and crit["What's counted"] == "1 of 2 Contacts with a role on an open deal are on more than one"
    assert crit["Their roles"] == "Influencer: 1; Decision Maker: 1"
    _page(monkeypatch, ["003000000000001"])
    body = client.get(f"{API}/assessments/{a['id']}/areas/area-4/indicator-records", params={"label": card["label"], "object": "Contact"}).json()
    assert [c["label"] for c in body["columns"]][:2] == ["Full Name", "Roles on Open Deals"] and body["columns"][1]["type"] == "lines"
    assert body["records"][0]["values"]["OpenDealRoles"] == "Influencer on Acme Renewal\nDecision Maker on Globex Expansion"


def test_contacts_to_multiple_accounts_when_on(client, sf, monkeypatch):
    monkeypatch.setitem(DESCRIBE, "AccountContactRelation", [_f("Id", type="id"), _f("ContactId", type="reference"), _f("IsDirect", type="boolean")])
    monkeypatch.setattr(sys.modules[__name__], "COUNTS", [(("FROM Contact", "AccountContactRelation WHERE IsDirect = false"), 7),
                                                          (("FROM AccountContactRelation",), 11), *COUNTS])
    connect(client)
    a, res, findings = run(client)
    card = next(i for x in res["areas"] for i in x["indicators"] if i["label"] == "Contacts to Multiple Accounts")
    assert card["value"] == 7 and card["score"] == 100
    assert dict(card["criteria"])["What's counted"] == "7 Contacts (6%) are related to more than one Account, through 11 indirect relationships"
    assert "Contacts can’t be related to multiple Accounts" not in {f["name"] for f in findings}
    _page(monkeypatch, ["003000000000001", "003000000000002"])
    body = client.get(f"{API}/assessments/{a['id']}/areas/area-4/indicator-records", params={"label": card["label"], "object": "Contact"}).json()
    assert [c["label"] for c in body["columns"]][:2] == ["Full Name", "Related Accounts"]  # right after the name
    assert body["columns"][1]["type"] == "lines"
    assert body["records"][0]["values"]["RelatedAccounts"] == "OakStone Retail Group\nTitan Manufacturing Corp"  # its own Account first
    assert body["records"][1]["values"]["RelatedAccounts"] is None
    q = next(q for q in reversed(sf.soql) if "FROM AccountContactRelation WHERE ContactId IN" in q)
    assert "ContactId IN ('003000000000001', '003000000000002')" in q
