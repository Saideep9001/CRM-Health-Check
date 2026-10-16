"""User Adoption (areas 12–14) and Quoting (areas 15–17), run against a fake org with known users, deals, quotes and discounts."""
import re
from urllib.parse import urlparse

import httpx
import pytest

from app.salesforce import explorer

from . import test_workflows as wf
from .conftest import connect

ADOPTION = ("area-12", "area-13", "area-14")
QUOTING = ("area-15", "area-16", "area-17")
F = wf._f
ANN, BOB, CARA, DAN = "005000000000001", "005000000000002", "005000000000004", "005000000000005"
STD_BOOK = "01s000000000001AAA"
O1, O2, O3 = "006000000000001AAA", "006000000000002AAA", "006000000000003AAA"

DESCRIBE = {
    **wf.DESCRIBE,
    "User": [F("Id", type="id"), F("Name"), F("LastLoginDate", type="datetime"), F("UserRoleId", type="reference"),
             F("UserPreferencesLightningExperiencePreferred", type="boolean")],
    "Organization": [F("Id", type="id"), F("DefaultOpportunityAccess", type="picklist"), F("DefaultLeadAccess", type="picklist")],
    "PermissionSet": [F("Id", type="id")], "PermissionSetAssignment": [F("Id", type="id")], "UserRole": [F("Id", type="id")],
    "ListView": [F("Id", type="id"), F("Name"), F("SobjectType"), F("LastViewedDate", type="datetime")],
    "Opportunity": wf.DESCRIBE["Opportunity"] + [
        F("HasOpportunityLineItem", type="boolean"), F("SyncedQuoteId", type="reference"), F("Probability", type="percent"),
        F("Region__c", custom=True, inlineHelpText="Sales region that owns the deal")],
    "Product2": [F("Id", type="id"), F("Name"), F("ProductCode"), F("Family", type="picklist")],
    "Pricebook2": [F("Id", type="id")], "PricebookEntry": [F("Id", type="id")], "OpportunityLineItem": [F("Id", type="id")],
    "Quote": [F("Id", type="id"), F("Status", type="picklist"), F("OpportunityId", type="reference")],
    "ProcessInstance": [F("Id", type="id")], "ProcessDefinition": [F("Id", type="id")],
}

PEOPLE = [
    {"Id": ANN, "Name": "Ann Lee", "Profile": {"Name": "Sales"}, "LastLoginDate": "2099-01-01T00:00:00.000+0000", "UserRoleId": "00E000000000001", "UserPreferencesLightningExperiencePreferred": True},
    {"Id": BOB, "Name": "Bob Ray", "Profile": {"Name": "Sales", "UserLicense": {"Name": "Salesforce"}}, "LastLoginDate": "2020-01-01T00:00:00.000+0000", "UserRoleId": None, "UserPreferencesLightningExperiencePreferred": False},
    {"Id": CARA, "Name": "Cara Diaz", "Profile": {"Name": "System Administrator", "UserLicense": {"Name": "Salesforce Platform"}}, "LastLoginDate": None, "UserRoleId": None, "UserPreferencesLightningExperiencePreferred": True},
    {"Id": DAN, "Name": "Dan Wu", "Profile": {"Name": "Sales"}, "LastLoginDate": "2099-01-01T00:00:00.000+0000", "UserRoleId": "00E000000000001", "UserPreferencesLightningExperiencePreferred": False},
    {"Id": "005000000000009", "Name": "Integration User", "Profile": {"Name": "Sales"}, "LastLoginDate": None},
]

