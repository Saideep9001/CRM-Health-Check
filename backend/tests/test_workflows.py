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
# Einstein Activity Capture settings: on for everyone, email and contact sync on, event sync off
EAC_XML = """<?xml version="1.0" encoding="UTF-8"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
xmlns="http://soap.sforce.com/2006/04/metadata"><soapenv:Body><readMetadataResponse><result>
<records xsi:type="EACSettings" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><fullName>EAC</fullName>
<enableEACForEveryone>true</enableEACForEveryone><enableEmailSync>true</enableEmailSync><enableEventSync>false</enableEventSync>
<enableContactSync>true</enableContactSync><enableInsightsInTimeline>true</enableInsightsInTimeline></records>
</result></readMetadataResponse></soapenv:Body></soapenv:Envelope>"""

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
# Accounts with a parent: Account A (the top, not listed) → B → C, and A → D; Loop X → Y → Z goes round; Self S is its own parent.
ACCOUNT_PARENTS = [
    {"Id": "001000000000002", "Name": "Account B", "ParentId": "001000000000001"},
    {"Id": "001000000000003", "Name": "Account C", "ParentId": "001000000000002"},
    {"Id": "001000000000004", "Name": "Account D", "ParentId": "001000000000001"},
    {"Id": "001000000000005", "Name": "Loop X", "ParentId": "001000000000006"},
    {"Id": "001000000000006", "Name": "Loop Y", "ParentId": "001000000000007"},
    {"Id": "001000000000007", "Name": "Loop Z", "ParentId": "001000000000005"},
    {"Id": "001000000000008", "Name": "Self S", "ParentId": "001000000000008"},
]
# Accounts for Possible Missing Parent Accounts: Acme East (domain, name and sibling → Acme Corp), Zenith Retail (Subsidiary),
# Nova Labs UK (domain and name → Nova Labs), Harbor Logistics (phone only → Harbor Freight Co), two gmail.com sites (ignored),
# Orbit Media Group (its domain is Orbit Media's Contacts' → Orbit Media).
GUESS_ACCOUNTS = [
    {"Id": "001A00000000001", "Name": "Acme Corp", "Website": "acme.com"},
    {"Id": "001A00000000002", "Name": "Acme West", "ParentId": "001A00000000001"},
    {"Id": "001A00000000003", "Name": "Acme East", "Website": "https://www.acme.com/east"},
    {"Id": "001A00000000004", "Name": "Zenith Retail", "Ownership": "Subsidiary"},
    {"Id": "001A00000000005", "Name": "Nova Labs", "Website": "novalabs.co.uk"},
    {"Id": "001A00000000006", "Name": "Nova Labs UK", "Website": "https://uk.novalabs.co.uk"},
    {"Id": "001A00000000007", "Name": "Harbor Freight Co", "Phone": "(415) 555-0100"},
    {"Id": "001A00000000008", "Name": "Harbor Logistics", "Phone": "415-555-0100"},
    {"Id": "001A00000000009", "Name": "Solo Person", "Website": "gmail.com"},
    {"Id": "001A00000000010", "Name": "Another Solo", "Website": "www.gmail.com"},
    {"Id": "001A00000000011", "Name": "Orbit Media"},
    {"Id": "001A00000000012", "Name": "Orbit Media Group", "Website": "orbitmedia.com"},
]
LEADS = [  # open Leads read to compare with the rules
    {"Id": "00Q000000000001", "OwnerId": "00G000000000002", "Owner": {"Name": "Web Queue"}, "CreatedById": "005000000000009", "LeadSource": "Web"},  # active entry 1
    {"Id": "00Q000000000002", "OwnerId": "005000000000002", "Owner": {"Name": "Bob Ray"}, "CreatedById": "005000000000002", "LeadSource": "Partner"},  # no match, waiting
    {"Id": "00Q000000000003", "OwnerId": "005000000000001", "Owner": {"Name": "Ann Lee"}, "CreatedById": "005000000000009", "LeadSource": None},  # no match, assigned by hand
    {"Id": "00Q000000000004", "OwnerId": "005000000000001", "Owner": {"Name": "Ann Lee"}, "CreatedById": "005000000000009", "LeadSource": "phone"},  # active entry 2
]

# COUNT() answers: first rule whose substrings all appear in the query wins.
KEY_PREFIXES = {"Account": "001", "Contact": "003", "Opportunity": "006", "Lead": "00Q"}  # the objects' record id prefixes

