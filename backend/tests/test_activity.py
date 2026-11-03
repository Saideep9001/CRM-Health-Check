"""No activity with a chosen period and meaning of "activity" (tasks/events or any edit)."""
from app.salesforce import explorer

from .conftest import connect

API = "/api/v1/data"


def setup_function():
    explorer.clear_cache()


def test_period_and_basis_build_the_filter(client, sf):
    connect(client)
    r = client.get(f"{API}/inactive", params={"object": "Account", "days": 365, "basis": "activity"})
    assert r.status_code == 200, r.text
    body = r.json()
    # this fake Account has no LastActivityDate, so "activity" falls back to the last edit
    assert body["field"] == "LastModifiedDate" and body["days"] == 365 and len(body["buckets"]) == 6
    assert any("WHERE (LastModifiedDate = null OR LastModifiedDate < LAST_N_DAYS:365)" in q for q in sf.soql)
    assert any("LastModifiedDate < LAST_N_DAYS:180 AND LastModifiedDate >= LAST_N_DAYS:365" in q for q in sf.soql)  # 6-12 months

    assert client.get(f"{API}/inactive/records", params={"object": "Account", "days": 90, "basis": "edit"}).status_code == 200
    q = sf.soql[-1]
    assert "FROM Account WHERE (LastModifiedDate = null OR LastModifiedDate < LAST_N_DAYS:90)" in q and "ORDER BY LastModifiedDate ASC" in q

    assert client.get(f"{API}/inactive/values", params={"object": "Account", "field": "Industry", "days": 90, "basis": "edit"}).status_code == 200
    assert sf.soql[-1].startswith("SELECT Industry v, COUNT(Id) c FROM Account WHERE ((LastModifiedDate = null")


def test_only_whitelisted_periods_and_bases(client, sf):
    connect(client)
    assert client.get(f"{API}/inactive", params={"object": "Account", "days": 100}).status_code == 422
    assert client.get(f"{API}/inactive", params={"object": "Account", "days": 180, "basis": "Id != null"}).status_code == 422

