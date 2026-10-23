"""Find & ask: questions become safe filters; search spans objects."""
import json

import pytest

from app.salesforce import finder

from .conftest import connect

API = "/api/v1/data"


@pytest.fixture(autouse=True)
def _fresh_cache():
    # Other tests use a different fake org under the same org id; don't reuse their cached describes.
    finder.explorer.clear_cache()


def F(name, type_, label=None, **kw):
    return {"name": name, "label": label or name, "type": type_, "filterable": True, "sortable": True, **kw}


def pick(*values):
    return [{"value": v, "active": True} for v in values]


DESCRIBE = {
    "Opportunity": {"fields": [
        F("Id", "id"), F("Name", "string", "Opportunity Name", nameField=True), F("Amount", "currency"),
        F("CloseDate", "date", "Close Date"), F("CreatedDate", "datetime", "Created Date"),
        F("LastModifiedDate", "datetime", "Last Modified Date"), F("IsClosed", "boolean", "Closed"), F("IsWon", "boolean", "Won"),
        F("StageName", "picklist", "Stage", picklistValues=pick("Prospecting", "Negotiation/Review", "Closed Won", "Closed Lost")),
        F("LeadSource", "picklist", "Lead Source", picklistValues=pick("Web", "Partner Referral", "Other")),
        F("OwnerId", "reference", "Owner ID", relationshipName="Owner", referenceTo=["User"]),
        F("AccountId", "reference", "Account ID", relationshipName="Account", referenceTo=["Account"]),
    ]},
    "Account": {"fields": [
        F("Id", "id"), F("Name", "string", "Account Name", nameField=True), F("Phone", "phone", "Account Phone"),
        F("Industry", "picklist", picklistValues=pick("Technology", "Banking", "Other")),
        F("BillingState", "string", "Billing State/Province"), F("BillingCountry", "string", "Billing Country"),
        F("AnnualRevenue", "currency", "Annual Revenue"), F("NumberOfEmployees", "int", "Employees"),
        F("CreatedDate", "datetime", "Created Date"), F("LastModifiedDate", "datetime", "Last Modified Date"),
        F("OwnerId", "reference", "Owner ID", relationshipName="Owner", referenceTo=["User"]),
    ]},
    "Contact": {"fields": [
        F("Id", "id"), F("Name", "string", "Full Name", nameField=True), F("Email", "email"),
        F("AccountId", "reference", "Account ID", relationshipName="Account", referenceTo=["Account"]),
        F("MailingCountry", "string", "Mailing Country"), F("CreatedDate", "datetime", "Created Date"),
    ]},
    "Lead": {"fields": [
        F("Id", "id"), F("Name", "string", "Full Name", nameField=True), F("Email", "email"), F("IsConverted", "boolean", "Converted"),
        F("LeadSource", "picklist", "Lead Source", picklistValues=pick("Web", "Phone Inquiry")), F("CreatedDate", "datetime", "Created Date"),
        F("State", "string", "State/Province"), F("Country", "string"),
        F("StateCode", "picklist", "State/Province Code", picklistValues=pick("CA", "IN", "NY")),
    ]},
    "Case": {"fields": [
        F("Id", "id"), F("Subject", "string", nameField=True), F("IsClosed", "boolean", "Closed"),
        F("Priority", "picklist", picklistValues=pick("High", "Medium", "Low")), F("CreatedDate", "datetime", "Created Date"),
    ]},
}
OBJECTS = {n: {"label": n, "labelPlural": n + "s"} for n in DESCRIBE}
OBJECTS["Opportunity"]["labelPlural"] = "Opportunities"
CHILDREN = {"Account": [
    {"name": "Contacts", "object": "Contact", "field": "AccountId", "label": "Contacts", "primary": True},
    {"name": "Opportunities", "object": "Opportunity", "field": "AccountId", "label": "Opportunities", "primary": True},
]}