COUNTS = [
    (("FROM ActivityMetric", "LAST_N_DAYS:7"), 12),  # EAC Health: Activity Metrics updated
    (("FROM ActivityMetric",), 40),
    (("FROM Task WHERE OwnerId IN", "LAST_N_DAYS:7"), 9),  # tasks the EAC users logged
    (("FROM Event WHERE OwnerId IN", "LAST_N_DAYS:7"), 3),
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
    (("CloseDate < TODAY", "CloseDate < LAST_N_DAYS:90"), 2),  # overdue by more than 90 days
    (("CloseDate < TODAY", "CloseDate < LAST_N_DAYS:30"), 5),  # by more than 30 days
    (("CloseDate < TODAY",), 8),
    (("NOT IN (SELECT OpportunityId",), 15),
    (("LastStageChangeDate",), 10),
    (("NextStep = null",), 18),
    (("IsWon = false", "Loss_Reason__c = null"), 6),
    (("IsWon = false",), 10),
    (("FROM Opportunity", "LastActivityDate"), 22),
    (("Amount = null",), 4),
    (("FROM Account", "NOT IN (SELECT AccountId FROM Contact"), 30),
    (("FROM Account", "ParentId != null", "Parent.Name LIKE"), 3),  # child Accounts under an inactive parent
    (("FROM Account", "ParentId != null"), 12),  # child Accounts
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
            xml = (LAYOUT_XML if "<met:type>Layout</met:type>" in self.soap[-1] else EAC_XML if "<met:type>EACSettings</met:type>" in self.soap[-1]
                   else self.rules_xml)
            return httpx.Response(200, text=xml, headers={"Content-Type": "text/xml"})
        if url.path.endswith("/sobjects"):
            return httpx.Response(200, json={"sobjects": [{"name": n, "label": n, "labelPlural": n + "s", "queryable": True, "retrieveable": True,
                                                           "keyPrefix": KEY_PREFIXES.get(n)} for n in DESCRIBE]})
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
        if q.startswith("SELECT Id, Name, ParentId FROM Account WHERE ParentId != null"):
            return ACCOUNT_PARENTS
        if q.startswith("SELECT Id, Name, ParentId") and " FROM Account ORDER BY CreatedDate" in q:  # Accounts, for missing parents
            return GUESS_ACCOUNTS
        if q.startswith("SELECT AccountId, Email FROM Contact WHERE AccountId != null AND Email != null"):
            return [{"AccountId": "001A00000000011", "Email": "kim@orbitmedia.com"}, {"AccountId": "001A00000000009", "Email": "x@gmail.com"}]
        if q.startswith("SELECT Id, Name, IsActive FROM RecordType WHERE SobjectType = 'Lead'"):  # Lead record types
            return [{"Id": "012000000000001AAA", "Name": "Partner", "IsActive": True}, {"Id": "012000000000002AAA", "Name": "Direct", "IsActive": True},
                    {"Id": "012000000000003AAA", "Name": "Old", "IsActive": False}]
        if q.startswith("SELECT RecordTypeId r, COUNT(Id) c FROM Lead"):
            return [{"r": "012000000000002AAA", "c": 7}, {"r": None, "c": 2}]
        if q.startswith("SELECT StageName s, COUNT(Id) c FROM Opportunity"):  # the Stage chips
            return [{"s": "Proposal", "c": 3}, {"s": "Prospecting", "c": 2}]
        if q.startswith("SELECT Id, Name FROM Account WHERE Id IN"):  # the top Accounts' names
            return [{"Id": "001000000000001", "Name": "Account A"}] if "'001000000000001'" in q else []
        if "FROM User WHERE Username IN" in q:  # who inactive rules assign to, by username
            return [{"Id": "005000000000002", "Name": "Bob Ray", "Username": "bob@acme.test"}] if "'bob@acme.test'" in q else []
        if "FROM User" in q:
            return [{"Id": i, "Name": n, "UserType": "Standard", "Profile": {"Name": "Sales"}} for i, n in USERS.items()]
        if "Owner.Type = 'Queue' ORDER BY CreatedDate" in q:
            return [{"Name": "Old Lead", "CreatedDate": "2026-01-01T00:00:00.000+0000"}]
        if q.startswith("SELECT Name, StageName"):
            return [{"Name": "Big Deal", "StageName": "Proposal", "Amount": 90000}]
        if "Id IN ('006000000000001AAA', '006000000000002AAA')" in q:  # Potential junk data's records table
            return [{"Id": "006000000000001AAA", "Name": "Deal A", "NextStep": "tbd"}, {"Id": "006000000000002AAA", "Name": "Deal B", "Description": "test"}]
        if q.startswith("SELECT Id, NextStep, Description FROM Opportunity"):
            return [{"Id": "006000000000001AAA", "NextStep": "tbd"}, {"Id": "006000000000002AAA", "Description": "test"},
                    {"Id": "006000000000003AAA", "NextStep": "Call Monday", "Description": "Real notes"}]
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
    # No Activity in 6 Months (Leads) needs an activity date, which this fake org's Leads don't have (tested on its own below)
    assert [i["label"] for i in areas["area-3"]["indicators"]] == ["Stuck Queue-Owned Leads", "Inactive Lead Assignment Rules", "Lead Assignment Criteria Mismatches",
                                                                   "Stale Leads"]
    assert ind["Stale Leads"] == 20  # Status unchanged for 30+ days (Lead History)
    assert ind["Opportunities with an Overdue Close Date"] == 8
    overdue = areas["area-5"]["indicators"][-2]  # Area 5, right before Sales stage guidance gaps
    assert overdue["label"] == "Opportunities with an Overdue Close Date"
    assert dict(overdue["criteria"])["How far past"] == "1–30 days: 3 · 31–90 days: 3 · more than 90 days: 2"
    assert ind["Stuck Queue-Owned Leads"] == 8  # in a queue more than 3 days
    assert ind["Inactive Lead Assignment Rules"] == 1 and ind["Lead Assignment Criteria Mismatches"] == 2  # 1 Lead in an inactive queue
    rule_reads = [x for x in sf.soap if "<met:type>AssignmentRules</met:type>" in x]
    assert len(rule_reads) == 1 and "<fullNames>Lead</fullNames>" in rule_reads[0]  # read once for both cards
    assert [i["label"] for i in areas["area-4"]["indicators"]] == ["Accounts Without Contacts", "Accounts Without Open Opportunities", "Account Hierarchy Chains",  # Accounts first
                                                                   "Child Accounts Under Inactive Parents", "Possible Missing Parent Accounts",
                                                                   "Opportunities Without Contact Roles", "Orphaned Contacts",
                                                                   "Contacts to Multiple Accounts", "Multi-Deal Contacts"]
    assert ind["Child Accounts Under Inactive Parents"] == 3
    assert ind["Accounts Without Contacts"] == 30
    assert ind["Opportunities Without Contact Roles"] == 15 and ind["Orphaned Contacts"] == 9
    assert ind["Contacts to Multiple Accounts"] == 0 and ind["Multi-Deal Contacts"] == 1  # the feature is off; Pat is on 2 open deals
    assert ind["Stuck Opportunities"] == 10 and ind["Missing Next Steps"] == 18
    assert "Missing Closed Lost reasons" not in ind  # removed: Closed Lost Without a Reason covers it
    assert ind["Sales stage guidance gaps"] == 2  # no Path: both open stages unguided
    assert "Missing sales activities" not in ind  # removed: Reps with No Activities Logged Recently covers it
    assert ind["Reps with No Activities Logged Recently"] == 1  # Bob owns work but logged nothing
    assert ind["Web-to-Lead issues"] == 1 and ind["Email template availability"] == 2
    assert "Activity capture gaps" not in ind  # removed from Area 6
    assert ind["Missing validation rules"] == 3 and ind["Potential junk data"] == 2  # 2 open opps (only open Opportunities are checked)
    assert res["salesProcessScore"] == res["categories"][0]["score"] and res["categories"][0]["categoryId"] == "workflows"

    assert not any("unexpected error" in (x["message"] or "") for x in res["areas"]), res["areas"]
    names = {f["name"]: f for f in findings}
    assert "Placeholder or junk values" in names
    # junk data looks at every open Opportunity (no 2,000 limit), and no other object
    opp = next(q for q in sf.soql if q.startswith("SELECT Id, NextStep, Description FROM Opportunity"))
    assert "LIMIT" not in opp and "IsClosed = false" in opp
    assert not any(q.startswith(("SELECT Company v", "SELECT LastName v", "SELECT Name v")) for q in sf.soql)
    # its records table lists exactly the open Opportunities with a placeholder, by Id
    junk = names["Placeholder or junk values"]
    assert junk["recordsAvailable"]
    assert client.get(f"{API}/findings/{junk['id']}/records").status_code == 200
    q = sf.soql[-1]
    assert "FROM Opportunity" in q and "Id IN ('006000000000001AAA', '006000000000002AAA')" in q and "IsClosed = false" in q
    # the junk values themselves are marked red, with why (Next Step "tbd" on one, Description "test" on the other)
    page = client.get(f"{API}/assessments/{a['id']}/areas/area-7/indicator-records", params={"label": "Potential junk data", "object": "Opportunity"})
    assert page.status_code == 200
    assert page.json()["cellNotes"] == {"006000000000001AAA": {"NextStep": "Placeholder value “tbd”"},
                                        "006000000000002AAA": {"Description": "Placeholder value “test”"}}
    assert "Website leads have stopped arriving" in names and names["Website leads have stopped arriving"]["severity"] == "critical"
    assert "Reps with no logged activity" not in names
    assert names["Leads with no assignment path"]["description"] == ("1 open Leads match no entry of the active Lead Assignment Rule “Standard” and "
                                                                     "haven’t been assigned by hand; 1 more were assigned by hand. Most are with: Bob Ray (1).")
    stuck = names["Leads stuck in a queue"]
    assert stuck["severity"] == "critical" and "8 open Leads have waited in a queue more than 3 days" in stuck["description"]
    assert "3 of them more than 7 days" in stuck["description"] and "Jane Doe" in stuck["description"]
    review = names["Inactive Lead Assignment Rules match existing Leads"]
    assert review["severity"] == "low" and review["affectedRecords"] == 4 and "“Old Rule” (4), “Partner Rule” (1)" in review["description"]
    assert "“Big Deal” (Proposal, 90,000)" in names["Stuck deals"]["description"]
    assert "Lost deals with no reason" not in names
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
        {"id": "00G000000000001AAA", "name": "Jane Doe", "count": 5, "active": False},  # no active rule assigns to it: red
        {"id": "00G000000000002AAA", "name": "Web Queue", "count": 0, "active": True}]  # the active rule's Web_Queue: green
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
    assert "FROM Lead WHERE IsConverted = false AND OwnerId IN ('00G000000000003AAA')" in q
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
    roles = body["columns"][-1]  # last, frozen, one role per line
    assert (roles["label"], roles["type"], roles["frozen"]) == ("Roles on Open Deals", "lines", True)
    assert not any(c["frozen"] for c in body["columns"][:-1])
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
    related = body["columns"][-1]  # last, frozen, one Account per line
    assert (related["label"], related["type"], related["frozen"]) == ("Related Accounts", "lines", True)
    assert body["records"][0]["values"]["RelatedAccounts"] == "OakStone Retail Group\nTitan Manufacturing Corp"  # its own Account first
    assert body["records"][1]["values"]["RelatedAccounts"] is None
    q = next(q for q in reversed(sf.soql) if "FROM AccountContactRelation WHERE ContactId IN" in q)
    assert "ContactId IN ('003000000000001', '003000000000002')" in q


