"""Deeper outcome checks: empty fields others depend on, automation health, report trust, forecast setup, sync health."""
import re
from urllib.parse import urlparse

import httpx
import pytest

from app.salesforce import explorer

from . import test_workflows as wf
from .conftest import connect

F = wf._f
INTEG = "005000000000009"
DESCRIBE = {
    **wf.DESCRIBE,
    "Opportunity": wf.DESCRIBE["Opportunity"] + [
        F("Region__c", type="picklist", custom=True, label="Region",
          picklistValues=[{"value": "West", "active": True}, {"value": "East", "active": True}]),
        F("ForecastCategoryName", type="picklist"),
    ],
    "FlowInterview": [F("Id", type="id")], "Report": [F("Id", type="id")], "Dashboard": [F("Id", type="id")],
    "AsyncApexJob": [F("Id", type="id")],
}
COUNTS = [
    (("FROM FlowInterview",), 3),
    (("ForecastCategoryName = 'Closed'",), 2),
    (("FROM Contact", "CreatedById IN"), 40),
    (("FROM Lead", "CreatedById IN"), 60),
    (("FROM AsyncApexJob", "Status = 'Failed'"), 5),
    (("FROM AsyncApexJob",), 50),
]


class FakeDeepOrg(wf.FakeSalesOrg):
    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        authed = request.headers.get("authorization", "").removeprefix("Bearer ") in self.valid_access
        if authed and url.path.endswith("/sobjects"):
            return httpx.Response(200, json={"sobjects": [{"name": n, "label": n, "labelPlural": n + "s", "queryable": True, "retrieveable": True} for n in DESCRIBE]})
        if authed and (m := re.search(r"/sobjects/(\w+)/describe$", url.path)):
            return httpx.Response(200, json={"name": m[1], "fields": DESCRIBE[m[1]]})
        if authed and url.path.endswith("/analytics/reports/00O000000000001/describe"):
            return httpx.Response(200, json={"reportMetadata": {"reportFilters": [{"column": "Opportunity.Region__c", "operator": "equals", "value": "North,West"}]}})
        if authed and "/analytics/reports/" in url.path:
            return httpx.Response(404, json=[{"errorCode": "NOT_FOUND", "message": "The column Old_Field__c no longer exists."}])
        return super().handler(request)

    @staticmethod
    def count(q: str) -> int:
        if q.startswith("SELECT COUNT()"):
            for subs, n in COUNTS:
                if all(s in q for s in subs):
                    return n
        return wf.FakeSalesOrg.count(q)

    @staticmethod
    def records(q: str) -> list[dict]:
        if "FROM FlowDefinitionView" in q:
            return [{"ApiName": "PB1", "Label": "Opportunity updates", "ProcessType": "Workflow", "TriggerObjectOrEventLabel": "Opportunity"},
                    {"ApiName": "F1", "Label": "Set owner", "ProcessType": "AutoLaunchedFlow", "TriggerType": "RecordAfterSave", "TriggerObjectOrEventLabel": "Opportunity"}]
        if "ForecastCategoryName, DefaultProbability FROM OpportunityStage" in q:
            return [{"MasterLabel": "Prospecting", "IsClosed": False, "IsWon": False, "ForecastCategoryName": "Pipeline", "DefaultProbability": 10},
                    {"MasterLabel": "Negotiation", "IsClosed": False, "IsWon": False, "ForecastCategoryName": "Closed", "DefaultProbability": 90},
                    {"MasterLabel": "Closed Won", "IsClosed": True, "IsWon": True, "ForecastCategoryName": "Closed", "DefaultProbability": 100},
                    {"MasterLabel": "Closed Lost", "IsClosed": True, "IsWon": False, "ForecastCategoryName": "Pipeline", "DefaultProbability": 0}]
        if "FROM Report WHERE NamespacePrefix = null AND LastRunDate" in q:
            return [{"Id": "00O000000000001", "Name": "Pipeline by Region"}, {"Id": "00O000000000002", "Name": "Old KPI report"}]
        if "FROM Dashboard" in q and "RunningUser.IsActive = false" in q:
            return [{"Id": "01Z000000000001", "Title": "Exec KPIs"}]
        if "SELECT Id, Name, Profile.Name FROM User WHERE IsActive = true LIMIT 2000" in q:
            return [{"Id": INTEG, "Name": "HubSpot Integration", "Profile": {"Name": "API Only"}}, {"Id": "005000000000001", "Name": "Ann Lee", "Profile": {"Name": "Sales"}}]
        if q.startswith("SELECT LastModifiedById u"):
            return [{"u": INTEG, "m": "2020-01-01T00:00:00.000+0000", "c": 50}] if "FROM Account" in q else []
        if q.startswith("SELECT Email v") and "FROM Contact" in q:
            return [{"v": "a@x.com", "c": 3}]
        return wf.FakeSalesOrg.records(q)

    @staticmethod
    def tooling(q: str) -> list[dict]:
        if "FROM CustomField" in q:
            return [{"Id": "00N000000000001", "DeveloperName": "Region", "TableEnumOrId": "Opportunity"}]
        if "FROM MetadataComponentDependency" in q:
            return [{"MetadataComponentType": "Report", "MetadataComponentName": "Pipeline by Region", "RefMetadataComponentId": "00N000000000001"},
                    {"MetadataComponentType": "Flow", "MetadataComponentName": "Set owner", "RefMetadataComponentId": "00N000000000001"},
                    {"MetadataComponentType": "Layout", "MetadataComponentName": "Opp Layout", "RefMetadataComponentId": "00N000000000001"}]
        if "FROM ApexTrigger" in q:
            return [{"Name": "OppTrigger", "TableEnumOrId": "Opportunity"}]
        if "FROM WorkflowRule" in q:
            return [{"Id": "01Q000000000001", "Name": "Old lead rule", "TableEnumOrId": "Lead"}]
        return wf.FakeSalesOrg.tooling(q)


