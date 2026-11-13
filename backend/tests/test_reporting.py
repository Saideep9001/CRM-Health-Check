"""Reporting & Dashboards checks (areas 8–11), run against a fake org with known reports and deals."""
import re
from datetime import datetime, timedelta, timezone
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
    "Report": [wf._f("Id", type="id"), wf._f("Name", label="Report Name"), wf._f("FolderName", label="Folder", sortable=True),
               wf._f("ReportTypeApiName", label="Report Type API Name"),
               wf._f("CreatedById", type="reference", label="Created By ID"), wf._f("CreatedDate", type="datetime", label="Created Date"),
               wf._f("LastViewedDate", type="datetime", label="Last Viewed Date"), wf._f("LastRunDate", type="datetime", label="Last Run"), wf._f("LastModifiedById", type="reference", label="Last Modified By ID"),
               wf._f("LastModifiedDate", type="datetime", label="Last Modified Date"), wf._f("OwnerId", type="reference")],
    "Dashboard": [wf._f("Id", type="id"), wf._f("Title"), wf._f("FolderName", label="Folder", sortable=True),
                  wf._f("Type", type="picklist", label="Dashboard Type"), wf._f("CreatedById", type="reference", label="Created By ID"),
                  wf._f("CreatedDate", type="datetime"), wf._f("RunningUserId", type="reference", label="Running User ID"),
                  wf._f("LastModifiedById", type="reference"), wf._f("LastModifiedDate", type="datetime"),
                  wf._f("DashboardResultRefreshedDate", type="datetime")],
    "EventLogFile": [wf._f("Id", type="id")],
    "DashboardComponent": [wf._f("Id", type="id")],
    "OpportunityLineItem": [wf._f("Id", type="id")],
    "OpportunityCompetitor": [wf._f("Id", type="id")],
    "Opportunity": wf.DESCRIBE["Opportunity"] + [wf._f("OwnerId", type="reference", label="Opportunity Owner ID"), wf._f("Name", label="Opportunity Name"),
                                                 wf._f("ExpectedRevenue", type="currency", label="Expected Revenue"),
                                                 wf._f("Probability", type="percent", label="Probability (%)"), wf._f("CloseDate", type="date", label="Close Date"),
                                                 wf._f("AgeInDays", type="int", label="Age"),
                                                 wf._f("HasOpportunityLineItem", type="boolean"), wf._f("Timezone__c", custom=True, label="Opportunity Timezone"),
                                                 wf._f("Region__c", type="picklist", custom=True, label="Region")],
}
# Event Monitoring's Report event log: Pipeline by Stage run 3 times by 2 people, Lost deals by reason once
REPORT_LOG = ("EVENT_TYPE,TIMESTAMP_DERIVED,USER_ID_DERIVED,REPORT_ID_DERIVED\n"
              "Report,2026-11-10T09:00:00Z,005000000000001AAA,00O000000000001AAA\nReport,2026-11-11T09:00:00Z,005000000000002AAA,00O000000000001AAA\n"
              "Report,2026-11-10T10:00:00Z,005000000000001AAA,00O000000000001AAA\nReport,2026-11-09T09:00:00Z,005000000000002AAA,00O000000000004AAA\n")
