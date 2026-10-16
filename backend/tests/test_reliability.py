"""Retrying Salesforce hiccups and protecting the org's daily API budget."""
import httpx
import pytest

from app import crypto
from app.config import get_settings
from app.models import SalesforceConnectionRow
from app.salesforce import client as sfclient
from app.salesforce.client import SalesforceClient
from app.salesforce.errors import SalesforceError

from .conftest import FakeSalesforce, connect

API = "/api/v1"


def _client(handler) -> SalesforceClient:
    conn = SalesforceConnectionRow(instance_url="https://acme.my.salesforce.com", access_token_enc=crypto.encrypt("token"),
                                   login_host="login.salesforce.com", environment="production")
    sf = SalesforceClient(httpx.Client(transport=httpx.MockTransport(handler)), conn, get_settings(), None, lambda: None)
    sf._sleep = lambda s: None  # no real waiting in tests
    return sf


def test_retries_brief_salesforce_hiccups():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"ok": True})

    assert _client(handler).get("/services/data/v61.0/limits") == {"ok": True}
    assert len(calls) == 3


def test_retries_network_timeouts():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, json={"ok": True})

    assert _client(handler).get("/x") == {"ok": True}


def test_gives_up_after_a_few_tries_and_never_retries_real_errors():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(503, json=[{"message": "Down for maintenance"}])

    with pytest.raises(SalesforceError, match="Down for maintenance"):
        _client(handler).get("/x")
    assert len(calls) == sfclient.RETRIES + 1

    calls.clear()

    def bad_query(req):
        calls.append(req)
        return httpx.Response(400, json=[{"message": "MALFORMED_QUERY", "errorCode": "MALFORMED_QUERY"}])

    with pytest.raises(SalesforceError):
        _client(bad_query).get("/x")
    assert len(calls) == 1  # a real error is reported straight away


class LowBudgetOrg(FakeSalesforce):
    def handler(self, request):
        if request.url.path.endswith("/limits"):
            return httpx.Response(200, json={"DailyApiRequests": {"Max": 15000, "Remaining": 400}})
        return super().handler(request)


@pytest.fixture
def sf():
    return LowBudgetOrg()


def test_check_does_not_start_when_the_api_budget_is_nearly_used(client, sf):
    connect(client)
    conn = client.get(f"{API}/salesforce/connection").json()
    aid = client.post(f"{API}/assessments", json={"name": "x", "connectionId": conn["id"], "scope": {"areaIds": ["area-1"]}}).json()["id"]
    a = client.get(f"{API}/assessments/{aid}").json()
    assert a["status"] == "failed" and "400 of today’s 15,000" in a["errorMessage"]
    assert not any("FROM Account" in q for q in sf.soql)  # nothing was spent on the check