COUNTS = [
    (("FROM Opportunity", "IsWon = true", "HasOpportunityLineItem = false"), 5),
    (("FROM Opportunity", "IsWon = true", "LAST_N_DAYS:365"), 20),
    (("FROM Opportunity", "HasOpportunityLineItem = false"), 12),
    (("FROM Opportunity", "Product2.IsActive = false"), 3),
    (("FROM Opportunity", "SyncedQuoteId = null"), 4),
    (("FROM Opportunity", "SyncedQuote.ExpirationDate"), 2),
    (("FROM Opportunity", "Probability >= 50", "NOT IN (SELECT OpportunityId FROM Quote)"), 6),
    (("FROM Opportunity", "Probability >= 50"), 15),
    (("FROM Opportunity", "Id IN (SELECT OpportunityId FROM Quote)"), 10),
    (("FROM Opportunity", "IsClosed = false"), 30),
    (("FROM Product2", "Family = null"), 4),
    (("FROM Product2", "ProductCode = null"), 2),
    (("FROM Product2", "NOT IN (SELECT Product2Id"), 3),
    (("FROM Product2",), 25),
    (("FROM PricebookEntry", "UnitPrice = 0"), 1),
    (("FROM Quote", "Status = 'Draft'"), 2),
    (("FROM Quote",), 50),
]


def per_owner(q: str) -> list[dict]:
    if "LastModifiedDate < LAST_N_DAYS:30" in q:
        return [{"o": ANN, "c": 1, "a": 1000}, {"o": BOB, "c": 5, "a": 50000}]
    if "CloseDate < TODAY" in q:
        return [{"o": ANN, "c": 1}, {"o": BOB, "c": 4}]
    return [{"o": ANN, "c": 10, "a": 100000}, {"o": BOB, "c": 6, "a": 60000}]


class FakeAdoptionQuotingOrg(wf.FakeSalesOrg):
    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        authed = request.headers.get("authorization", "").removeprefix("Bearer ") in self.valid_access
        if authed and url.path.endswith("/sobjects"):
            return httpx.Response(200, json={"sobjects": [{"name": n, "label": n, "labelPlural": n + "s", "custom": n.endswith("__c"), "queryable": True, "retrieveable": True} for n in DESCRIBE]})
        if authed and (m := re.search(r"/sobjects/(\w+)/describe$", url.path)):
            return httpx.Response(200, json={"name": m[1], "fields": DESCRIBE[m[1]]})
        if authed and url.path.endswith("/query") and "DefaultOpportunityAccess" in request.url.params.get("q", ""):
            return httpx.Response(200, json={"records": [{"DefaultOpportunityAccess": "Edit", "DefaultLeadAccess": "Read"}], "totalSize": 1, "done": True})
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
        if "FROM User WHERE IsActive = true AND UserType = 'Standard' ORDER BY Name" in q:
            return PEOPLE
        if "FROM UserRole" in q:
            return [{"Id": "00E000000000001", "Name": "Sales Rep", "ParentRoleId": "00E000000000002"}, {"Id": "00E000000000002", "Name": "VP Sales", "ParentRoleId": None}]
        if "FROM PermissionSetAssignment WHERE PermissionSet.PermissionsModifyAllData" in q:
            return [{"AssigneeId": i} for i in (ANN, BOB, CARA)]
        if "FROM PermissionSet WHERE" in q:
            return [{"Id": f"0PS00000000000{i}", "Label": f"Set {i}"} for i in range(4)]
        if q.startswith("SELECT PermissionSetId p"):
            return [{"p": "0PS000000000000", "c": 3}]
        if "FROM ListView" in q:
            return [{"Id": f"00B{i}", "Name": f"View {i}", "SobjectType": "Opportunity", "LastViewedDate": None if i < 6 else "2026-10-01T00:00:00.000+0000"} for i in range(10)]
        if q.startswith("SELECT OwnerId o") and "FROM Opportunity" in q:
            return per_owner(q)
        if q.startswith("SELECT OwnerId o") and "FROM Task" in q:
            return [{"o": ANN, "c": 12}]
        if "FROM Pricebook2 WHERE IsStandard = true" in q:
            return [{"Id": STD_BOOK, "IsActive": True}]
        if "FROM Pricebook2" in q:
            return [{"Id": STD_BOOK, "Name": "Standard", "IsActive": True, "IsStandard": True}, {"Id": "01s000000000002AAA", "Name": "Partner Prices", "IsActive": True, "IsStandard": False}]
        if q.startswith("SELECT Pricebook2Id p"):
            return [{"p": STD_BOOK, "c": 22}]
        if "FROM ProcessInstance WHERE Status = 'Pending'" in q:
            return [{"Id": "04g1", "TargetObject": {"Name": "Deal A quote"}, "CreatedDate": "2020-01-01T00:00:00.000+0000"},
                    {"Id": "04g2", "TargetObject": {"Name": "Deal B quote"}, "CreatedDate": "2020-02-01T00:00:00.000+0000"},
                    {"Id": "04g3", "TargetObject": {"Name": "Deal C quote"}, "CreatedDate": "2099-01-01T00:00:00.000+0000"}]
        if "FROM Quote WHERE OpportunityId IN" in q:
            return [{"Id": "0Q0000000000001AAA", "OpportunityId": O2, "Status": "Approved"}]
        if "FROM ProcessInstance" in q or "FROM ProcessDefinition" in q:
            return []
        if "FROM OpportunityLineItem" in q:
            return [
                {"OpportunityId": O1, "Quantity": 1, "ListPrice": 10000, "TotalPrice": 7000, "Opportunity": {"Name": "Deal A", "Owner": {"Name": "Ann Lee"}}, "Product2": {"Name": "Platform"}},
                {"OpportunityId": O2, "Quantity": 2, "ListPrice": 5000, "TotalPrice": 9500, "Opportunity": {"Name": "Deal B", "Owner": {"Name": "Bob Ray"}}, "Product2": {"Name": "Support"}},
                {"OpportunityId": O3, "Quantity": 1, "ListPrice": 20000, "TotalPrice": 20000, "Opportunity": {"Name": "Deal C", "Owner": {"Name": "Ann Lee"}}, "Product2": {"Name": "Platform"}},
            ]
        return wf.FakeSalesOrg.records(q)


