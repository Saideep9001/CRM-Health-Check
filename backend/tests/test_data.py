"""Data explorer: object list, describe, records, and input validation."""
from urllib.parse import parse_qs, urlparse

from .conftest import connect

API = "/api/v1/data"


def test_requires_connection(client):
    assert client.get(f"{API}/objects").status_code == 409


def test_lists_queryable_objects_common_first(client):
    connect(client)
    objs = client.get(f"{API}/objects").json()
    names = [o["name"] for o in objs]
    assert names[:4] == ["Account", "Contact", "Lead", "Opportunity"] and "Hidden" not in names
    by = {o["name"]: o for o in objs}
    assert by["Account"]["approxCount"] == 120 and by["Invoice__c"]["custom"] and by["AccountHistory"]["system"]


def test_describe_object(client):
    connect(client)
    d = client.get(f"{API}/objects/Account").json()
    assert d["nameField"] == "Name" and d["searchable"]
    assert d["defaultColumns"][:3] == ["Id", "Name", "Industry"] and "BillingAddress" not in d["defaultColumns"]
    assert next(f for f in d["fields"] if f["name"] == "Name")["required"] is True


def test_unknown_object_is_404(client):
    connect(client)
    assert client.get(f"{API}/objects/Account;DROP").status_code == 404
    assert client.get(f"{API}/objects/Hidden").status_code == 404


def test_records_page_with_owner_name_and_cursor(client, sf):
    connect(client)
    page = client.get(f"{API}/objects/Account/records").json()
    assert page["totalSize"] == 450 and page["nextCursor"].startswith("/services/data/")
    row = page["records"][0]
    assert row["values"]["Name"] == "Acme" and row["refNames"]["OwnerId"] == "Jane Doe"
    q = sf.soql[-1]
    assert "Owner.Name" in q and "ORDER BY LastModifiedDate DESC" in q
    assert sf.batch == "batchSize=200"


def test_search_is_escaped_and_bad_fields_dropped(client, sf):
    connect(client)
    client.get(f"{API}/objects/Account/records", params={"q": "O'Brien%", "fields": "Name,Evil__x) FROM User--,Industry", "sort": "Bogus"})
    q = sf.soql[-1]
    bs = chr(92)
    assert f"LIKE '%O{bs}'Brien{bs}%%'" in q
    assert "Evil" not in q and q.startswith("SELECT Id, Name, Industry")


def test_rejects_foreign_cursor(client):
    connect(client)
    r = client.get(f"{API}/objects/Account/records", params={"cursor": "https://evil.example/steal"})
    assert r.status_code == 422


def test_record_detail(client):
    connect(client)
    r = client.get(f"{API}/objects/Account/records/001000000000001AAA").json()
    assert r["values"]["Name"] == "Acme" and "attributes" not in r["values"]
    assert r["salesforceUrl"].endswith("/001000000000001AAA")
    assert client.get(f"{API}/objects/Account/records/bad'id").status_code == 404


def test_related_lists_are_described(client):
    connect(client)
    rels = client.get(f"{API}/objects/Account").json()["childRelationships"]
    # Common lists first; system objects, hidden objects, and unnamed links are left out.
    assert [(r["name"], r["object"], r["field"], r["label"], r["primary"]) for r in rels] == [
        ("Contacts", "Contact", "AccountId", "Contacts", True),  # standard link first, plain label
        ("ApproverContacts__r", "Contact", "Approver_Account__c", "Contacts (Approver Account)", False),
        ("Opportunities", "Opportunity", "AccountId", "Opportunitys", True),
    ]


def test_related_records(client, sf):
    connect(client)
    page = client.get(f"{API}/objects/Account/records/001000000000001AAA/related/Contacts").json()
    assert page["object"] == "Contact" and page["label"] == "Contacts" and page["nameField"] == "Name"
    assert [c["name"] for c in page["columns"]] == ["Id", "Name", "Email", "LastModifiedDate"]  # the link field itself is left out
    assert page["records"][0]["values"]["Name"] == "Ada Lovelace" and page["totalSize"] == 42
    assert page["salesforceUrl"].endswith("/lightning/r/Account/001000000000001AAA/related/Contacts/view")
    q = next(x for x in sf.soql if "FROM Contact WHERE" in x and "COUNT" not in x)
    assert "WHERE AccountId = '001000000000001AAA'" in q and q.endswith("LIMIT 50")


def test_related_rejects_unknown_relationships_and_bad_ids(client):
    connect(client)
    assert client.get(f"{API}/objects/Account/records/001000000000001AAA/related/Histories").status_code == 404
    assert client.get(f"{API}/objects/Account/records/001000000000001AAA/related/Bogus").status_code == 404
    assert client.get(f"{API}/objects/Account/records/bad'id/related/Contacts").status_code == 404