def test_inactive_rules_chips_by_rule_and_assignee(client, sf):
    connect(client)
    a, _, _ = run(client)
    base = f"{API}/assessments/{a['id']}/areas/area-3"
    params = {"label": "Inactive Lead Assignment Rules", "object": "Lead"}
    body = client.get(f"{base}/indicator-rule-targets", params=params)
    assert body.status_code == 200
    got = body.json()
    # each inactive rule with who it assigns to (Old Rule: Bob, a user; Partner Rule: the Partner queue), counts live (by OwnerId)
    assert got["rules"] == [{"name": "Old Rule", "targets": ["005000000000002"], "count": 2},
                            {"name": "Partner Rule", "targets": ["00G000000000003AAA"], "count": 0}]
    assert got["targets"] == [{"id": "005000000000002", "name": "Bob Ray", "type": "User", "inactive": False, "count": 2},
                              {"id": "00G000000000003AAA", "name": "Partner Queue", "type": "Queue", "inactive": True, "count": 0}]
    # a rule's assignee (a user here): the open Leads it owns, not just those in inactive queues
    assert client.get(f"{base}/indicator-records", params={**params, "queue": "005000000000002"}).status_code == 200
    q = _lead_query(sf)
    assert "FROM Lead WHERE IsConverted = false AND OwnerId IN ('005000000000002')" in q and "00G000000000003AAA" not in q
    # a rule picked with no assignee: all of its assignees
    assert client.get(f"{base}/indicator-records", params={**params, "queue": "005000000000002,00G000000000003AAA"}).status_code == 200
    assert "OwnerId IN ('005000000000002', '00G000000000003AAA')" in _lead_query(sf)
    for bad in ("005000000000001", "x' OR Id != null", ","):  # not one of the rules' assignees or the inactive queues
        assert client.get(f"{base}/indicator-records", params={**params, "queue": bad}).status_code == 422
    other = {"label": "Stuck Queue-Owned Leads", "object": "Lead"}
    assert client.get(f"{base}/indicator-rule-targets", params=other).status_code == 422


def test_account_hierarchy_chains(client, sf, monkeypatch):
    connect(client)
    a, res, findings = run(client)
    card = next(i for x in res["areas"] for i in x["indicators"] if i["label"] == "Account Hierarchy Chains")
    crit = dict(card["criteria"])
    assert card["value"] == 8 and card["score"] is None  # A, B, C, D, the 3 in the loop and Self S
    assert crit["What's counted"] == "8 of 100 Accounts (8%) are in a hierarchy, across 1 hierarchy"
    assert crit["Deepest chain"] == "3 levels: Account A → Account B → Account C"
    assert crit["Largest hierarchy"] == "Account A (4 Accounts)"
    assert crit["Loops"] == ("4 Accounts in 2 loops: Loop Z → Loop Y → Loop X ↻ back to Loop Z; Self S ↻ back to Self S")
    found = next(f for f in findings if f["name"] == "Account hierarchies that loop back on themselves")
    assert found["severity"] == "high" and found["affectedRecords"] == 4
    base = f"{API}/assessments/{a['id']}/areas/area-4"
    params = {"label": card["label"], "object": "Account"}
    assert client.get(f"{base}/indicator-queues", params=params).status_code == 422  # no Batches chips
    assert client.get(f"{base}/indicator-records", params={**params, "queue": "001000000000001"}).status_code == 422
    _page(monkeypatch, ["001000000000002", "001000000000001", "001000000000099"])
    body = client.get(f"{base}/indicator-records", params=params).json()
    assert body["sortedBy"] == "HierarchyBatch"  # the table groups the rows by batch
    assert body["columns"][0]["label"] == "Batch" and (body["columns"][-1]["label"], body["columns"][-1]["frozen"]) == ("Child Accounts", True)
    top, b, other = (r["values"] for r in body["records"])  # batch by batch, the top Account first
    assert (top["HierarchyBatch"], top["ChildAccounts"]) == (1, "Account B\nAccount D")
    assert (b["HierarchyBatch"], b["ChildAccounts"]) == (1, "Account C")
    assert other["HierarchyBatch"] is None and other["ChildAccounts"] is None


