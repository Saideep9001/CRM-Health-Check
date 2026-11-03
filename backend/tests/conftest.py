"""Test setup: isolated SQLite DB, a test Connected App, and a fake Salesforce."""
import json
import os
import tempfile
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet

_tmp = tempfile.mkdtemp(prefix="aq-test-")
os.environ.update(
    # Set TEST_DATABASE_URL (e.g. postgresql+psycopg://…) to run the suite against PostgreSQL, as CI does.
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp}/test.db".replace("\\", "/"),
    JOB_MODE="inline",
    TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    SF_CLIENT_ID="test-client-id",
    SF_CLIENT_SECRET="test-client-secret",
    FRONTEND_ORIGIN="http://localhost:5173",
    SF_QUERY_API="rest",  # the fake org speaks REST; Bulk API jobs have their own tests (test_bulk.py)
    AUTH_REQUIRED="true",  # sign-in is off by default for testing the deployed app; the tests cover it switched on
    SF_CACHE_SECONDS="0",  # tests count Salesforce calls exactly; the read cache has its own test (test_read_cache.py)
)

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from sqlalchemy import text  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

INSTANCE = "https://acme.my.salesforce.com"
CALLBACK = "http://localhost:5173/connection/callback"


class FakeSalesforce:
    """Just enough of Salesforce's OAuth + REST API to exercise the backend."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.valid_access = {"access-1"}
        self.refresh_ok = True
        self.revoked: list[str] = []
        self.soql: list[str] = []
        self.rotate_refresh = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        self.calls.append((request.method, f"{url.netloc}{url.path}"))
        auth = request.headers.get("authorization", "").removeprefix("Bearer ")

        if url.path == "/services/oauth2/token":
            form = parse_qs(request.content.decode())
            grant = form["grant_type"][0]
            if form.get("client_secret", [""])[0] != "test-client-secret":
                return httpx.Response(400, json={"error": "invalid_client"})
            if grant == "authorization_code":
                if form["code"][0] != "good-code" or not form.get("code_verifier"):
                    return httpx.Response(400, json={"error": "invalid_grant", "error_description": "authentication failure"})
                return httpx.Response(200, json={"access_token": "access-1", "refresh_token": "refresh-1", "instance_url": INSTANCE, "id": f"https://{url.netloc}/id/00Dxx0000001/005xx0000001"})
            if grant == "refresh_token":
                if not self.refresh_ok:
                    return httpx.Response(400, json={"error": "invalid_grant", "error_description": "expired access/refresh token"})
                self.valid_access = {"access-2"}
                body = {"access_token": "access-2", "instance_url": INSTANCE}
                if self.rotate_refresh:  # Connected App with refresh token rotation
                    body["refresh_token"] = "refresh-2"
                return httpx.Response(200, json=body)
        if url.path == "/services/oauth2/revoke":
            self.revoked.append(parse_qs(request.content.decode())["token"][0])
            return httpx.Response(200)
        if url.path.startswith("/id/"):
            return httpx.Response(200, json={"organization_id": "00Dxx0000001", "display_name": "Test Admin", "username": "admin@acme.test"})

        # REST API requires a valid token.
        if auth not in self.valid_access:
            return httpx.Response(401, json=[{"message": "Session expired or invalid", "errorCode": "INVALID_SESSION_ID"}])
        if url.path.endswith("/limits/recordCount"):
            return httpx.Response(200, json={"sObjects": [{"name": "Account", "count": 120}, {"name": "Lead", "count": 42}]})
        if url.path.endswith("/sobjects"):
            return httpx.Response(200, json={"sobjects": [
                {"name": n, "label": n, "labelPlural": n + "s", "custom": n.endswith("__c"), "queryable": True, "retrieveable": True, "searchable": True, "keyPrefix": "001"}
                for n in ("Account", "Lead", "Invoice__c", "AccountHistory", "Contact", "Opportunity")
            ] + [{"name": "Hidden", "label": "Hidden", "queryable": False, "retrieveable": True}]})
        if url.path.endswith("/sobjects/Contact/describe"):
            return httpx.Response(200, json={"name": "Contact", "label": "Contact", "labelPlural": "Contacts", "fields": [
                {"name": "Id", "label": "Contact ID", "type": "id", "sortable": True, "filterable": True},
                {"name": "Name", "label": "Full Name", "type": "string", "nameField": True, "sortable": True, "filterable": True},
                {"name": "Email", "label": "Email", "type": "email", "sortable": True, "filterable": True},
                {"name": "AccountId", "label": "Account ID", "type": "reference", "relationshipName": "Account", "referenceTo": ["Account"], "filterable": True},
                {"name": "LastModifiedDate", "label": "Last Modified", "type": "datetime", "sortable": True, "filterable": True},
            ]})
        if url.path.endswith("/describe"):
            return httpx.Response(200, json={"name": "Account", "label": "Account", "labelPlural": "Accounts",
                "childRelationships": [
                    {"childSObject": "Opportunity", "field": "AccountId", "relationshipName": "Opportunities"},
                    {"childSObject": "Contact", "field": "AccountId", "relationshipName": "Contacts"},
                    {"childSObject": "AccountHistory", "field": "AccountId", "relationshipName": "Histories"},
                    {"childSObject": "Hidden", "field": "AccountId", "relationshipName": "Hiddens"},
                    {"childSObject": "Contact", "field": "Approver_Account__c", "relationshipName": "ApproverContacts__r"},
                    {"childSObject": "Contact", "field": "Other__c", "relationshipName": None},
                ],
                "fields": [
                {"name": "Id", "label": "Account ID", "type": "id", "sortable": True, "filterable": True, "nillable": False},
                {"name": "Name", "label": "Account Name", "type": "string", "nameField": True, "sortable": True, "filterable": True, "nillable": False, "createable": True},
                {"name": "Industry", "label": "Industry", "type": "picklist", "sortable": True, "filterable": True, "groupable": True, "nillable": True, "picklistValues": [{"value": "Tech", "active": True}]},
                {"name": "OwnerId", "label": "Owner ID", "type": "reference", "relationshipName": "Owner", "referenceTo": ["User"], "sortable": True, "filterable": True, "groupable": True},
                {"name": "BillingAddress", "label": "Billing Address", "type": "address"},
                {"name": "LastModifiedDate", "label": "Last Modified", "type": "datetime", "sortable": True, "filterable": True},
            ]})
        if "/sobjects/Account/001" in url.path:
            return httpx.Response(200, json={"attributes": {"type": "Account"}, "Id": "001000000000001AAA", "Name": "Acme", "OwnerId": "005000000000001"})
        if "/parameterizedSearch" in url.path:
            self.search = parse_qs(url.query)
            return httpx.Response(200, json={"searchRecords": [
                {"attributes": {"type": "Contact"}, "Id": "003000000000001AAA", "Name": "Ada Lovelace", "Email": "ada@acme.test"},
                {"attributes": {"type": "Account"}, "Id": "001000000000001AAA", "Name": "Acme"},
            ]})
        if url.path.endswith("/limits"):
            return httpx.Response(200, json={"DailyApiRequests": {"Max": 15000, "Remaining": 14250}})
        if url.path.endswith("/query"):
            q = parse_qs(url.query)["q"][0]
            self.soql.append(q)
            if "FROM Organization" in q:
                return httpx.Response(200, json={"totalSize": 1, "done": True, "records": [{"Name": "Acme Inc", "OrganizationType": "Enterprise Edition"}]})
            if " FROM Contact WHERE AccountId = " in q and "COUNT" not in q:
                return httpx.Response(200, json={"totalSize": 1, "done": True, "records": [{"Id": "003000000000001AAA", "Name": "Ada Lovelace", "Email": "ada@acme.test"}]})
            if " FROM Account" in q and "COUNT" not in q:
                self.batch = request.headers.get("sforce-query-options")
                return httpx.Response(200, json={"totalSize": 450, "done": False, "nextRecordsUrl": "/services/data/v61.0/query/01gxx0000001-200",
                    "records": [{"attributes": {}, "Id": "001000000000001AAA", "Name": "Acme", "Industry": "Tech", "OwnerId": "005000000000001", "Owner": {"Name": "Jane Doe"}}]})
            if q.startswith("SELECT COUNT() FROM"):
                return httpx.Response(200, json={"totalSize": 42, "done": True, "records": []})
            if "GROUP BY" in q or "SUM(Amount)" in q:
                return httpx.Response(200, json={"totalSize": 1, "done": True, "records": [{"deals": 3, "amount": 125000, "StageName": "Prospecting", "LeadSource": "Web", "total": 3}]})
            return httpx.Response(200, json={"totalSize": 1, "done": True, "records": [{"Id": "00Q000000000001", "Name": "Ada Lovelace", "Company": "Acme", "CreatedDate": "2026-09-01T10:00:00.000+0000", "Owner": {"Name": "Inbound Queue"}}]})
        return httpx.Response(404, json=[{"message": f"Not found: {url.path}"}])


@pytest.fixture
def sf() -> FakeSalesforce:
    return FakeSalesforce()


@pytest.fixture
def client(sf: FakeSalesforce):
    # Start empty; the app's start-up runs the real migrations to build the schema.
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    app.state.http_transport = httpx.MockTransport(sf.handler)
    with TestClient(app) as c:
        # Sign-in is on: create the first admin (first-run setup) and stay signed in for the test.
        r = c.post("/api/v1/auth/setup", json=ADMIN)
        assert r.status_code == 201, r.text
        yield c
    app.dependency_overrides.clear()


ADMIN = {"name": "Test Admin", "email": "admin@aquarient.test", "password": "correct horse battery"}


def connect(client: TestClient, environment: str = "production") -> dict:
    """Run the full sign-in flow and return the connection."""
    start = client.post("/api/v1/salesforce/oauth/start", json={"environment": environment, "redirectUri": CALLBACK}).json()
    state = parse_qs(urlparse(start["authorizationUrl"]).query)["state"][0]
    resp = client.post("/api/v1/salesforce/oauth/callback", json={"code": "good-code", "state": state, "redirectUri": CALLBACK})
    assert resp.status_code == 200, resp.text
    return resp.json()


def dumps(o) -> str:
    return json.dumps(o, indent=2, default=str)
