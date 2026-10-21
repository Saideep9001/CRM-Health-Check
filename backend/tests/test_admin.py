"""Admin Panel: forced password change, access requests (approve/reject), activity log, admin-only access."""
from fastapi.testclient import TestClient

from app import manage
from app.db import SessionLocal
from app.main import app
from app.models import UserRow

from .conftest import connect
from .test_auth import _login, _user
from .test_consultant import _add_org

API = "/api/v1"
ORG_A = "00Dxx0000001"


def test_temporary_password_must_be_changed_first(client):
    v = _user(client, "viewer", keep_temporary=True)
    viewer = _login(v["email"], v["password"])
    assert viewer.get(f"{API}/me").json()["mustChangePassword"] is True
    assert viewer.get(f"{API}/portfolio").status_code == 403  # nothing else until they choose a password
    same = {"currentPassword": v["password"], "newPassword": v["password"]}
    assert viewer.post(f"{API}/me/password", json=same).status_code == 422
    assert viewer.post(f"{API}/me/password", json={"currentPassword": v["password"], "newPassword": "my very own password"}).status_code == 204
    assert viewer.get(f"{API}/me").json()["mustChangePassword"] is False
    assert viewer.get(f"{API}/portfolio").status_code == 200

    # An admin's reset gives a temporary password again.
    client.post(f"{API}/users/{v['id']}/password", json={"password": "another temp password"})
    again = _login(v["email"], "another temp password")
    assert again.get(f"{API}/me").json()["mustChangePassword"] is True


def test_admin_panel_is_admins_only(client):
    c = _user(client, "consultant")
    consultant = _login(c["email"], c["password"])
    for path in ("/admin/overview", "/admin/requests", "/admin/activity"):
        assert consultant.get(f"{API}{path}").status_code == 403
        assert client.get(f"{API}{path}").status_code == 200
    o = client.get(f"{API}/admin/overview").json()
    assert o["admins"] == 1 and o["consultants"] == 1 and o["pendingRequests"] == 0


def test_org_access_request_approved(client, sf):
    connect(client)
    _add_org("00Dyy0000002", "Beta Corp")
    v = _user(client, "viewer", org_ids=[ORG_A])
    viewer = _login(v["email"], v["password"])
    assert viewer.post(f"{API}/access-requests", json={"kind": "org"}).status_code == 422  # must say which client
    r = viewer.post(f"{API}/access-requests", json={"kind": "org", "orgNote": "Beta Corp please", "message": "New project"})
    assert r.status_code == 201
    rid = r.json()["id"]
    assert viewer.post(f"{API}/access-requests", json={"kind": "org", "orgNote": "again"}).status_code == 409  # one at a time
    assert client.get(f"{API}/admin/overview").json()["pendingRequests"] == 1

    pending = client.get(f"{API}/admin/requests", params={"status": "pending"}).json()
    assert pending[0]["userEmail"] == v["email"] and pending[0]["orgNote"] == "Beta Corp please"
    assert client.post(f"{API}/admin/requests/{rid}/approve", json={}).status_code == 422  # choose orgs
    assert client.post(f"{API}/admin/requests/{rid}/approve", json={"orgIds": ["00Dzz_unknown"]}).status_code == 422
    ok = client.post(f"{API}/admin/requests/{rid}/approve", json={"orgIds": ["00Dyy0000002"]})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    assert sorted(o["orgId"] for o in viewer.get(f"{API}/portfolio").json()) == sorted([ORG_A, "00Dyy0000002"])  # applies at once
    assert client.post(f"{API}/admin/requests/{rid}/reject", json={}).status_code == 409  # already decided
    assert viewer.get(f"{API}/access-requests/mine").json()[0]["status"] == "approved"


def test_role_request_rejected_and_admin_cannot_be_requested(client):
    v = _user(client, "viewer")
    viewer = _login(v["email"], v["password"])
    assert viewer.post(f"{API}/access-requests", json={"kind": "role", "requestedRole": "admin"}).status_code == 422
    assert viewer.post(f"{API}/access-requests", json={"kind": "role", "requestedRole": "viewer"}).status_code == 422
    r = viewer.post(f"{API}/access-requests", json={"kind": "role", "requestedRole": "consultant"}).json()
    assert viewer.post(f"{API}/admin/requests/{r['id']}/approve", json={}).status_code == 403  # can't approve their own
    rej = client.post(f"{API}/admin/requests/{r['id']}/reject", json={"note": "Not this quarter"}).json()
    assert rej["status"] == "rejected" and rej["decisionNote"] == "Not this quarter"
    assert viewer.get(f"{API}/me").json()["role"] == "viewer"
    assert client.post(f"{API}/access-requests", json={"kind": "role", "requestedRole": "viewer"}).status_code == 409  # admins needn't ask


def test_activity_log_records_access_changes(client):
    v = _user(client, "viewer")
    client.patch(f"{API}/users/{v['id']}", json={"role": "consultant"})
    client.post(f"{API}/users/{v['id']}/sign-out")
    events = client.get(f"{API}/admin/activity").json()
    assert {"user.added", "user.updated", "user.signed_out"} <= {e["action"] for e in events}
    upd = next(e for e in events if e["action"] == "user.updated")
    assert "viewer → consultant" in upd["detail"] and v["email"] in upd["target"]


def test_unlock(client):
    v = _user(client, "viewer")
    c = TestClient(app)
    for _ in range(5):
        c.post(f"{API}/auth/login", json={"email": v["email"], "password": "wrong password!!"})
    assert any(m["locked"] for m in client.get(f"{API}/users").json())
    assert client.post(f"{API}/users/{v['id']}/unlock").status_code == 204
    _login(v["email"], v["password"])


def test_add_admin_command(client, monkeypatch):
    monkeypatch.setenv("AQ_DEFAULT_PASSWORD", "a shared default pass")
    v = _user(client, "viewer", email="existing@aquarient.test")
    assert manage.main(["add-admin", "new.person@aquarient.test", "existing@aquarient.test"]) == 0
    with SessionLocal() as db:
        new = db.query(UserRow).filter(UserRow.email == "new.person@aquarient.test").one()
        old = db.query(UserRow).filter(UserRow.email == "existing@aquarient.test").one()
        assert (new.role, new.all_orgs, new.must_change_password, new.name) == ("admin", True, True, "New Person")
        assert new.password_hash.startswith("scrypt$") and "a shared default pass" not in new.password_hash
        assert (old.role, old.must_change_password) == ("admin", False)  # password left alone
    signed_in = _login("new.person@aquarient.test", "a shared default pass")
    assert signed_in.get(f"{API}/me").json()["mustChangePassword"] is True
    _login(v["email"], v["password"])
    assert manage.main(["add-admin", "not-an-email"]) == 2