def test_child_accounts_under_inactive_parents(client, sf, monkeypatch):
    monkeypatch.setitem(DESCRIBE, "Account", [*DESCRIBE["Account"], _f("Active__c", label="Active", type="picklist"),
                                              _f("Account_Status__c", label="Account Status", type="picklist",
                                                 picklistValues=[{"value": "Open"}, {"value": "Closed"}, {"value": "Dormant"}])])
    connect(client)
    a, res, findings = run(client)
    card = next(i for x in res["areas"] for i in x["indicators"] if i["label"] == "Child Accounts Under Inactive Parents")
    crit = dict(card["criteria"])
    assert card["value"] == 3 and crit["What's counted"] == "3 of 12 child Accounts (25%) are under an inactive Parent Account"
    assert crit["Inactive parent"].startswith("The Parent Account Active is No; or Account Status is Closed or Dormant; or its name says “Inactive”")
    q = next(q for q in sf.soql if q.startswith("SELECT COUNT() FROM Account WHERE ParentId != null AND ("))
    assert "Parent.Active__c IN ('No', 'False', 'N', 'Inactive') OR Parent.Account_Status__c IN ('Closed', 'Dormant')" in q
    assert "Parent.Name LIKE '%Defunct%'" in q
    assert "Child Accounts under inactive parent Accounts" in {f["name"] for f in findings}
    live = client.get(f"{API}/assessments/{a['id']}/areas/area-4/indicator-records", params={"label": card["label"], "object": "Account"}).json()
    assert live["sortedBy"] == "ParentId"  # grouped by the inactive parent
    assert "ORDER BY Parent.Name ASC NULLS LAST, Name ASC" in next(q for q in reversed(sf.soql) if "FROM Account WHERE ParentId != null AND" in q)
    page = {"object": "Account", "columns": [{"name": "Name", "label": "Account Name", "type": "string"},
                                             {"name": "Industry", "label": "Industry", "type": "picklist"},
                                             {"name": "ParentId", "label": "Parent Account ID", "type": "reference"}],
            "total_size": 1, "next_cursor": None, "record_url_prefix": "https://acme.my.salesforce.com/",
            "records": [{"id": "001000000000002", "values": {"Name": "Kid"}, "ref_names": {"ParentId": "Old Co (Defunct)"}}]}
    seen = {}
    monkeypatch.setattr(explorer, "records_matching", lambda *a, **k: seen.update(k) or page)
    params = {"label": card["label"], "object": "Account", "fields": "Name,Industry"}
    body = client.get(f"{API}/assessments/{a['id']}/areas/area-4/indicator-records", params=params).json()
    assert seen["columns"][0] == "ParentId"  # the parent is read even when not picked
    assert seen["order"] == "Parent.Name"
    first = body["columns"][0]
    assert (first["name"], first["label"], first["pinned"]) == ("ParentId", "Inactive Parent Account", True)


def test_possible_missing_parent_accounts(client, sf, monkeypatch):
    monkeypatch.setitem(DESCRIBE, "Account", [*DESCRIBE["Account"], _f("Website", type="url"), _f("Ownership", type="picklist"),
                                              _f("BillingStreet", type="textarea"), _f("BillingPostalCode"), _f("CreatedDate", type="datetime")])
    connect(client)
    a, res, findings = run(client)
    card = next(i for x in res["areas"] for i in x["indicators"] if i["label"] == "Possible Missing Parent Accounts")
    crit = dict(card["criteria"])
    assert card["value"] == 5 and card["score"] is None
    assert crit["What's counted"] == "5 Accounts may be missing their Parent Account: High 4, Medium 0, Low 1"
    assert crit["Clues found"].startswith("Subsidiary 1 · sibling 1 · website domain 2 · Contact email domain 1")
    found = next(f for f in findings if f["name"] == "Accounts that may be missing their Parent Account")
    assert found["severity"] == "low" and found["affectedRecords"] == 4
    assert not any("@gmail" in q for q in sf.soql)
    _page(monkeypatch, ["001A00000000008", "001A00000000003", "001A00000000012", "001A00000000006", "001A00000000004"])
    body = client.get(f"{API}/assessments/{a['id']}/areas/area-4/indicator-records", params={"label": card["label"], "object": "Account"}).json()
    assert [c["label"] for c in body["columns"]][-3:] == ["Confidence", "Note (why it was guessed)", "Suggested Parent Account"]
    parent_col, note_col = body["columns"][-1], body["columns"][-2]
    assert parent_col["frozen"] and parent_col["note"] == "WhyParent" and note_col["hidden"]  # the note shows under the suggestion
    rows = [(r["id"], r["values"]["Confidence"], r["values"]["SuggestedParent"]) for r in body["records"]]  # the most likely first
    assert rows[-1] == ("001A00000000008", "Low", "Harbor Freight Co")  # Harbor Logistics: only the phone matches
    got = {i: (c, p) for i, c, p in rows}
    assert got["001A00000000003"] == ("High", "Acme Corp")  # Acme East
    assert got["001A00000000006"] == ("High", "Nova Labs")  # Nova Labs UK: same domain and name
    assert got["001A00000000012"] == ("High", "Orbit Media")  # Orbit Media Group: its domain is Orbit Media's Contacts'
    assert got["001A00000000004"] == ("High", None)  # Zenith Retail: Subsidiary, no parent to suggest
    acme = next(r["values"]["WhyParent"] for r in body["records"] if r["id"] == "001A00000000003")
    assert acme.split("\n") == ["Same website domain acme.com", "Same name once Inc, Corp, places and suffixes are dropped (“acme”)",
                                 "Sibling “Acme West” already has “Acme Corp” as parent"]


def test_lead_activity_cards_in_area_3(client, sf, monkeypatch):
    monkeypatch.setitem(DESCRIBE, "Lead", [*DESCRIBE["Lead"], _f("LastActivityDate", type="date"), _f("CreatedDate", type="datetime")])
    connect(client)
    _, res, findings = run(client)
    labels = [i["label"] for x in res["areas"] if x["areaId"] == "area-3" for i in x["indicators"]]
    assert labels[-2:] == ["No Activity in 6 Months (Leads)", "Stale Leads"]  # moved from Area 1, and Stale Leads added
    assert not any(i["label"] == "No Activity in 6 Months (Leads)" for x in res["areas"] if x["areaId"] == "area-1" for i in x["indicators"])
    assert {"Open Leads with no activity in 6 months", "Open Leads stuck in the same status for 14+ days"} <= {f["name"] for f in findings}