@pytest.fixture
def sf():
    explorer.clear_cache()
    return FakeAdoptionQuotingOrg()


def _ok(res, areas):
    by = {x["areaId"]: x for x in res["areas"]}
    assert all(by[i]["status"] == "assessed" for i in areas), {i: by[i]["message"] for i in areas}
    assert not any("unexpected error" in (x["message"] or "") for x in res["areas"]), [x["message"] for x in res["areas"]]


def test_user_adoption(client, sf):
    connect(client)
    a, res, findings = wf.run(client, areaIds=list(ADOPTION), categoryIds=["user-adoption"])
    assert a["status"] == "completed", a
    _ok(res, ADOPTION)
    ind = {i["label"]: i["value"] for x in res["areas"] for i in x["indicators"]}
    assert ind["Inactive users"] == 2 and ind["Login activity"] == 50.0  # Bob (old) and Cara (never); Ann + Dan weekly
    assert ind["Low adoption indicators"] == 1 and ind["Training opportunities"] == 1  # Bob: no activity, 5 of 6 stale, 4 of 6 sloppy
    assert ind["Excessive permissions"] == 3 and ind["Role hierarchy issues"] == 1  # Bob has no role
    assert ind["Permission configuration concerns"] == 2  # public read/write deals + 3 unused permission sets
    assert ind["Missing field help text"] == 50.0 and ind["Home page improvement opportunities"] == 1
    assert ind["List view usability"] == 1 and ind["Navigation improvement opportunities"] == 2  # Bob + Dan on Classic

    names = {f["name"]: f for f in findings}
    lic = names["Paid licenses not being used"]
    assert lic["valueAtRisk"] == 1 * 165 * 12 and "1 of them is on full Salesforce licences" in lic["description"] and "Integration User" not in lic["description"] and lic["recordsAvailable"]
    stale = names["Reps whose pipeline is going stale"]
    assert "Bob Ray" in stale["description"] and "Ann Lee" not in stale["description"] and stale["valueAtRisk"] == 50000
    for expected in ("Few people log in each week", "Reps who need coaching on deal updates", "Too many people can change all data",
                     "Sales users without a role", "Everyone can edit every deal", "Permission sets nobody uses",
                     "Custom fields without help text", "No custom home page for the sales team", "Cluttered or unused list views",
                     "People still using Salesforce Classic"):
        assert expected in names, expected
    assert names["Everyone can edit every deal"]["fixUrl"].endswith("/lightning/setup/SecuritySharing/home")
    assert all(q.lstrip().upper().startswith("SELECT") for q in sf.soql)


