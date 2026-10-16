"""Integrations, API & Data Flow checks (areas 18–21), run against a fake org with known connections and limits."""
import re
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.salesforce import explorer

from . import test_reporting as rp
from . import test_workflows as wf
from .conftest import connect

API = "/api/v1"
AREAS = ("area-18", "area-19", "area-20", "area-21")

DESCRIBE = {
    **rp.DESCRIBE,
    "Campaign": [wf._f("Id", type="id")],
    "AsyncApexJob": [wf._f("Id", type="id")],
    "Account": rp.DESCRIBE["Account"] + [wf._f("ERP_Id__c", custom=True, externalId=True, label="ERP Customer ID")],
    "Opportunity": rp.DESCRIBE["Opportunity"] + [wf._f("CampaignId", type="reference"), wf._f("ERP_Order_Id__c", custom=True, label="ERP Order ID")],
}
COUNTS = [
    (("FROM Lead", "LAST_N_DAYS:90", "Email = null OR LeadSource = null"), 10),
    (("FROM Lead", "CreatedDate = LAST_N_DAYS:90"), 40),
    (("FROM Campaign",), 5),
    (("FROM Opportunity", "CampaignId = null"), 45),
    (("FROM Account", "ERP_Id__c = null"), 80),
    (("FROM Opportunity", "LAST_N_DAYS:90", "ERP_Order_Id__c = null"), 4),
    (("FROM Opportunity", "IsWon = true", "LAST_N_DAYS:90"), 12),
    (("FROM AsyncApexJob", "Status = 'Failed'"), 30),
    (("FROM AsyncApexJob",), 100),
]
LIMITS = {
    "DailyApiRequests": {"Max": 15000, "Remaining": 2000},
    "DailyAsyncApexExecutions": {"Max": 250000, "Remaining": 10000},
    "DataStorageMB": {"Max": 1000, "Remaining": 150},
    "FileStorageMB": {"Max": 2000, "Remaining": 1900},
    "SingleEmail": {"Max": 5000, "Remaining": 4900},
}


class FakeIntegrationsOrg(rp.FakeReportingOrg):
    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        authed = request.headers.get("authorization", "").removeprefix("Bearer ") in self.valid_access
        if authed and url.path.endswith("/limits/recordCount"):
            return httpx.Response(200, json={"sObjects": [{"name": "Task", "count": 2_500_000}, {"name": "FieldPermissions", "count": 3_000_000}, {"name": "Account", "count": 100}]})
        if authed and url.path.endswith("/limits"):
            return httpx.Response(200, json=LIMITS)
        if authed and url.path.endswith("/sobjects"):
            return httpx.Response(200, json={"sobjects": [{"name": n, "label": n, "labelPlural": n + "s", "custom": n.endswith("__c"), "queryable": True, "retrieveable": True} for n in DESCRIBE]})
        if authed and (m := re.search(r"/sobjects/(\w+)/describe$", url.path)):
            return httpx.Response(200, json={"name": m[1], "fields": DESCRIBE[m[1]]})
        return super().handler(request)

    @staticmethod
    def count(q: str) -> int:
        if q.startswith("SELECT COUNT()"):
            for subs, n in COUNTS:
                if all(s in q for s in subs):
                    return n
        return rp.FakeReportingOrg.count(q)

    @staticmethod
    def records(q: str) -> list[dict]:
        if "FROM ConnectedApplication" in q:
            return [{"Name": "MuleSoft Anypoint"}, {"Name": "Old Survey App"}]
        if "FROM OauthToken" in q:
            return [{"AppName": "MuleSoft Anypoint", "LastUsedDate": "2026-10-10T00:00:00.000+0000"},
                    {"AppName": "Old Survey App", "LastUsedDate": "2024-01-01T00:00:00.000+0000"}]
        if "FROM User WHERE IsActive = true AND UserType = 'Standard'" in q:
            return [{"Id": "005000000000009", "Name": "Integration User", "Profile": {"Name": "System Administrator"}},
                    {"Id": "005000000000001", "Name": "Ann Lee", "Profile": {"Name": "Sales"}}]
        if q.startswith("SELECT ApexClass.Name n"):
            return [{"n": "ErpSyncJob", "c": 30}]
        if "FROM Report WHERE NamespacePrefix = null ORDER BY Name" in q:
            return rp.REPORTS + [{"Id": "00O000000000009", "Name": "Pipeline by Stage", "FolderName": "Marketing"}]
        return rp.FakeReportingOrg.records(q)

    @staticmethod
    def tooling(q: str) -> list[dict]:
        if "FROM InstalledSubscriberPackage" in q:
            return [{"SubscriberPackage": {"Name": "HubSpot Integration", "NamespacePrefix": "HubSpot_Inc"}}]
        return wf.FakeSalesOrg.tooling(q)


