"""Duplicate finder: Salesforce's standard matching rules, and matching on chosen fields."""
import pytest

from app.salesforce import duplicates


def F(name, type_="string", label=None, **kw):
    return {"name": name, "label": label or name, "type": type_, "filterable": True, **kw}


DESCRIBE = {
    "Account": {"fields": [F("Id", "id"), F("Name", label="Account Name", nameField=True), F("Website", "url"), F("Phone", "phone", "Account Phone"),
                           F("BillingStreet", "textarea"), F("BillingCity", label="Billing City"), F("BillingState", label="Billing State"),
                           F("BillingPostalCode", label="Billing Zip"), F("Industry", "picklist")]},
    "Contact": {"fields": [F("Id", "id"), F("Name", label="Full Name", nameField=True), F("FirstName", label="First Name"), F("LastName", label="Last Name"),
                           F("Email", "email"), F("Phone", "phone"), F("Title"), F("AccountId", "reference"), F("MailingStreet", "textarea"),
                           F("MailingCity"), F("MailingPostalCode")]},
}

ACCOUNTS = [
    {"Id": "001A", "Name": "Acme, Inc.", "Website": "https://www.acme.com", "Phone": "1-415-555-1234", "BillingCity": "San Francisco", "BillingPostalCode": "94105"},
    {"Id": "001B", "Name": "ACME", "Website": None, "Phone": "(415) 555-1234", "BillingCity": "Oakland", "BillingPostalCode": None},
    {"Id": "001C", "Name": "Globex Corporation", "Website": "globex.com", "Phone": "212-555-0000", "BillingCity": "New York", "BillingPostalCode": "10001"},
    {"Id": "001D", "Name": "Globex", "Website": None, "Phone": None, "BillingCity": "Boston", "BillingPostalCode": "02101"},  # name only: not enough
    {"Id": "001E", "Name": "Initech", "Website": "initech.com", "Phone": "312-555-9999", "BillingCity": "Chicago", "BillingPostalCode": "60601"},
    {"Id": "001F", "Name": "Initech LLC", "Website": None, "Phone": None, "BillingCity": "Chicago", "BillingPostalCode": "60601-1234"},
]
CONTACTS = [
    {"Id": "003A", "Name": "Robert Smith", "FirstName": "Robert", "LastName": "Smith", "Email": "bob@acme.com", "Phone": None, "Account": {"Name": "Acme"}},
    {"Id": "003B", "Name": "Bob Smyth", "FirstName": "Bob", "LastName": "Smyth", "Email": "BOB@acme.com", "Phone": None, "Account": None},
    {"Id": "003C", "Name": "Smith Robert", "FirstName": "Smith", "LastName": "Robert", "Email": None, "Phone": "415-555-1234", "Account": None},  # swapped
    {"Id": "003D", "Name": "Robert Smith", "FirstName": "Robert", "LastName": "Smith", "Email": None, "Phone": "1-415-555-1234", "Account": None},
    {"Id": "003E", "Name": "Jane Jones", "FirstName": "Jane", "LastName": "Jones", "Email": "jane@x.com", "Phone": None, "Account": None},
]


class StubSF:
    base = "https://acme.my.salesforce.com"

    def __init__(self, rows):
        self.rows, self.soql = rows, []

    def query(self, soql):
        self.soql.append(soql)
        return {"records": self.rows, "done": True}

    def get(self, path):  # pragma: no cover - no paging in these tests
        raise AssertionError(path)


@pytest.fixture(autouse=True)
def _describe(monkeypatch):
    monkeypatch.setattr(duplicates.explorer, "_describe", lambda sf, name: DESCRIBE[name])


def groups_of(result):
    return sorted(sorted(r["id"] for r in g["records"]) for g in result["groups"])


def test_standard_account_rule():
    r = duplicates.find_duplicates(StubSF(ACCOUNTS), "Account", standard=True)
    # Acme: name + phone. Initech: name + ZIP (first five digits). Globex: name alone isn't enough.
    assert groups_of(r) == [["001A", "001B"], ["001E", "001F"]]
    assert r["rule_name"] == "Standard Account Matching Rule" and r["extra_copies"] == 2
    assert ["Account Name", "Account Phone"] in r["rules"]


def test_standard_contact_rule_handles_nicknames_typos_case_and_swapped_names():
    r = duplicates.find_duplicates(StubSF(CONTACTS), "Contact", standard=True)
    # Robert Smith / Bob Smyth share an email; Smith Robert (swapped) / Robert Smith share a phone.
    assert groups_of(r) == [["003A", "003B"], ["003C", "003D"]]
    assert "Account.Name" in r["columns"][0]["name"] or any(c["name"] == "Account.Name" for c in r["columns"])


def test_chosen_fields_must_all_match():
    sf = StubSF(ACCOUNTS)
    by_city = duplicates.find_duplicates(sf, "Account", ["BillingCity"])
    assert groups_of(by_city) == [["001E", "001F"]] and by_city["rules"] == [["Billing City"]]
    by_name = duplicates.find_duplicates(sf, "Account", ["Name"])
    assert groups_of(by_name) == [["001A", "001B"], ["001C", "001D"], ["001E", "001F"]]
    assert groups_of(duplicates.find_duplicates(sf, "Account", ["Name", "BillingCity"])) == [["001E", "001F"]]


def test_input_is_checked():
    sf = StubSF(ACCOUNTS)
    with pytest.raises(ValueError):
        duplicates.find_duplicates(sf, "Account", [])
    with pytest.raises(ValueError):
        duplicates.find_duplicates(sf, "Account", ["Name) FROM User --"])  # not a real field: ignored, so nothing chosen
    assert all("--" not in q for q in sf.soql)


@pytest.mark.parametrize("a,b,expected", [
    ("1-415-555-1234", "1-415-555-5678", True),  # Salesforce's own example: 90, above 80
    ("123 Market Street, Suite 100", "123 Market Drive, Suite 300", False),  # Salesforce's example: 70, below 80
    ("94104-1001", "94104", True),
])
def test_salesforce_examples(a, b, expected):
    m = duplicates.m_phone if "-" in a and a[0].isdigit() and len(a) > 10 and "Market" not in a else duplicates.m_street if "Market" in a else duplicates.m_zip
    assert m(a, b) is expected