def ask(q, context=None):
    a = finder.interpret(q, OBJECTS, lambda n: DESCRIBE[n], lambda n: CHILDREN.get(n, []), context=context)
    children = {c["name"]: c for c in CHILDREN.get(a["object"], [])}
    a["where"] = finder.conditions(finder.explorer._fields(DESCRIBE[a["object"]]), a["filters"], children)
    return a


def test_open_deals_over_50k_closing_this_month():
    a = ask("open deals over 50k closing this month")
    assert a["object"] == "Opportunity" and a["ignored"] == []
    assert a["where"] == ["IsClosed = FALSE", "Amount > 50000", "CloseDate = THIS_MONTH"]
    assert [f["label"] for f in a["filters"]] == ["Closed: no", "Amount > 50,000", "Close Date: this month"]


def test_how_many_won_deals_last_quarter_from_web():
    a = ask("How many won opportunities from Web last quarter?")
    assert a["count_only"] and "IsWon = TRUE" in a["where"] and "CloseDate = LAST_QUARTER" in a["where"]
    assert "LeadSource = 'Web'" in a["where"] and a["ignored"] == []


def test_accounts_without_contacts_in_california():
    a = ask("accounts without contacts in California")
    assert a["where"] == [
        "Id NOT IN (SELECT AccountId FROM Contact WHERE AccountId != null)",
        "BillingState IN ('California', 'CA')",
    ]
    assert a["filters"][0]["label"] == "No contacts"


def test_contacts_missing_email_created_last_30_days():
    a = ask("contacts with no email created in the last 30 days")
    assert a["object"] == "Contact"
    assert sorted(a["where"]) == ["CreatedDate = LAST_N_DAYS:30", "Email = null"]


def test_owner_numbers_and_industry():
    a = ask("technology accounts owned by Ryan Clark with more than 100 employees")
    assert "Owner.Name LIKE '%Ryan Clark%'" in a["where"]
    assert "NumberOfEmployees > 100" in a["where"] and "Industry = 'Technology'" in a["where"]
    assert a["ignored"] == []


def test_stale_and_sorting_and_year():
    a = ask("biggest opportunities not updated in 3 months")
    assert a["sort"] == "Amount" and a["dir"] == "desc" and a["where"] == ["LastModifiedDate < LAST_N_DAYS:90"]
    a = ask("leads created in 2025 in India")
    assert a["where"] == ["CreatedDate >= 2025-01-01T00:00:00Z", "CreatedDate <= 2025-12-31T00:00:00Z", "Country IN ('India', 'IN')"]


def test_context_object_and_unknown_words_reported():
    a = ask("without email", context="Lead")
    assert a["object"] == "Lead" and a["where"] == ["Email = null"]
    assert ask("accounts with purple unicorns")["ignored"] == ["purple", "unicorns"]
    with pytest.raises(ValueError):
        ask("purple unicorns")


def test_quoted_name_is_escaped():
    a = ask('accounts named "O\'Brien%"')
    bs = chr(92)
    assert a["where"] == [f"Name LIKE '%O{bs}'Brien{bs}%%'"]


@pytest.mark.parametrize("bad", [
    {"field": "Name) FROM User--", "op": "eq", "value": "x"},
    {"field": "Amount", "op": "gt", "value": "1 OR Id != null"},
    {"field": "CloseDate", "op": "eq", "value": "TODAY OR IsDeleted = TRUE"},
    {"field": "IsClosed", "op": "eq", "value": "TRUE"},
    {"field": "OwnerId", "op": "eq", "value": "005' OR Name != '"},
    {"field": "StageName", "op": "like", "value": "x"},
    {"field": "Contacts", "op": "nochild"},
])
def test_unsafe_filters_rejected(bad):
    with pytest.raises(ValueError):
        finder.condition(finder.explorer._fields(DESCRIBE["Opportunity"]), bad, {})


def test_text_values_escaped():
    fields = finder.explorer._fields(DESCRIBE["Opportunity"])
    bs = chr(92)
    got = finder.condition(fields, {"field": "StageName", "op": "eq", "value": "x' OR Name != '"})
    assert got == f"StageName = 'x{bs}' OR Name != {bs}''"


