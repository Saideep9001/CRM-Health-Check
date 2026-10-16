"""Connected App keys entered on the Connect Salesforce page."""
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.config import Settings
from app.db import SessionLocal
from app.deps import settings_dep
from app.main import app
from app.models import SalesforceAppRow

from .conftest import CALLBACK, connect

API = "/api/v1"
KEY = "3MVG9TestConsumerKeyABCDEFGHIJ.klmnop_qrs"
SECRET = "1234567890ABCDEFSECRET"


def no_env_keys():
    app.dependency_overrides[settings_dep] = lambda: Settings(sf_client_id="", sf_client_secret="")


def test_not_configured_without_env_or_ui(client):
    no_env_keys()
    cfg = client.get(f"{API}/salesforce/app").json()
    assert cfg == {"configured": False, "source": None, "clientIdPreview": None, "callbackUrl": CALLBACK, "updatedAt": None}
    r = client.post(f"{API}/salesforce/oauth/start", json={"environment": "production", "redirectUri": CALLBACK})
    assert r.status_code == 501 and "Salesforce app setup" in r.json()["detail"]


def test_env_keys_are_reported_as_env(client):
    cfg = client.get(f"{API}/salesforce/app").json()
    assert cfg["configured"] is True and cfg["source"] == "env" and cfg["clientIdPreview"] == "test…t-id"


def test_save_keys_from_ui_masks_and_encrypts(client):
    no_env_keys()
    r = client.put(f"{API}/salesforce/app", json={"clientId": f"  {KEY} ", "clientSecret": SECRET})
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["configured"] is True and cfg["source"] == "ui" and cfg["updatedAt"]
    assert cfg["clientIdPreview"] == "3MVG…_qrs"
    assert SECRET not in r.text and KEY not in r.text  # secret never returned, key only masked
    with SessionLocal() as db:
        row = db.scalar(select(SalesforceAppRow))
        assert row.client_id == KEY and SECRET not in row.client_secret_enc


def test_ui_keys_are_used_for_sign_in(client):
    no_env_keys()
    client.put(f"{API}/salesforce/app", json={"clientId": KEY, "clientSecret": SECRET})
    url = client.post(f"{API}/salesforce/oauth/start", json={"environment": "production", "redirectUri": CALLBACK}).json()["authorizationUrl"]
    assert parse_qs(urlparse(url).query)["client_id"] == [KEY]


def test_ui_keys_override_env(client):
    client.put(f"{API}/salesforce/app", json={"clientId": KEY, "clientSecret": SECRET})
    assert client.get(f"{API}/salesforce/app").json()["source"] == "ui"
    # Removing them falls back to the .env keys.
    assert client.delete(f"{API}/salesforce/app").json()["source"] == "env"


def test_rejects_bad_keys(client):
    for body in (
        {"clientId": "short", "clientSecret": SECRET},
        {"clientId": KEY, "clientSecret": "abc"},
        {"clientId": "has spaces in the middle of it ok", "clientSecret": SECRET},
        {"clientId": KEY, "clientSecret": "<script>alert(1)</script>"},
    ):
        assert client.put(f"{API}/salesforce/app", json=body).status_code == 422


def test_switching_apps_disconnects(client, sf):
    connect(client)  # connected with the .env app
    assert client.get(f"{API}/salesforce/connection").json()["status"] == "connected"
    client.put(f"{API}/salesforce/app", json={"clientId": KEY, "clientSecret": SECRET})
    assert client.get(f"{API}/salesforce/connection").json()["status"] == "disconnected"
    assert sf.revoked == ["refresh-1"]


def test_saving_same_key_keeps_connection(client):
    connect(client)
    client.put(f"{API}/salesforce/app", json={"clientId": "test-client-id-0000000000", "clientSecret": "test-client-secret"})
    # Different key from the .env one ("test-client-id"), so this disconnects; now save the same key again:
    connect_after = client.put(f"{API}/salesforce/app", json={"clientId": "test-client-id-0000000000", "clientSecret": "rotated-secret-123"})
    assert connect_after.status_code == 200 and connect_after.json()["source"] == "ui"