def test_opportunity_cards_moved_to_area_5(client, sf, monkeypatch):
    monkeypatch.setitem(DESCRIBE, "Opportunity", [*DESCRIBE["Opportunity"], _f("LastActivityDate", type="date"), _f("IsWon", type="boolean")])
    connect(client)
    _, res, _ = run(client)
    labels = {x["areaId"]: [i["label"] for i in x["indicators"]] for x in res["areas"]}
    # (the fake org has no plural label, so the cards say "Opportunitys"; a real org's say "Opportunities")
    moved = ("No Activity in 6 Months (Opportun", "Closed Lost Without a Reason (Opportun")
    assert [label.startswith(m) for label, m in zip(labels["area-5"][2:4], moved)] == [True, True]  # after Missing Next Steps
    assert labels["area-5"][-2:] == ["Opportunities with an Overdue Close Date", "Sales stage guidance gaps"]
    assert labels["area-5"][:2] == ["Stuck Opportunities", "Missing Next Steps"] and "Missing Closed Lost reasons" not in labels["area-5"]
    assert not any(label.startswith(moved) for label in labels.get("area-1", []))

def test_stale_leads_period_and_status(client, sf):
    connect(client)
    a, _, _ = run(client)
    base = f"{API}/assessments/{a['id']}/areas/area-3"
    params = {"label": "Stale Leads", "object": "Lead"}
    status = "'Status' AND CreatedDate"
    # another period: Status unchanged for 90 days instead of the check's 14
    assert client.get(f"{base}/indicator-records", params={**params, "period": "90"}).status_code == 200
    q = _lead_query(sf)
    assert "CreatedDate < LAST_N_DAYS:90" in q and f"{status} = LAST_N_DAYS:90" in q and "LAST_N_DAYS:14" not in q
    # dates: no Status change between them, on Leads created before the first
    assert client.get(f"{base}/indicator-records", params={**params, "period": "range:2026-01-01:2026-03-31"}).status_code == 200
    q = _lead_query(sf)
    assert "CreatedDate < 2026-01-01T00:00:00Z" in q
    assert f"{status} >= 2026-01-01T00:00:00Z AND CreatedDate < 2026-04-01T00:00:00Z" in q
    assert client.get(f"{base}/indicator-records", params={**params, "period": "45"}).status_code == 422
    # the Status chips, for the period picked, and one Status's Leads
    statuses = client.get(f"{base}/indicator-queues", params={**params, "period": "90"})
    assert statuses.status_code == 200
    grouped = next(q for q in reversed(sf.soql) if q.startswith("SELECT Status s, COUNT(Id) c FROM Lead"))
    assert "LAST_N_DAYS:90" in grouped and "GROUP BY Status" in grouped
    assert client.get(f"{base}/indicator-records", params={**params, "queue": "Working - Contacted"}).status_code == 200
    assert "AND Status = 'Working - Contacted'" in _lead_query(sf)
    assert client.get(f"{base}/indicator-records", params={**params, "queue": "New' OR Id != null --"}).status_code == 422
    # the Record Type drop-down: active types (and inactive ones with Leads), most first, plus the Leads with none
    types = client.get(f"{base}/indicator-record-types", params={**params, "period": "90"})
    assert types.status_code == 200
    assert [(t["id"], t["name"], t["count"]) for t in types.json()] == [
        ("012000000000002AAA", "Direct", 7), ("none", "No record type", 2), ("012000000000001AAA", "Partner", 0)]
    assert "LAST_N_DAYS:90" in next(q for q in reversed(sf.soql) if q.startswith("SELECT RecordTypeId r"))
    # one record type: its Leads, and its Status counts
    rt = {**params, "record_type": "012000000000002AAA"}
    assert client.get(f"{base}/indicator-records", params={**rt, "queue": "Working - Contacted"}).status_code == 200
    q = _lead_query(sf)
    assert "AND RecordTypeId = '012000000000002AAA'" in q and "AND Status = 'Working - Contacted'" in q
    assert client.get(f"{base}/indicator-queues", params=rt).status_code == 200
    assert "RecordTypeId = '012000000000002AAA'" in next(q for q in reversed(sf.soql) if q.startswith("SELECT Status s, COUNT(Id) c FROM Lead"))
    assert client.get(f"{base}/indicator-records", params={**params, "record_type": "none"}).status_code == 200
    assert "AND RecordTypeId = null" in _lead_query(sf)
    assert client.get(f"{base}/indicator-records", params={**params, "record_type": "x' OR Id != null"}).status_code == 422
    other = client.get(f"{base}/indicator-records", params={"label": "Stuck Queue-Owned Leads", "object": "Lead", "record_type": "none"})
    assert other.status_code == 422


# Sales Paths in Setup: an active Channel path (its own sales process, two stages, one guided) and an inactive Master one
PATH_GUIDANCE = ("<p>Qualify the opportunity and confirm budget.&nbsp;What’s their business?</p>"
                 "<ul><li>What problems are they trying to solve?</li><li>Why is the timing good for them?</li></ul>")