def test_search_endpoint_groups_by_object(client, sf):
    connect(client)
    groups = client.get(f"{API}/search", params={"q": "ada*", "objects": "Contact,Account,Hidden,Evil"}).json()
    assert [g["object"] for g in groups] == ["Contact", "Account"]
    assert groups[0]["records"][0] == {"id": "003000000000001AAA", "name": "Ada Lovelace", "detail": "ada@acme.test"}
    assert sf.search["q"] == ["ada"] and sf.search["sobject"] == ["Contact", "Account"]


def test_records_with_filters_and_ask(client, sf):
    connect(client)
    f = json.dumps([{"field": "Industry", "op": "eq", "value": "Tech"}, {"field": "Contacts", "op": "nochild"}])
    assert client.get(f"{API}/objects/Account/records", params={"filters": f}).status_code == 200
    q = sf.soql[-1]
    assert "WHERE Industry = 'Tech' AND Id NOT IN (SELECT AccountId FROM Contact WHERE AccountId != null)" in q
    bad = json.dumps([{"field": "Name) FROM User--", "op": "eq", "value": "x"}])
    assert client.get(f"{API}/objects/Account/records", params={"filters": bad}).status_code == 422
    assert client.get(f"{API}/objects/Account/records", params={"filters": "not json"}).status_code == 422

    a = client.post(f"{API}/ask", json={"question": "how many Tech accounts without contacts"}).json()
    assert a["object"] == "Account" and a["countOnly"] and a["total"] == 42
    assert sorted(x["label"] for x in a["filters"]) == ["Industry is Tech", "No contacts"]
    assert client.post(f"{API}/ask", json={"question": "zzz"}).status_code == 422


def test_state_codes_are_not_words_and_prefixes_match():
    a = ask("web leads in California")
    assert a["ignored"] == []
    assert a["where"] == ["LeadSource = 'Web'", "State IN ('California', 'CA')"]
    a = ask("phone leads in India")
    assert a["where"] == ["LeadSource = 'Phone Inquiry'", "Country IN ('India', 'IN')"]


def test_field_word_after_value_is_used():
    a = ask("open cases high priority")
    assert a["where"] == ["IsClosed = FALSE", "Priority = 'High'"] and a["ignored"] == []


def test_standard_object_wins_over_custom_with_same_label():
    objs = {**OBJECTS, "Account__c": {"label": "Account", "labelPlural": "Accounts", "custom": True}}
    for _ in range(5):
        a = finder.interpret("accounts", objs, lambda n: DESCRIBE.get(n, {"fields": []}), lambda n: [])
        assert a["object"] == "Account"


def test_column_filter_one_of_any_kind_of_field():
    fields = {f["name"]: f for f in DESCRIBE["Opportunity"]["fields"]}
    c = lambda field, op, value: finder.condition(fields, {"field": field, "op": op, "value": value})  # noqa: E731
    assert c("StageName", "in", ["Prospecting", None]) == "(StageName IN ('Prospecting') OR StageName = null)"  # None = Blanks
    assert c("StageName", "notin", ["Closed Lost"]) == "StageName NOT IN ('Closed Lost')"
    assert c("Amount", "in", [5000, 12.5]) == "Amount IN (5000, 12.5)"
    assert c("CloseDate", "in", ["2026-01-31"]) == "CloseDate IN (2026-01-31)"
    assert c("OwnerId", "in", ["005000000000001"]) == "OwnerId IN ('005000000000001')"
    assert c("IsClosed", "in", [True, None]) == "(IsClosed = TRUE OR IsClosed = null)"
    for bad in [("CloseDate", ["2026-01-31) OR (Id != null"]), ("OwnerId", ["x' OR Name != '"]), ("Amount", ["1 OR 1=1"])]:
        with pytest.raises(ValueError):
            c(bad[0], "in", bad[1])
    with pytest.raises(ValueError):
        c("StageName", "in", [f"v{i}" for i in range(101)])
