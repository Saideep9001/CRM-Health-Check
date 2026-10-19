from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.config import Settings
from app.db import SessionLocal
from app.deps import settings_dep
from app.main import app
from app.models import SalesforceConnectionRow
from app.salesforce.crm_queries import LOOKUPS

from .conftest import CALLBACK, INSTANCE, connect

API = "/api/v1"


def test_health_and_disconnected_by_default(client):
    assert client.get(f"{API}/health").json()["status"] == "ok"
    conn = client.get(f"{API}/salesforce/connection").json()
    assert conn["status"] == "disconnected"
    assert "accessToken" not in conn and "access_token" not in conn


def test_start_requires_connected_app(client):
    app.dependency_overrides[settings_dep] = lambda: Settings(sf_client_id="", sf_client_secret="")
    r = client.post(f"{API}/salesforce/oauth/start", json={"environment": "production", "redirectUri": CALLBACK})
    assert r.status_code == 501 and "Salesforce app setup" in r.json()["detail"]


def test_start_validates_redirect_and_domain(client):
    r = client.post(f"{API}/salesforce/oauth/start", json={"environment": "production", "redirectUri": "https://evil.example/cb"})
    assert r.status_code == 422
    r = client.post(f"{API}/salesforce/oauth/start", json={"environment": "custom", "myDomain": "evil.example.com", "redirectUri": CALLBACK})
    assert r.status_code == 422


def test_start_builds_pkce_authorize_url(client):
    r = client.post(f"{API}/salesforce/oauth/start", json={"environment": "sandbox", "redirectUri": CALLBACK}).json()
    url = urlparse(r["authorizationUrl"])
    q = parse_qs(url.query)
    assert url.netloc == "test.salesforce.com" and url.path == "/services/oauth2/authorize"
    assert q["client_id"] == ["test-client-id"] and q["redirect_uri"] == [CALLBACK]
    assert q["code_challenge_method"] == ["S256"] and len(q["code_challenge"][0]) >= 43
    assert q["state"] == [r["state"]]


def test_custom_domain_login_host(client):
    r = client.post(f"{API}/salesforce/oauth/start", json={"environment": "custom", "myDomain": "https://Acme.my.salesforce.com/", "redirectUri": CALLBACK}).json()
    assert urlparse(r["authorizationUrl"]).netloc == "acme.my.salesforce.com"


def test_full_connect_flow_stores_encrypted_tokens(client, sf):
    conn = connect(client)
    assert conn["status"] == "connected"
    assert conn["organizationName"] == "Acme Inc" and conn["edition"] == "Enterprise Edition"
    assert conn["orgId"] == "00Dxx0000001" and conn["connectedBy"] == "Test Admin"
    assert conn["instanceUrl"] == INSTANCE
    assert conn["apiRequestsMax"] == 15000 and conn["apiRequestsRemaining"] == 14250
    with SessionLocal() as db:
        row = db.scalar(select(SalesforceConnectionRow))
        assert "access-1" not in row.access_token_enc and "refresh-1" not in (row.refresh_token_enc or "")


def test_callback_rejects_bad_or_reused_state(client):
    r = client.post(f"{API}/salesforce/oauth/callback", json={"code": "good-code", "state": "made-up", "redirectUri": CALLBACK})
    assert r.status_code == 400
    start = client.post(f"{API}/salesforce/oauth/start", json={"environment": "production", "redirectUri": CALLBACK}).json()
    body = {"code": "good-code", "state": start["state"], "redirectUri": CALLBACK}
    assert client.post(f"{API}/salesforce/oauth/callback", json=body).status_code == 200
    assert client.post(f"{API}/salesforce/oauth/callback", json=body).status_code == 400  # one-time use


def test_callback_reports_salesforce_rejection(client):
    start = client.post(f"{API}/salesforce/oauth/start", json={"environment": "production", "redirectUri": CALLBACK}).json()
    r = client.post(f"{API}/salesforce/oauth/callback", json={"code": "bad-code", "state": start["state"], "redirectUri": CALLBACK})
    assert r.status_code == 400 and "authentication failure" in r.json()["detail"]


def test_crm_queries_need_connection_and_known_id(client):
    assert client.post(f"{API}/assistant/crm-query", json={"queryId": "leads.open"}).status_code == 409
    connect(client)
    assert client.post(f"{API}/assistant/crm-query", json={"queryId": "DELETE everything"}).status_code == 422


def test_every_crm_lookup_runs_read_only(client, sf):
    connect(client)
    sf.soql.clear()
    for qid in LOOKUPS:
        r = client.post(f"{API}/assistant/crm-query", json={"queryId": qid})
        assert r.status_code == 200, (qid, r.text)
        body = r.json()
        assert body["id"] == qid and body["title"] and body["summary"] and "asOf" in body
        for row in body["rows"]:
            if row.get("url"):
                assert row["url"].startswith(f"{INSTANCE}/lightning/r/")
    assert sf.soql and all(q.lstrip().upper().startswith("SELECT ") for q in sf.soql)


def test_unassigned_leads_answer(client):
    connect(client)
    body = client.post(f"{API}/assistant/crm-query", json={"queryId": "leads.unassigned"}).json()
    assert body["total"] == 42 and "42 leads" in body["summary"]
    assert body["rows"][0]["label"] == "Ada Lovelace"
    assert body["rows"][0]["url"] == f"{INSTANCE}/lightning/r/Lead/00Q000000000001/view"
    assert "Inbound Queue" in body["rows"][0]["detail"]


def test_expired_access_token_is_refreshed_transparently(client, sf):
    connect(client)
    sf.valid_access = {"access-2"}  # access-1 now rejected; refresh issues access-2
    r = client.post(f"{API}/assistant/crm-query", json={"queryId": "accounts.count"})
    assert r.status_code == 200 and r.json()["total"] == 42
    with SessionLocal() as db:
        from app import crypto

        assert crypto.decrypt(db.scalar(select(SalesforceConnectionRow)).access_token_enc) == "access-2"


def test_failed_refresh_marks_connection_expired(client, sf):
    connect(client)
    sf.valid_access = set()
    sf.refresh_ok = False
    r = client.post(f"{API}/assistant/crm-query", json={"queryId": "accounts.count"})
    assert r.status_code == 409 and "reconnect" in r.json()["detail"].lower()
    assert client.get(f"{API}/salesforce/connection").json()["status"] == "expired"


def test_check_connection_updates_limits(client, sf):
    connect(client)
    conn = client.post(f"{API}/salesforce/connection/check").json()
    assert conn["status"] == "connected" and conn["lastCheckedAt"]
    sf.valid_access, sf.refresh_ok = set(), False
    assert client.post(f"{API}/salesforce/connection/check").json()["status"] == "expired"


def test_disconnect_revokes_and_forgets(client, sf):
    connect(client)
    assert client.delete(f"{API}/salesforce/connection").status_code == 204
    assert sf.revoked == ["refresh-1"]
    assert client.get(f"{API}/salesforce/connection").json()["status"] == "disconnected"


def test_rotated_refresh_token_is_saved(client, sf):
    """With refresh token rotation, Salesforce retires the old refresh token, so the new one must be stored."""
    connect(client)
    sf.valid_access, sf.rotate_refresh = {"access-2"}, True
    assert client.post(f"{API}/assistant/crm-query", json={"queryId": "accounts.count"}).status_code == 200
    with SessionLocal() as db:
        from app import crypto

        row = db.scalar(select(SalesforceConnectionRow))
        assert crypto.decrypt(row.refresh_token_enc) == "refresh-2" and crypto.decrypt(row.access_token_enc) == "access-2"