def test_sales_paths_with_stage_guidance(client, sf, monkeypatch):
    tooling, records = FakeSalesOrg.tooling, FakeSalesOrg.records

    def paths_tooling(q):
        if q.startswith("SELECT Id, DeveloperName, MasterLabel, SobjectType, IsActive FROM PathAssistant"):
            return [{"Id": "0Ra000000000002AAA", "DeveloperName": "Master_Path", "MasterLabel": "Master Path", "SobjectType": "Opportunity", "IsActive": False},
                    {"Id": "0Ra000000000001AAA", "DeveloperName": "Channel_Path", "MasterLabel": "Channel Sales Path", "SobjectType": "Opportunity", "IsActive": True},
                    {"Id": "0Ra000000000003AAA", "DeveloperName": "Lead_Path", "MasterLabel": "Lead Path", "SobjectType": "Lead", "IsActive": True}]
        if q == "SELECT Id, Metadata FROM PathAssistant WHERE Id = '0Ra000000000001AAA'":
            return [{"Metadata": {"recordTypeName": "Opportunity.Channel", "pathAssistantSteps": [
                {"picklistValueName": "Proposal", "info": PATH_GUIDANCE, "fieldNames": ["Amount", "NextStep"]},
                {"picklistValueName": "Prospecting", "info": "<p>&nbsp;</p>", "fieldNames": []}]}}]
        if q == "SELECT Id, Metadata FROM PathAssistant WHERE Id = '0Ra000000000002AAA'":
            return [{"Metadata": {"recordTypeName": "__MASTER__", "pathAssistantSteps": []}}]
        if q == "SELECT Id, Name, Metadata FROM BusinessProcess WHERE Id = '019000000000001AAA'":
            return [{"Name": "Channel Sales Process", "Metadata": {"values": [{"fullName": "Prospecting"}, {"fullName": "Proposal"}]}}]
        if q == "SELECT Id, Name, Metadata FROM BusinessProcess WHERE Id = '019000000000002AAA'":
            return [{"Name": "Direct Sales Process", "Metadata": {"values": [{"fullName": "Proposal"}]}}]
        return tooling(q)

    def paths_records(q):
        if q.startswith("SELECT Name, DeveloperName, BusinessProcessId, IsActive FROM RecordType WHERE SobjectType = 'Opportunity'"):
            return [{"Name": "Channel", "DeveloperName": "Channel", "BusinessProcessId": "019000000000001AAA", "IsActive": True},
                    {"Name": "Partner", "DeveloperName": "Partner", "BusinessProcessId": "019000000000001AAA", "IsActive": True},
                    {"Name": "Direct", "DeveloperName": "Direct", "BusinessProcessId": "019000000000002AAA", "IsActive": True}]
        if q.startswith("SELECT Id, Name, IsActive FROM BusinessProcess WHERE TableEnumOrId = 'Opportunity'"):
            return [{"Id": "019000000000001AAA", "Name": "Channel Sales Process", "IsActive": True},
                    {"Id": "019000000000002AAA", "Name": "Direct Sales Process", "IsActive": False}]
        return records(q)

    monkeypatch.setattr(FakeSalesOrg, "tooling", staticmethod(paths_tooling))
    monkeypatch.setattr(FakeSalesOrg, "records", staticmethod(paths_records))
    connect(client)
    a, _, _ = run(client)
    body = client.get(f"{API}/assessments/{a['id']}/sales-paths")
    assert body.status_code == 200, body.text
    channel, master, direct = body.json()  # every Sales Process, active ones first (the inactive Direct one last); no Lead path
    assert (channel["name"], channel["active"], channel["pathName"], channel["recordType"]) == ("Channel Sales Process", True, "Channel Sales Path", "Channel, Partner")
    assert (direct["name"], direct["active"], direct["pathName"], direct["processActive"]) == ("Direct Sales Process", False, None, False)
    assert [(s["stage"], s["available"]) for s in direct["stages"]] == [("Proposal", False)]  # no Path: no guidance
    assert (master["name"], master["active"], master["pathName"], master["pathActive"], master["recordType"]) == (
        "Master (no record type)", False, "Master Path", False, "Master")
    assert [s["stage"] for s in channel["stages"]] == ["Prospecting", "Proposal"] and (channel["guided"], channel["openStages"]) == (1, 2)
    prospecting, proposal = channel["stages"]
    assert not prospecting["available"] and prospecting["details"] == []  # only a blank paragraph: no guidance
    assert proposal["available"] and proposal["details"] == ["Qualify the opportunity and confirm budget. What’s their business?",
                                                             "• What problems are they trying to solve?", "• Why is the timing good for them?"]
    assert proposal["keyFields"][0] == "Amount" and len(proposal["keyFields"]) == 2
    assert all(not s["available"] for s in master["stages"])


def test_stage_chips_on_area_5_opportunity_cards(client, sf):
    connect(client)
    a, _, _ = run(client)
    base = f"{API}/assessments/{a['id']}/areas/area-5"
    for label in ("Stuck Opportunities", "Missing Next Steps", "Opportunities with an Overdue Close Date"):
        params = {"label": label, "object": "Opportunity"}
        chips = client.get(f"{base}/indicator-queues", params=params)
        assert chips.status_code == 200, chips.text
        assert [(c["name"], c["count"]) for c in chips.json()] == [("Prospecting", 2), ("Proposal", 3)]  # in the stages' order
        grouped = next(q for q in reversed(sf.soql) if q.startswith("SELECT StageName s, COUNT(Id) c FROM Opportunity"))
        assert "IsClosed = false" in grouped and "GROUP BY StageName" in grouped
        assert client.get(f"{base}/indicator-records", params={**params, "queue": "Proposal"}).status_code == 200
        q = next(q for q in reversed(sf.soql) if " FROM Opportunity" in q and "StageName = " in q)
        assert "AND StageName = 'Proposal'" in q
        assert client.get(f"{base}/indicator-records", params={**params, "queue": "x' OR Id != null --"}).status_code == 422


# Users assigned EAC: one fine, one deactivated, one who never logged in, one not logged in for years
EAC_USERS = [
    {"Id": "005000000000011AAA", "Name": "Priya Nair", "Email": "priya@acme.test", "Title": "Account Manager", "Phone": "(415) 555-0101",
     "Profile": {"Name": "Sales Rep"}, "IsActive": True, "LastLoginDate": "2099-01-01T00:00:00.000+0000"},
    {"Id": "005000000000012AAA", "Name": "Daniel Ortiz", "Profile": {"Name": "Sales Manager"}, "IsActive": False, "LastLoginDate": None},
    {"Id": "005000000000013AAA", "Name": "Aisha Khan", "Profile": {"Name": "Sales Rep"}, "IsActive": True, "LastLoginDate": None},
    {"Id": "005000000000014AAA", "Name": "Marcus Lee", "Profile": {"Name": "Account Executive"}, "IsActive": True, "LastLoginDate": "2020-01-01T00:00:00.000+0000"},
]


