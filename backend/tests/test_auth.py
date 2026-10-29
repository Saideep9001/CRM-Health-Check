"""Sign-in, sessions, roles and per-org access."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import SessionRow, UserRow

from .conftest import ADMIN, connect
from .test_consultant import _add_org, _completed

API = "/api/v1"
ORG_A = "00Dxx0000001"


def _user(client, role: str, org_ids=(), all_orgs=False, email=None, keep_temporary=False) -> dict:
    body = {"name": f"{role.title()} Person", "email": email or f"{role}@aquarient.test", "role": role,
            "orgIds": list(org_ids), "allOrgs": all_orgs, "password": "a long safe password"}
    r = client.post(f"{API}/users", json=body)
    assert r.status_code == 201, r.text
    if not keep_temporary:  # as if they'd already chosen their own password
        with SessionLocal() as db:
            db.get(UserRow, r.json()["id"]).must_change_password = False
            db.commit()
    return {**r.json(), "password": body["password"]}


def _login(email: str, password: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c


def test_first_run_setup_only_once(client):
    assert client.get(f"{API}/auth/setup-status").json() == {"needsSetup": False, "authRequired": True}
    assert client.post(f"{API}/auth/setup", json={**ADMIN, "email": "other@aquarient.test"}).status_code == 409


def test_signed_out_requests_are_rejected(client):
    anon = TestClient(app)
    assert anon.get(f"{API}/health").status_code == 200  # public
    assert anon.get(f"{API}/auth/setup-status").status_code == 200  # public
    for path in ("/me", "/me/settings", "/salesforce/connection", "/assessments", "/portfolio", "/data/objects", "/users"):
        assert anon.get(f"{API}{path}").status_code == 401, path


def test_login_logout_and_cookie(client):
    c = TestClient(app)
    assert c.post(f"{API}/auth/login", json={"email": ADMIN["email"], "password": "wrong password!"}).status_code == 401
    assert c.post(f"{API}/auth/login", json={"email": "nobody@x.test", "password": "whatever123"}).status_code == 401
    r = c.post(f"{API}/auth/login", json={"email": ADMIN["email"].upper(), "password": ADMIN["password"], "rememberMe": True})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "max-age" in cookie
    assert c.get(f"{API}/me").json()["email"] == ADMIN["email"]
    with SessionLocal() as db:  # only a hash of the token is stored
        token = c.cookies.get("aq_session")
        assert token and db.get(SessionRow, token) is None
    assert c.post(f"{API}/auth/logout").status_code == 204
    assert c.get(f"{API}/me").status_code == 401


def test_lockout_after_repeated_failures(client):
    c = TestClient(app)
    for _ in range(5):
        assert c.post(f"{API}/auth/login", json={"email": ADMIN["email"], "password": "not the password"}).status_code == 401
    r = c.post(f"{API}/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    assert r.status_code == 429  # locked even with the right password


def test_cross_site_writes_blocked(client):
    r = client.post(f"{API}/me/notifications/read", json={}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.post(f"{API}/me/notifications/read", json={}, headers={"Origin": "http://localhost:5173"}).status_code == 204


def test_password_rules_and_change(client):
    assert client.post(f"{API}/users", json={"name": "X", "email": "x@aquarient.test", "role": "viewer", "password": "short"}).status_code == 422
    assert client.post(f"{API}/users", json={"name": "X", "email": "x@aquarient.test", "role": "viewer", "password": "1111111111111"}).status_code == 422
    assert client.post(f"{API}/me/password", json={"currentPassword": "nope", "newPassword": "another long password"}).status_code == 422
    assert client.post(f"{API}/me/password", json={"currentPassword": ADMIN["password"], "newPassword": "another long password"}).status_code == 204
    assert client.get(f"{API}/me").status_code == 200  # this session stays signed in
    _login(ADMIN["email"], "another long password")


def test_viewer_is_read_only_and_sees_only_their_org(client, sf):
    connect(client)
    _add_org("00Dyy0000002", "Beta Corp")
    _completed(ORG_A, "Acme Inc", 70, datetime(2026, 9, 1, tzinfo=timezone.utc))
    beta = _completed("00Dyy0000002", "Beta Corp", 55, datetime(2026, 9, 2, tzinfo=timezone.utc))
    v = _user(client, "viewer", org_ids=[ORG_A])
    viewer = _login(v["email"], v["password"])

    assert [o["orgId"] for o in viewer.get(f"{API}/portfolio").json()] == [ORG_A]
    assert [a["organizationName"] for a in viewer.get(f"{API}/assessments", params={"allOrgs": True}).json()["items"]] == ["Acme Inc"]
    assert viewer.get(f"{API}/assessments/{beta}").status_code == 404  # other client's check is invisible
    assert viewer.post(f"{API}/salesforce/connections/00Dyy0000002/activate").status_code == 404

    conn = viewer.get(f"{API}/salesforce/connection").json()
    assert conn["orgId"] == ORG_A
    run = viewer.post(f"{API}/assessments", json={"name": "x", "connectionId": conn["id"], "scope": {"categoryIds": ["data-quality"], "areaIds": ["area-1"]}})
    assert run.status_code == 403
    assert viewer.put(f"{API}/schedules/{ORG_A}", json={"frequency": "weekly"}).status_code == 403
    assert viewer.get(f"{API}/users").status_code == 403
    s = viewer.get(f"{API}/me/settings").json()
    assert viewer.put(f"{API}/me/settings", json={**s, "branding": {**s["branding"], "companyName": "Hacked"}}).status_code == 403


def test_active_org_is_per_user(client, sf):
    connect(client)
    _add_org("00Dyy0000002", "Beta Corp")
    c = _user(client, "consultant", all_orgs=True)
    consultant = _login(c["email"], c["password"])
    assert consultant.post(f"{API}/salesforce/connections/00Dyy0000002/activate").json()["active"] is True
    assert consultant.get(f"{API}/salesforce/connection").json()["organizationName"] == "Beta Corp"
    assert client.get(f"{API}/salesforce/connection").json()["orgId"] == ORG_A  # the admin's view didn't change


def test_consultant_connecting_an_org_gets_access(client, sf):
    c = _user(client, "consultant")
    consultant = _login(c["email"], c["password"])
    assert consultant.get(f"{API}/portfolio").json() == []
    connect(consultant)
    assert [o["orgId"] for o in consultant.get(f"{API}/portfolio").json()] == [ORG_A]
    assert consultant.delete(f"{API}/salesforce/connections/{ORG_A}").status_code == 403  # only admins disconnect


def test_team_management_and_last_admin(client):
    me = client.get(f"{API}/me").json()
    assert client.post(f"{API}/users", json={"name": "Dup", "email": ADMIN["email"], "role": "viewer", "password": "a long safe password"}).status_code == 409
    assert client.patch(f"{API}/users/{me['id']}", json={"role": "viewer"}).status_code == 409  # keep one admin
    v = _user(client, "viewer")
    viewer = _login(v["email"], v["password"])
    assert client.patch(f"{API}/users/{v['id']}", json={"isActive": False}).json()["isActive"] is False
    assert viewer.get(f"{API}/me").status_code == 401  # signed out at once
    r = TestClient(app).post(f"{API}/auth/login", json={"email": v["email"], "password": v["password"]})
    assert r.status_code == 403
    client.patch(f"{API}/users/{v['id']}", json={"isActive": True})
    assert client.post(f"{API}/users/{v['id']}/password", json={"password": "brand new password 1"}).status_code == 204
    _login(v["email"], "brand new password 1")
    with SessionLocal() as db:
        assert db.query(UserRow).filter(UserRow.email == v["email"]).one().password_hash.startswith("scrypt$")


def test_default_admin_from_environment(client):
    """DEFAULT_ADMIN_EMAIL / DEFAULT_ADMIN_PASSWORD create the first admin at start-up, and only while no one exists."""
    from app import auth
    from app.config import Settings

    settings = Settings(default_admin_email="Boss@Example.test", default_admin_password="example pass for tests", default_admin_name="Boss")
    with SessionLocal() as db:  # back to an empty install
        db.query(SessionRow).delete()
        db.query(UserRow).delete()
        db.commit()
    auth.ensure_default_admin(settings)
    c = _login("boss@example.test", "example pass for tests")
    me = c.get(f"{API}/me").json()
    assert me["role"] == "admin" and me["name"] == "Boss"

    auth.ensure_default_admin(Settings(default_admin_email="second@example.test", default_admin_password="another example pass"))
    with SessionLocal() as db:
        assert [u.email for u in db.query(UserRow).all()] == ["boss@example.test"]  # someone exists: nothing more is created