# the dashboard was last refreshed yesterday (its newest component)
REFRESHED = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT09:30:00.000Z")
COUNTS = [
    (("FROM Report", "LastRunDate = LAST_N_DAYS:30"), 1),
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
        if authed and url.path.endswith("/analytics/dashboards/01Z000000000001AAA/status"):  # when its components were last refreshed
            return httpx.Response(200, json={"componentStatus": [{"componentId": "01a1", "refreshDate": "2026-11-01T08:00:00.000Z"},
                                                                 {"componentId": "01a2", "refreshDate": REFRESHED}]})
        if authed and url.path.endswith("/analytics/reportTypes"):  # report type names, by category
            return httpx.Response(200, json=[{"label": "Opportunities", "reportTypes": [{"label": "Opportunities", "type": "Opportunity"}]}])
        if authed and url.path.endswith("/sobjects/EventLogFile/0AT000000000001AAA/LogFile"):
            return httpx.Response(200, text=REPORT_LOG, headers={"Content-Type": "text/csv"})
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
        if "FROM EventLogFile WHERE EventType = 'Report'" in q:
            return [{"Id": "0AT000000000001AAA", "LogDate": "2026-11-11T00:00:00.000+0000", "LogFileLength": 400}]
        if q.startswith("SELECT Id, Name FROM User WHERE Id IN"):
            return [{"Id": "005000000000001AAA", "Name": "Ann Lee"}, {"Id": "005000000000002AAA", "Name": "Bob Ray"}]
        if q.startswith("SELECT Id, CreatedDate, LastViewedDate, DashboardResultRefreshedDate FROM Dashboard"):
            return [{"Id": "01Z000000000001AAA", "CreatedDate": "2025-01-01T00:00:00.000+0000", "DashboardResultRefreshedDate": None},
                    {"Id": "01Z000000000002AAA", "CreatedDate": "2025-01-01T00:00:00.000+0000", "DashboardResultRefreshedDate": None}]
        if "FROM Dashboard WHERE NamespacePrefix = null ORDER BY FolderName" in q:  # the Dashboards tab
            return [{"Id": "01Z000000000001AAA", "Title": "Sales Leadership", "Type": "SpecifiedUser", "DashboardResultRefreshedDate": None}]
        if q.startswith("SELECT OwnerId g, COUNT(Id) c, SUM(Amount) s0, SUM(ExpectedRevenue) s1 FROM Opportunity"):  # each owner's totals
            return [{"g": "005000000000001AAA", "c": 2, "s0": 150000, "s1": 100000}]
        if "FROM Opportunity" in q and "ORDER BY Owner.Name" in q:  # Sales leadership opportunities, by owner
            return [{"Id": "006000000000011AAA", "OwnerId": "005000000000001AAA", "Owner": {"Name": "John"}, "Name": "ABC Software Deal",
                     "StageName": "Negotiation", "Amount": 50000, "ExpectedRevenue": 40000, "Probability": 80, "CloseDate": "2026-12-15",
                     "AgeInDays": 45, "LeadSource": "Web"}]
        if "FROM DashboardComponent" in q:
            assert "DashboardId IN ('01Z000000000001AAA', '01Z000000000002AAA')" in q  # asked for by dashboard
            d = "01Z000000000001AAA"  # two components show Pipeline by Stage (listed once), one the Old Quarterly Report
            return [{"DashboardId": d, "CustomReportId": "00O000000000001AAA"}, {"DashboardId": d, "CustomReportId": "00O000000000001AAA"},
                    {"DashboardId": d, "CustomReportId": "00O000000000003AAA"}]
        if "FROM Report WHERE NamespacePrefix = null ORDER BY FolderName" in q:  # Report & dashboard usage's records, by folder
            return [{"Id": "00O000000000001AAA", "Name": "Pipeline by Stage", "ReportTypeApiName": "Opportunity", "LastRunDate": None},
                    {"Id": "00O000000000003AAA", "Name": "Old Quarterly Report", "ReportTypeApiName": "CustomEntity$Quota__c", "LastRunDate": None}]
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
    labels = [i["label"] for i in areas["area-8"]["indicators"]]
    assert labels[:2] == ["Report usage", "Dashboard usage"]  # usage and unused together, one card each
    assert not {"Unused reports", "Unused dashboards", "Report & dashboard usage", "Unused reports & dashboards"} & set(labels)
    assert ind["Report usage"] == 2  # 2 reports not run in 180 days
    assert ind["Dashboard usage"] == 1  # Old Board never refreshed; Sales Leadership refreshed yesterday
    cards = {i["label"]: i for i in areas["area-8"]["indicators"]}
    assert cards["Report usage"]["recordObjects"] == ["Report"] and cards["Dashboard usage"]["recordObjects"] == ["Dashboard"]
    assert cards["Report usage"]["score"] == 37.5 and cards["Dashboard usage"]["score"] == 37.5  # half unused (0 at 80%)
    # every report by folder, with Salesforce's own fields and its share of runs frozen last (All, by default)
    page = sf_client_page(client, res)
    assert page["sortedBy"] == "FolderName"
    assert [c["name"] for c in page["columns"] if c["type"] != "id" and not c["hidden"]] == [  # what the table shows
        "FolderName", "Name", "ReportType", "CreatedById", "CreatedDate", "LastViewedDate", "LastRunDate", "LastModifiedById", "LastModifiedDate", "UsagePct"]
    assert page["columns"][-1]["frozen"] and page["columns"][-1]["label"] == "Usage %"
    rows = {r["values"]["Name"]: r["values"] for r in page["records"]}
    assert rows["Pipeline by Stage"]["UsagePct"] == "75.0%" and rows["Old Quarterly Report"]["UsagePct"] == "0%"
    # the report type by the name Salesforce shows; a type the Analytics API doesn't name keeps its API name
    assert (rows["Pipeline by Stage"]["ReportType"], rows["Old Quarterly Report"]["ReportType"]) == ("Opportunities", "CustomEntity$Quota__c")
    assert next(c for c in page["columns"] if c["name"] == "ReportTypeApiName")["hidden"]
    # dashboards: the org's own fields, the reports each one shows, and its usage
    aid = client.get(f"{API}/assessments").json()
    aid = (aid["items"] if isinstance(aid, dict) else aid)[0]["id"]
    dash = client.get(f"{API}/assessments/{aid}/areas/area-8/indicator-records",
                      params={"label": "Dashboard usage", "object": "Dashboard"}).json()
    assert [c["name"] for c in dash["columns"] if c["type"] != "id" and not c["hidden"]] == [
        "FolderName", "Title", "DashboardMode", "CreatedById", "CreatedDate", "DashboardResultRefreshedDate", "LastModifiedById", "LastModifiedDate",
        "SourceReports", "UsagePct"]
    assert next(c for c in dash["columns"] if c["name"] == "DashboardResultRefreshedDate")["label"] == "Last Refreshed Date"
    assert next(c for c in dash["columns"] if c["name"] == "DashboardMode")["label"] == "Dashboard Running User"
    assert dash["records"][0]["values"]["DashboardMode"] == "Static"  # runs as one specified user
    # Salesforce leaves the refreshed date empty: it's the latest component refresh, from the dashboard's status
    assert dash["records"][0]["values"]["DashboardResultRefreshedDate"] == REFRESHED
    assert dash["records"][0]["values"]["SourceReports"] == "Pipeline by Stage\nOld Quarterly Report"
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
    assert all("NamespacePrefix = null" in q for q in sf.soql if re.search(r"FROM (Report|Dashboard)\b", q))
    assert all(q.lstrip().upper().startswith("SELECT") for q in sf.soql)


def test_no_reports_access_skips_report_checks(client, sf):
    report = DESCRIBE.pop("Report")
    try:
        connect(client)
        a, res, _ = wf.run(client, areaIds=["area-8", "area-11"], categoryIds=["reporting"])
        areas = {x["areaId"]: x for x in res["areas"]}
        assert a["status"] == "completed"
        assert "Reports can’t be read" in (areas["area-8"]["message"] or "")
        assert areas["area-11"]["status"] == "assessed"
    finally:
        DESCRIBE["Report"] = report


def sf_client_page(client, res):
    """The Report usage card's records, as the page lists them."""
    aid = res["id"] if "id" in res else None
    assessments = client.get(f"{API}/assessments").json()
    aid = aid or (assessments["items"] if isinstance(assessments, dict) else assessments)[0]["id"]
    got = client.get(f"{API}/assessments/{aid}/areas/area-8/indicator-records", params={"label": "Report usage", "object": "Report"})
    assert got.status_code == 200, got.text
    return got.json()


def test_usage_filter_all_used_unused(client, sf):
    connect(client)
    wf.run(client, areaIds=["area-8"], categoryIds=["reporting"])
    aid = client.get(f"{API}/assessments").json()
    aid = (aid["items"] if isinstance(aid, dict) else aid)[0]["id"]
    url = f"{API}/assessments/{aid}/areas/area-8/indicator-records"

    def page(label, obj, period=None):
        got = client.get(url, params={"label": label, "object": obj, **({"period": period} if period else {})})
        assert got.status_code == 200, got.text
        return got.json()

    last = lambda obj: [q for q in sf.soql if f"FROM {obj} WHERE" in q and "LastModifiedDate" in q][-1].split("WHERE")[1]  # noqa: E731
    # reports: All (no period), Used (run in 180 days), Unused for 30 days (past the grace period), Unused between two dates
    page("Report usage", "Report")
    assert "LastRunDate" not in last("Report")
    page("Report usage", "Report", "all")
    assert "LastRunDate" not in last("Report")
    assert page("Report usage", "Report")["columns"][-1]["name"] == "UsagePct"
    # Used, with Event Monitoring: only the reports with a share of runs (Pipeline by Stage, Lost deals by reason); 0% is Unused
    page("Report usage", "Report", "used")
    assert "Id IN ('00O000000000001', '00O000000000004')" in last("Report") or "Id IN ('00O000000000004', '00O000000000001')" in last("Report")
    unused = page("Report usage", "Report", "30")
    assert "(LastRunDate < LAST_N_DAYS:30 OR LastRunDate = null) AND CreatedDate < LAST_N_DAYS:30" in last("Report")
    assert "UsagePct" not in [c["name"] for c in unused["columns"]]  # no Usage % under Unused
    page("Report usage", "Report", "range:2026-01-01:2026-03-31")
    assert "LastRunDate >= 2026-01-01T00:00:00Z AND LastRunDate <= 2026-03-31T23:59:59Z" in last("Report")
    assert client.get(url, params={"label": "Report usage", "object": "Report", "period": "45"}).status_code == 422
    # dashboards by their last refresh (saved by the check): Used keeps Sales Leadership, Unused for 30 days keeps Old Board
    page("Dashboard usage", "Dashboard", "used")  # no Dashboard event log here: used = refreshed in the last 180 days
    assert "Id IN ('01Z000000000001')" in last("Dashboard")
    page("Dashboard usage", "Dashboard", "30")
    assert "Id IN ('01Z000000000002')" in last("Dashboard")  # 15-character ids, which Salesforce accepts
    page("Dashboard usage", "Dashboard")
    assert "Id IN" not in last("Dashboard")


def test_sales_leadership_opportunities(client, sf):
    connect(client)
    _, res, _ = wf.run(client, areaIds=["area-8"], categoryIds=["reporting"])
    cards = {i["label"]: i for x in res["areas"] for i in x["indicators"]}
    card = cards["Sales leadership opportunities"]
    assert card["score"] is None and card["recordObjects"] == ["Opportunity"]  # for information
    aid = client.get(f"{API}/assessments").json()
    aid = (aid["items"] if isinstance(aid, dict) else aid)[0]["id"]
    url = f"{API}/assessments/{aid}/areas/area-8/indicator-records"

    def page(period=None):
        got = client.get(url, params={"label": "Sales leadership opportunities", "object": "Opportunity", **({"period": period} if period else {})})
        assert got.status_code == 200, got.text
        return got.json()

    listing = lambda: [q for q in sf.soql if "FROM Opportunity" in q and "ORDER BY Owner.Name" in q][-1]  # noqa: E731
    p = page()
    assert p["sortedBy"] == "OwnerId"  # grouped by owner, A to Z
    assert [c["name"] for c in p["columns"] if c["type"] != "id"] == [
        "OwnerId", "Name", "StageName", "Amount", "ExpectedRevenue", "Probability", "CloseDate", "AgeInDays", "LeadSource"]
    assert p["groupTotals"] == {"005000000000001AAA": {"count": 2, "Amount": 150000, "ExpectedRevenue": 100000}}  # John: 2, $150,000, $100,000
    assert "CloseDate" not in listing().split("FROM Opportunity")[1].split("ORDER BY")[0]  # All
    page("this_quarter")
    assert "CloseDate = THIS_QUARTER" in listing()
    totals = [q for q in sf.soql if q.startswith("SELECT OwnerId g")][-1]
    assert "CloseDate = THIS_QUARTER" in totals and totals.endswith("GROUP BY OwnerId")  # totals over the same opportunities
    page("last_quarter")
    assert "CloseDate = LAST_QUARTER" in listing()
    assert client.get(url, params={"label": "Sales leadership opportunities", "object": "Opportunity", "period": "next_year"}).status_code == 422