def test_eac_health_card_in_area_6(client, sf, monkeypatch):
    records = FakeSalesOrg.records

    def eac_records(q):
        if q.startswith("SELECT Id, Label FROM PermissionSet WHERE Label LIKE '%Activity Capture%'"):
            return [{"Id": "0PS000000000001AAA", "Label": "Standard Einstein Activity Capture"}]
        if q.startswith("SELECT AssigneeId FROM PermissionSetAssignment WHERE PermissionSetId IN ('0PS000000000001AAA')"):
            return [{"AssigneeId": u["Id"]} for u in EAC_USERS[:3]]
        if q.startswith("SELECT Id, MasterLabel FROM PermissionSetLicense WHERE MasterLabel LIKE '%Activity Capture%'"):
            return [{"Id": "0PL000000000001AAA", "MasterLabel": "Einstein Activity Capture"}]
        if q.startswith("SELECT AssigneeId FROM PermissionSetLicenseAssign WHERE PermissionSetLicenseId IN ('0PL000000000001AAA')"):
            return [{"AssigneeId": EAC_USERS[0]["Id"]}, {"AssigneeId": EAC_USERS[3]["Id"]}]  # Priya twice: counted once
        if q.startswith("SELECT Id, Name, Email, Title, Phone, Profile.Name, IsActive, LastLoginDate FROM User WHERE Id IN"):
            return [u for u in EAC_USERS if f"'{u['Id']}'" in q]
        return records(q)

    monkeypatch.setattr(FakeSalesOrg, "records", staticmethod(eac_records))
    connect(client)
    a, res, findings = run(client)
    card = next(i for x in res["areas"] if x["areaId"] == "area-6" for i in x["indicators"] if i["label"] == "Einstein Activity Capture (EAC) Health")
    assert card["value"] == 3 and card["score"] is not None
    crit = dict(card["criteria"])
    assert crit["Users"] == "4 assigned, 1 active, 3 need attention"
    assert "expired token" in crit["Not checked"]
    found = next(f for f in findings if f["name"] == "EAC users who may not be capturing activity")
    assert found["severity"] == "medium" and found["affectedRecords"] == 3  # a deactivated user still assigned
    body = client.get(f"{API}/assessments/{a['id']}/eac-health")
    assert body.status_code == 200, body.text
    d = body.json()
    assert d["status"] == "Warning"
    assert {t["key"]: t["on"] for t in d["tiles"]} == {"master": True, "email": True, "calendar": False, "contact": True}
    assert d["sources"] == ["Permission set: Standard Einstein Activity Capture", "Licence: Einstein Activity Capture"]
    assert (d["users"]["total"], d["users"]["active"], d["users"]["attention"]) == (4, 1, 3)
    issues = {u["name"]: u["status"] for u in d["users"]["issues"]}
    assert d["users"]["issues"][0]["name"] == "Daniel Ortiz" and issues["Daniel Ortiz"] == "Deactivated user"  # the worst first
    assert issues["Aisha Khan"] == "Never logged in" and issues["Marcus Lee"].startswith("No login in")
    logins = {u["name"]: u["login"] for u in d["users"]["all"]}  # everyone assigned, with whether and when they logged in
    assert len(d["users"]["all"]) == 4 and d["users"]["all"][-1]["status"] == "Active"
    assert logins["Priya Nair"].startswith("Logged in to Salesforce on 2099-01-01")
    assert logins["Aisha Khan"] == "Has never logged in to Salesforce"
    assert logins["Marcus Lee"] == "Last logged in to Salesforce on 2020-01-01"
    assert logins["Daniel Ortiz"] == "Can’t log in (deactivated); never logged in"
    active = {u["name"]: u["isActive"] for u in d["users"]["all"]}  # the User Status filter: Salesforce's Active flag
    assert active == {"Priya Nair": True, "Daniel Ortiz": False, "Aisha Khan": True, "Marcus Lee": True}
    assert {u["profile"] for u in d["users"]["all"]} == {"Sales Rep", "Sales Manager", "Account Executive"}  # the Profile filter
    priya = next(u for u in d["users"]["all"] if u["name"] == "Priya Nair")
    assert (priya["email"], priya["title"], priya["phone"]) == ("priya@acme.test", "Account Manager", "(415) 555-0101")
    assert next(u for u in d["users"]["all"] if u["name"] == "Aisha Khan")["email"] is None  # not set in Salesforce
    sync = {u["name"]: {s["key"]: s["on"] for s in u["sync"]} for u in d["users"]["all"]}  # under each user's Status
    assert sync["Priya Nair"] == {"master": True, "email": True, "calendar": False, "contact": True}  # the org's settings
    assert sync["Daniel Ortiz"] == {"master": False, "email": False, "calendar": False, "contact": False}  # deactivated: EAC is off
    assert d["users"]["issues"][0]["sync"]  # the Action required rows have it too
    assert {p["key"]: p["value"] for p in d["pipeline"]} == {"metrics7": 12, "metrics30": 40, "task": 9, "event": 3}


def test_reps_with_no_activities_logged_recently(client, sf):
    connect(client)
    a, res, _ = run(client)
    card = next(i for x in res["areas"] if x["areaId"] == "area-6" for i in x["indicators"] if i["label"] == "Reps with No Activities Logged Recently")
    assert card["value"] == 1  # Bob logged nothing; Ann logged tasks (the Agentforce user isn't a rep)
    crit = dict(card["criteria"])
    assert crit["By type"] == "No emails: 1 · no events: 2 · no tasks: 1" and crit["Quiet reps"] == "Bob Ray"
    body = client.get(f"{API}/assessments/{a['id']}/rep-activity", params={"days": 7})
    assert body.status_code == 200, body.text
    d = body.json()
    assert d["days"] == 7 and d["available"] == {"email": True, "event": True, "task": True}
    reps = {r["name"]: r for r in d["reps"]}
    assert set(reps) == {"Ann Lee", "Bob Ray"} and reps["Ann Lee"]["profile"] == "Sales"
    assert reps["Ann Lee"]["counts"] == {"email": 3, "event": 0, "task": 3} and reps["Bob Ray"]["counts"] == {"email": 0, "event": 0, "task": 0}
    emails = next(q for q in reversed(sf.soql) if "FROM Task" in q and "TaskSubtype = 'Email'" in q)
    assert "LAST_N_DAYS:7" in emails and "GROUP BY OwnerId" in emails
    assert any("FROM Task" in q and "TaskSubtype != 'Email'" in q for q in sf.soql)  # Tasks: the other ones
    assert client.get(f"{API}/assessments/{a['id']}/rep-activity", params={"days": 45}).status_code == 422
    assert d["reps"][0]["name"] == "Bob Ray"  # nothing logged first
    # custom dates: both days included
    ranged = client.get(f"{API}/assessments/{a['id']}/rep-activity", params={"from": "2026-01-01", "to": "2026-01-31"})
    assert ranged.status_code == 200 and (ranged.json()["from"], ranged.json()["to"]) == ("2026-01-01", "2026-01-31")
    q = next(q for q in reversed(sf.soql) if "FROM Event" in q and "GROUP BY OwnerId" in q)
    assert "CreatedDate >= 2026-01-01T00:00:00Z AND CreatedDate < 2026-02-01T00:00:00Z" in q
    for bad in ({"from": "2026-02-01", "to": "2026-01-01"}, {"from": "2026-01-01"}, {"from": "2999-01-01", "to": "2999-01-02"}):
        assert client.get(f"{API}/assessments/{a['id']}/rep-activity", params=bad).status_code == 422