@pytest.fixture
def sf():
    explorer.clear_cache()
    return FakeIntegrationsOrg()


def test_all_integration_areas(client, sf):
    connect(client)
    a, res, findings = wf.run(client, areaIds=list(AREAS), categoryIds=["integrations"])
    assert a["status"] == "completed", a
    areas = {x["areaId"]: x for x in res["areas"]}
    assert all(areas[i]["status"] == "assessed" for i in AREAS), {i: areas[i]["message"] for i in AREAS}
    assert not any("unexpected error" in (x["message"] or "") for x in res["areas"]), [x["message"] for x in res["areas"]]
    ind = {i["label"]: i["value"] for x in res["areas"] for i in x["indicators"]}
    assert ind["Marketing integration status"] == 0  # HubSpot found
    assert ind["Lead synchronization concerns"] == 25.0 and ind["Campaign visibility"] == 75.0
    assert ind["Integration configuration gaps"] == 1  # admin-profile integration user
    assert ind["Missing external identifiers"] == 80.0 and ind["Potential synchronization gaps"] == 4
    assert ind["Order integration visibility"] == 1 and ind["ERP integration concerns"] == 0  # MuleSoft connected
    assert round(ind["API usage"]) == 87 and ind["API limit monitoring"] == 1  # async apex at 96%
    assert ind["Connected application visibility"] == 1 and ind["Integration health indicators"] == 30
    assert ind["BI integration visibility"] == 1 and ind["Data extraction concerns"] == 1
    assert ind["Storage utilization indicators"] == 85.0 and ind["Reporting consistency concerns"] == 1
    assert res["categories"][0]["categoryId"] == "integrations"

    names = {f["name"]: f for f in findings}
    for expected in ("Integration users have full admin rights", "Won deals that didn’t reach finance", "High daily API usage",
                     "Salesforce limits close to their maximum", "Connected apps with old, unused access", "Failed background jobs",
                     "Very large objects", "Storage is filling up", "Reports with the same name", "New leads arriving incomplete"):
        assert expected in names, expected
    assert "FieldPermissions" not in names["Very large objects"]["description"] and "Task" in names["Very large objects"]["description"]
    assert "Old Survey App" in names["Connected apps with old, unused access"]["description"]
    assert "ErpSyncJob (30)" in names["Failed background jobs"]["description"]
    assert names["Salesforce limits close to their maximum"]["severity"] == "high"
    assert all(q.lstrip().upper().startswith("SELECT") for q in sf.soql)


def test_without_setup_access(client, sf):
    sf.tooling_ok = False
    connect(client)
    a, res, _ = wf.run(client, areaIds=list(AREAS), categoryIds=["integrations"])
    assert a["status"] == "completed"
    areas = {x["areaId"]: x for x in res["areas"]}
    ind = {i["label"] for x in res["areas"] for i in x["indicators"]}
    assert "API usage" in ind and "Storage utilization indicators" in ind  # limits still readable
    assert areas["area-20"]["status"] == "assessed"