def test_quoting(client, sf):
    connect(client)
    a, res, findings = wf.run(client, areaIds=list(QUOTING), categoryIds=["quoting"])
    assert a["status"] == "completed", a
    _ok(res, QUOTING)
    ind = {i["label"]: i["value"] for x in res["areas"] for i in x["indicators"]}
    assert ind["Opportunities without products"] == 40.0  # 12 of 30 open deals
    assert ind["Product configuration concerns"] == 5  # 3 without a standard price + 2 without a code
    assert ind["Pricebook configuration"] == 2  # empty partner price book + a zero price
    assert ind["Product reporting gaps"] == 25.0  # 5 of 20 won deals
    assert ind["Quote configuration"] == 0 and ind["Quote synchronization concerns"] == 4
    assert ind["Missing Quote visibility"] == 40.0 and ind["Quote process gaps"] == 4  # 2 expired + 2 old drafts
    assert ind["Pending approvals"] == 3 and ind["Delayed approvals"] == 2
    assert ind["Discount approval configuration"] == 1 and ind["Approval workflow gaps"] == 1

    names = {f["name"]: f for f in findings}
    leak = names["Revenue given away in discounts"]
    assert leak["valueAtRisk"] == 3500 and "9%" in leak["description"] and "Ann Lee (3,000)" in leak["description"]
    gap = names["Big discounts that skipped approval"]
    assert gap["affectedRecords"] == 1 and gap["valueAtRisk"] == 3000 and "Deal A" in gap["description"]
    for expected in ("Open deals with no products", "Active products missing a price", "Open deals with retired products",
                     "Price books with no products", "Products priced at zero", "Won deals with no products recorded",
                     "Deals out of sync with their quotes", "Late-stage deals with no quote", "Expired or forgotten quotes",
                     "Approvals waiting more than 3 days", "No approval process for discounts"):
        assert expected in names, expected
    assert "4 active products have no product family" in names["Won deals with no products recorded"]["description"]


def test_cpq_migration_readiness(client, sf):
    DESCRIBE.update({"SBQQ__Quote__c": [F("Id", type="id"), F("SBQQ__Opportunity2__c", type="reference")],
                     "SBQQ__PriceRule__c": [F("Id", type="id")], "SBQQ__CustomScript__c": [F("Id", type="id")]})
    COUNTS.insert(0, (("FROM SBQQ__PriceRule__c",), 12))
    COUNTS.insert(0, (("FROM SBQQ__CustomScript__c",), 2))
    COUNTS.insert(0, (("FROM SBQQ__Quote__c",), 400))
    try:
        connect(client)
        _, res, findings = wf.run(client, areaIds=["area-16"], categoryIds=["quoting"])
        f = next(x for x in findings if x["name"].startswith("Salesforce CPQ is no longer sold"))
        assert "Migration complexity: Medium" in f["description"] and "12 price rules" in f["description"]  # 12*3 + 2*10 = 56 points
        assert f["severity"] == "medium"
    finally:
        for k in ("SBQQ__Quote__c", "SBQQ__PriceRule__c", "SBQQ__CustomScript__c"):
            DESCRIBE.pop(k)
        del COUNTS[:3]