@pytest.fixture
def sf():
    explorer.clear_cache()
    return FakeDeepOrg()


def test_deep_checks(client, sf):
    connect(client)
    areas = ["area-2", "area-7", "area-8", "area-10", "area-20"]
    cats = ["data-quality", "workflows", "reporting", "integrations"]
    _, res, findings = wf.run(client, areaIds=areas, categoryIds=cats, objects=["Account", "Contact", "Lead", "Opportunity"])
    ind = {i["label"]: i["value"] for x in res["areas"] for i in x["indicators"]}
    dep_card = next(k for k in ind if k.startswith("Empty Fields Others Depend On (Opportunit"))  # the fake org's plural label
    assert ind[dep_card] == 1  # Region__c: empty, used by a report and a flow (layout ignored)
    assert ind["Legacy automation to migrate"] == 2 and ind["Overlapping automation"] == 1  # Opportunity: PB + flow + trigger
    assert ind["Stuck or failing automations"] == 3
    assert ind["Report trust issues"] == 3  # retired "North" filter + a report that errors + a dashboard run by a leaver
    assert ind["Forecast setup issues"] == 3  # open stage in Closed, lost stage in Pipeline, 2 open deals filed as Closed
    assert ind["Sync health score"] == 43.0  # stalled sync (-40), 2 dupes of 100 created (-2), 10% failed jobs (-15)

    names = {f["name"]: f for f in findings}
    dep = next(f for n, f in names.items() if n.startswith("Nearly empty fields that reports and automation rely on (Opportunit"))
    assert "Region (0% filled) — used by 1 report, 1 flow" in dep["description"] and dep["measure"] == dep_card
    assert "Opportunity: 1 Process Builder, 1 record-triggered flow, 1 Apex trigger" in names["Objects automated by several tools at once"]["description"]
    assert "Process Builders and Workflow Rules to move to Flow" in names and "Flows stuck waiting for more than a week" in names
    assert "retired value(s) North" in names["Reports filtering on retired values or empty fields"]["description"]
    assert "Old KPI report" in names["Reports that no longer run"]["description"]
    assert "Exec KPIs" in names["Dashboards running as people who have left"]["description"]
    assert "open stage “Negotiation” is in “Closed”" in names["Sales stages mapped to the wrong forecast category"]["description"]
    assert names["Sales stages mapped to the wrong forecast category"]["severity"] == "high"
    closed = names["Open deals counted as closed in the forecast"]
    assert closed["affectedRecords"] == 2 and closed["valueAtRisk"] == 50000 and closed["recordsAvailable"]
    sync = names["Integrations aren’t syncing cleanly"]
    assert "HubSpot Integration" in sync["description"] and sync["severity"] == "high"
    assert all(q.lstrip().upper().startswith("SELECT") for q in sf.soql)


def test_deep_checks_without_setup_access(client, sf):
    sf.tooling_ok = False
    connect(client)
    _, res, _ = wf.run(client, areaIds=["area-7", "area-20"], categoryIds=["workflows", "integrations"])
    msgs = " ".join(x["message"] or "" for x in res["areas"])
    assert "unexpected error" not in msgs
    ind = {i["label"] for x in res["areas"] for i in x["indicators"]}
    assert "Sync health score" in ind  # doesn't need setup access
