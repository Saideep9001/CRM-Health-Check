"""Empty fields: find records whose chosen fields are blank (read-only, describe-checked)."""
from app.salesforce import explorer

from .conftest import connect

API = "/api/v1/data"


def setup_function():
    explorer.clear_cache()


def test_empty_fields_any_and_all(client, sf):
    connect(client)
    opts = client.get(f"{API}/empty/options", params={"object": "Account"}).json()
    assert {"Industry", "Name"} <= {f["name"] for f in opts}

    r = client.post(f"{API}/empty", json={"object": "Account", "fields": ["Industry", "Name"], "match": "any"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["objectTotal"] == 42 and body["fieldLabels"] == ["Industry", "Account Name"]
    assert any("WHERE (Industry = null OR Name = null)" in q for q in sf.soql)

    client.post(f"{API}/empty", json={"object": "Account", "fields": ["Industry", "Name"], "match": "all"})
    assert any("WHERE (Industry = null AND Name = null)" in q for q in sf.soql)


def test_only_real_fields_reach_the_query(client, sf):
    connect(client)
    bad = client.post(f"{API}/empty", json={"object": "Account", "fields": ["Name) FROM User --"], "match": "any"})
    assert bad.status_code == 422
    assert all("--" not in q for q in sf.soql)
    csv = client.get(f"{API}/empty.csv", params={"object": "Lead", "fields": "Industry"})  # the fake pages Accounts forever
    assert csv.status_code == 200 and csv.text.splitlines()[0].endswith("Salesforce link")