def test_web_to_lead_period_and_history(client, sf, monkeypatch):
    from datetime import date, timedelta
    today = date.today()
    records = FakeSalesOrg.records

    def web_records(q):
        if q.startswith("SELECT DAY_ONLY(CreatedDate) d, COUNT(Id) c FROM Lead"):  # 3 a week for 12 weeks, none lately
            return [{"d": (today - timedelta(days=n)).isoformat(), "c": 1} for n in range(14, 14 + 84, 2)][:36]
        if q.startswith("SELECT CALENDAR_YEAR(CreatedDate) y, CALENDAR_MONTH(CreatedDate) m, COUNT(Id) c FROM Lead"):
            return [{"y": today.year, "m": today.month, "c": 4}]
        if q.startswith("SELECT CreatedDate FROM Lead"):
            return [{"CreatedDate": (today - timedelta(days=15)).isoformat() + "T09:00:00.000+0000"}]
        return records(q)

    monkeypatch.setattr(FakeSalesOrg, "records", staticmethod(web_records))
    monkeypatch.setitem(DESCRIBE, "Lead", [*DESCRIBE["Lead"], _f("CreatedDate", type="datetime", sortable=True)])
    connect(client)
    a, res, _ = run(client)
    base = f"{API}/assessments/{a['id']}/areas/area-6"
    params = {"label": "Web-to-Lead issues", "object": "Lead"}
    lead_q = lambda: next(q for q in reversed(sf.soql) if q.startswith("SELECT") and " FROM Lead WHERE" in q and "LeadSource IN" in q and "COUNT" not in q and "DAY_ONLY" not in q)  # noqa: E731
    # any time (the default): every website lead, newest first, without the check's own 90 days
    assert client.get(f"{base}/indicator-records", params=params).status_code == 200
    q = lead_q()
    assert "LeadSource IN (" in q and "LAST_N_DAYS:90" not in q and "ORDER BY CreatedDate DESC" in q
    for period, cond in (("7", "CreatedDate = LAST_N_DAYS:7"), ("30", "CreatedDate = LAST_N_DAYS:30"),
                         ("range:2026-01-01:2026-01-31", "CreatedDate >= 2026-01-01T00:00:00Z AND CreatedDate < 2026-02-01T00:00:00Z")):
        assert client.get(f"{base}/indicator-records", params={**params, "period": period}).status_code == 200
        assert cond in lead_q() and "LeadSource IN (" in lead_q()
    assert client.get(f"{base}/indicator-records", params={**params, "period": "45"}).status_code == 422
    # the history: none in the last 14 days, but some in the 12 weeks before: Stopped
    h = client.get(f"{base}/web-lead-history")
    assert h.status_code == 200, h.text
    h = h.json()
    assert (h["verdict"], h["tone"], h["last14"], h["last7"]) == ("Stopped", "bad", 0, 0)
    assert h["expected14"] > 0 and "may be broken" in h["why"]
    assert len(h["weeks"]) == 12 and h["weeks"][-1]["end"] == today.isoformat() and h["weeks"][-1]["count"] == 0
    assert len(h["months"]) == 12 and h["months"][-1]["count"] == 4
    assert h["lastCreated"] == (today - timedelta(days=15)).isoformat()
    assert h["year"] is None and h["years"][0] == today.year  # newest first
    # one calendar year: January to December
    y = client.get(f"{base}/web-lead-history", params={"year": today.year})
    assert y.status_code == 200 and [m["label"] for m in y.json()["months"]][0] == f"Jan {today.year}"
    assert len(y.json()["months"]) == 12 and y.json()["months"][today.month - 1]["count"] == 4
    month_q = next(q for q in reversed(sf.soql) if q.startswith("SELECT CALENDAR_YEAR"))
    assert f"CreatedDate >= {today.year}-01-01T00:00:00Z AND CreatedDate < {today.year + 1}-01-01T00:00:00Z" in month_q
    assert client.get(f"{base}/web-lead-history", params={"year": 1990}).status_code == 422
    day_q = next(q for q in reversed(sf.soql) if q.startswith("SELECT DAY_ONLY"))
    assert "LeadSource IN (" in day_q and "LAST_N_DAYS:90" not in day_q


TEMPLATES = [
    {"Id": "00X000000000001AAA", "Name": "Welcome", "Description": "  First email to a new lead  ", "TemplateType": "custom", "UiType": "SFX",
     "IsActive": True, "TimesUsed": 30, "FolderName": "Sales"},
    {"Id": "00X000000000002AAA", "Name": "Follow Up", "Description": None, "TemplateType": "text", "UiType": "Aloha", "IsActive": True,
     "TimesUsed": 10, "FolderName": "Unfiled"},
    {"Id": "00X000000000003AAA", "Name": "Old Promo", "Description": "Spring promo", "TemplateType": "html", "UiType": "Aloha", "IsActive": False,
     "TimesUsed": 0, "FolderName": "Unfiled"},
]


def test_email_templates_by_status_with_description_and_usage(client, sf, monkeypatch):
    records = FakeSalesOrg.records
    monkeypatch.setitem(DESCRIBE, "EmailTemplate", [_f(n) for n in ("Id", "Name", "Description", "TemplateType", "UiType", "FolderName")]
                        + [_f("IsActive", type="boolean"), _f("TimesUsed", type="int")])
    monkeypatch.setattr(FakeSalesOrg, "records", staticmethod(
        lambda q: TEMPLATES if q.startswith("SELECT Id, Name, Description, TemplateType, UiType, IsActive, TimesUsed") else records(q)))
    connect(client)
    a, _, _ = run(client)
    body = client.get(f"{API}/assessments/{a['id']}/email-templates")
    assert body.status_code == 200, body.text
    d = body.json()
    assert d["counts"] == {"all": 3, "active": 2, "inactive": 1} and d["totalUsed"] == 40
    welcome = d["templates"][0]  # most used first
    assert (welcome["name"], welcome["description"], welcome["type"], welcome["active"], welcome["usagePct"]) == (
        "Welcome", "First email to a new lead", "Lightning · Custom HTML", True, 75.0)
    assert d["templates"][1]["description"] is None and d["templates"][1]["type"] == "Classic · Text"
    inactive = client.get(f"{API}/assessments/{a['id']}/email-templates", params={"status": "inactive"}).json()
    assert [t["name"] for t in inactive["templates"]] == ["Old Promo"] and inactive["counts"]["all"] == 3
    assert client.get(f"{API}/assessments/{a['id']}/email-templates", params={"status": "draft"}).status_code == 422
