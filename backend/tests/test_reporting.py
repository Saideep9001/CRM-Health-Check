"""Reporting & Dashboards checks (areas 8–11), run against a fake org with known reports and deals."""
import re
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.salesforce import explorer

from . import test_workflows as wf
from .conftest import connect

API = "/api/v1"
AREAS = ("area-8", "area-9", "area-10", "area-11")

REPORTS = [
    {"Id": "00O000000000001", "Name": "Pipeline by Stage", "FolderName": "Sales Leadership"},
    {"Id": "00O000000000002", "Name": "Copy of Pipeline by Stage", "FolderName": "Unfiled Public Reports"},
    {"Id": "00O000000000003", "Name": "Old Quarterly Report", "FolderName": "Archive"},
    {"Id": "00O000000000004", "Name": "Lost deals by reason", "FolderName": "Sales Leadership"},
]
DESCRIBE = {
    **wf.DESCRIBE,
    "Report": [wf._f("Id", type="id")],
    "Dashboard": [wf._f("Id", type="id")],
    "OpportunityLineItem": [wf._f("Id", type="id")],
    "OpportunityCompetitor": [wf._f("Id", type="id")],
    "Opportunity": wf.DESCRIBE["Opportunity"] + [wf._f("HasOpportunityLineItem", type="boolean"), wf._f("Timezone__c", custom=True, label="Opportunity Timezone"),
                                                 wf._f("Region__c", type="picklist", custom=True, label="Region")],
}
COUNTS = [
    (("FROM Report", "LastRunDate"), 2),
    (("FROM Report",), 4),
    (("FROM Dashboard", "LastViewedDate"), 1),
    (("FROM Dashboard",), 3),
    (("FROM Opportunity", "LeadSource = null"), 12),
    (("FROM Opportunity", "LastStageChangeDate = null"), 7),
    (("FROM Opportunity", "Region__c = null"), 10),
    (("FROM Opportunity", "IsWon = true", "LAST_N_DAYS:365"), 30),
    (("FROM Opportunity", "IsWon = false", "LAST_N_DAYS:365", "Loss_Reason__c = null"), 5),
    (("FROM Opportunity", "IsWon = false", "LAST_N_DAYS:365"), 20),
    (("FROM Opportunity", "IsClosed = true", "LAST_N_DAYS:365", "OpportunityCompetitor"), 10),
    (("FROM Opportunity", "IsClosed = true", "LAST_N_DAYS:365"), 50),
    (("FROM Opportunity", "HasOpportunityLineItem = false"), 25),
    (("FROM Opportunity", "CreatedDate = LAST_N_DAYS:365"), 60),
]


class FakeReportingOrg(wf.FakeSalesOrg):
    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        authed = request.headers.get("authorization", "").removeprefix("Bearer ") in self.valid_access
        if authed and url.path.endswith("/sobjects"):
            return httpx.Response(200, json={"sobjects": [{"name": n, "label": n, "labelPlural": n + "s", "queryable": True, "retrieveable": True} for n in DESCRIBE]})
        if authed and (m := re.search(r"/sobjects/(\w+)/describe$", url.path)):
            return httpx.Response(200, json={"name": m[1], "fields": DESCRIBE[m[1]]})
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
        if "FROM Report WHERE NamespacePrefix = null ORDER BY Name" in q:
            return REPORTS
        if q.startswith("SELECT Name, FolderName, LastRunDate FROM Report"):
            return REPORTS[2:3]
        if "FROM Dashboard WHERE NamespacePrefix = null ORDER BY Title" in q:
            return [{"Id": "01Z1", "Title": "Sales Leadership"}]
        if "FROM Task WHERE CreatedDate = LAST_N_DAYS:30" in q:
            return [{"o": "005000000000001", "c": 9}, {"o": "005000000000002", "c": 2}]
        if q.startswith("SELECT WhatId w"):
            return [{"w": "006000000000001AAA", "c": 1}]
        if "FROM Opportunity WHERE IsClosed = false AND Id IN" in q:
            return [{"Id": "006000000000001AAA"}]
        if "FROM FieldDefinition" in q:
            return [{"QualifiedApiName": "Status", "IsFieldHistoryTracked": False}]
        if "FROM OpportunityLineItem" in q:
            return [{"a": "001A", "f": "Software", "c": 2}, {"a": "001A", "f": "Services", "c": 1}, {"a": "001B", "f": "Software", "c": 1}]
        if q.startswith("SELECT Loss_Reason__c v"):
            return [{"v": "Price", "c": 9}, {"v": "Competitor", "c": 6}]
        return wf.FakeSalesOrg.records(q)


@pytest.fixture
def sf():
    explorer.clear_cache()
    return FakeReportingOrg()


def test_all_reporting_areas(client, sf):
    connect(client)
    _, res, findings = wf.run(client, areaIds=list(AREAS), categoryIds=["reporting"])
    areas = {x["areaId"]: x for x in res["areas"]}
    assert all(areas[i]["status"] == "assessed" for i in AREAS), {i: areas[i]["message"] for i in AREAS}
    assert not any("unexpected error" in (x["message"] or "") for x in res["areas"]), [x["message"] for x in res["areas"]]
    ind = {i["label"]: i["value"] for x in res["areas"] for i in x["indicators"]}
    assert ind["Unused reports"] == 2 and ind["Unused dashboards"] == 1
    assert ind["Reporting organization issues"] == 1  # the unfiled "Copy of …" report, counted once
    assert ind["Leadership reporting gaps"] == 3  # only pipeline and win/loss-ish names exist
    assert ind["Sales activity gaps"] == 1  # Bob logged 2 in 30 days
    assert ind["Opportunities without open Tasks"] == 39  # 40 open, 1 with an open task
    assert ind["Marketing-to-sales handoff visibility"] == 20.0  # 12 of 60 new deals have no source
    assert ind["Pipeline progression gaps"] == 7 and ind["Regional performance visibility"] == 25.0
    assert ind["Closed Lost trends"] == 25.0  # 5 of 20 lost without reason
    assert ind["Competitor tracking gaps"] == 80.0 and ind["Product visibility issues"] == 25
    assert ind["Upsell opportunity visibility"] == 1  # 001B bought only Software
    assert res["categories"][0]["categoryId"] == "reporting" and res["salesProcessScore"] is not None

    names = {f["name"]: f for f in findings}
    assert "Reports nobody runs" in names and "Old Quarterly Report" in names["Reports nobody runs"]["description"]
    assert "Key leadership reports are missing" in names and "Forecast" in names["Key leadership reports are missing"]["description"]
    assert "Lead Status changes aren’t tracked" in names
    assert "Customers who bought only one product line" in names
    assert "No report analyses why deals are lost" not in names  # "Lost deals by reason" exists
    assert "Region" in names["Open deals with no region"]["description"]  # not the Timezone field
    assert all("NamespacePrefix = null" in q for q in sf.soql if "FROM Report" in q or "FROM Dashboard" in q)
    assert all(q.lstrip().upper().startswith("SELECT") for q in sf.soql)


def test_no_reports_access_skips_report_checks(client, sf):
    DESCRIBE.pop("Report")
    try:
        connect(client)
        a, res, _ = wf.run(client, areaIds=["area-8", "area-11"], categoryIds=["reporting"])
        areas = {x["areaId"]: x for x in res["areas"]}
        assert a["status"] == "completed"
        assert "Reports can’t be read" in (areas["area-8"]["message"] or "")
        assert areas["area-11"]["status"] == "assessed"
    finally:
        DESCRIBE["Report"] = [wf._f("Id", type="id")]
