"""Companies (workspaces): people, orgs and results stay inside their company; "Remove from my list" is per person."""
from fastapi.testclient import TestClient

from app.main import app

from .conftest import ADMIN, connect

API = "/api/v1"
ORG = "00Dxx0000001"  # the fake Salesforce org every test connection signs in to


def _sign_in(email: str, password: str, new_password: str | None = None) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    if new_password:  # temporary password: choose your own first
        r = c.post(f"{API}/me/password", json={"currentPassword": password, "newPassword": new_password})
        assert r.status_code == 204, r.text
    return c


def _company(client, name: str, email: str) -> tuple[dict, TestClient]:
    r = client.post(f"{API}/admin/companies", json={"name": name, "adminName": f"{name} Admin", "adminEmail": email,
                                                     "adminPassword": "temporary pass 123"})
    assert r.status_code == 201, r.text
    return r.json(), _sign_in(email, "temporary pass 123", "their own pass 456")


def _orgs(c: TestClient) -> list[dict]:
    r = c.get(f"{API}/portfolio")
    assert r.status_code == 200, r.text
    return r.json()


def test_companies_cannot_see_each_other(client):
    me = client.get(f"{API}/me").json()
    assert me["platformAdmin"] and me["companyName"] == "Aquarient"
    connect(client)  # Aquarient's org
    beta, b = _company(client, "Beta Corp", "admin@beta.test")
    assert beta["admins"] == 1 and beta["orgs"] == 0

    # Beta sees none of Aquarient's people, orgs, checks or activity
    assert _orgs(b) == []
    assert b.get(f"{API}/salesforce/connection").json()["status"] == "disconnected"
    assert [u["email"] for u in b.get(f"{API}/users").json()] == ["admin@beta.test"]
    assert b.post(f"{API}/salesforce/connections/{ORG}/activate").status_code == 404
    assert b.get(f"{API}/assessments").json()["items"] == []
    assert all("beta" in (e["actor"] + (e["target"] or "")).lower() or e["action"] == "company.created" for e in b.get(f"{API}/admin/activity").json())
    assert b.get(f"{API}/admin/companies").status_code == 403  # company admins don't run the platform
    aq_admin = next(u for u in client.get(f"{API}/users").json() if u["email"] == ADMIN["email"])
    assert b.patch(f"{API}/users/{aq_admin['id']}", json={"role": "viewer"}).status_code == 404

    # Beta connects the same Salesforce org: its own connection, Aquarient's stays
    beta_conn = connect(b)
    assert beta_conn["orgId"] == f"{ORG}~{beta['id']}"
    assert [o["orgId"] for o in _orgs(b)] == [beta_conn["orgId"]]
    assert {o["orgId"] for o in _orgs(client)} == {ORG, beta_conn["orgId"]}  # the platform admin sees both companies

    # a consultant in Aquarient sees only Aquarient's org, even with "all orgs"
    r = client.post(f"{API}/users", json={"name": "Cleo", "email": "cleo@aq.test", "role": "consultant", "allOrgs": True,
                                          "password": "temporary pass 123"})
    assert r.status_code == 201 and r.json()["companyName"] == "Aquarient"
    cleo = _sign_in("cleo@aq.test", "temporary pass 123", "cleo own pass 789")
    assert [o["orgId"] for o in _orgs(cleo)] == [ORG]
    assert cleo.post(f"{API}/salesforce/connections/{beta_conn['orgId']}/activate").status_code == 404

    # Beta disconnecting its org leaves Aquarient's connected
    assert b.delete(f"{API}/salesforce/connections/{beta_conn['orgId']}").status_code == 204
    assert cleo.get(f"{API}/salesforce/connection").json()["status"] == "connected"


def test_remove_from_my_list_is_only_for_me(client):
    connect(client)
    r = client.post(f"{API}/users", json={"name": "Mohin", "email": "mohin@aq.test", "role": "admin", "password": "temporary pass 123"})
    assert r.status_code == 201
    mohin = _sign_in("mohin@aq.test", "temporary pass 123", "mohin own pass 789")
    assert client.get(f"{API}/salesforce/connections/{ORG}/people").json() == ["Mohin", ADMIN["name"]]

    assert client.post(f"{API}/salesforce/connections/{ORG}/hide").status_code == 204
    assert client.get(f"{API}/salesforce/connection").json()["status"] == "disconnected"  # gone from my list
    assert [(o["orgId"], o["hidden"]) for o in _orgs(client)] == [(ORG, True)]
    assert mohin.get(f"{API}/salesforce/connection").json()["status"] == "connected"  # Mohin still has it
    assert [o["hidden"] for o in _orgs(mohin)] == [False]

    assert client.post(f"{API}/salesforce/connections/{ORG}/activate").status_code == 200  # add it back
    assert client.get(f"{API}/salesforce/connection").json()["status"] == "connected"
    assert [o["hidden"] for o in _orgs(client)] == [False]
