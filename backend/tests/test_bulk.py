"""Bulk API 2.0 record queries: jobs, CSV pages and the REST-shaped results callers expect."""
import json

import httpx

from app import crypto
from app.config import get_settings
from app.models import SalesforceConnectionRow
from app.salesforce import bulk, explorer
from app.salesforce.client import SalesforceClient

DESCRIBE = {
    "Account": {"fields": [
        {"name": "Id", "type": "id"}, {"name": "Name", "type": "string"}, {"name": "NumberOfEmployees", "type": "int"},
        {"name": "AnnualRevenue", "type": "currency"}, {"name": "IsDeleted", "type": "boolean"},
        {"name": "OwnerId", "type": "reference", "relationshipName": "Owner", "referenceTo": ["User"]},
    ]},
    "User": {"fields": [{"name": "Id", "type": "id"}, {"name": "Name", "type": "string"}]},
}
CSV_PAGES = [
    'Id,Name,NumberOfEmployees,AnnualRevenue,IsDeleted,Owner.Name\n'
    '001000000000001AAA,Acme,25,1500.5,false,Ann Lee\n'
    '001000000000002AAA,"Globex, Inc",,,true,\n',
    'Id,Name,NumberOfEmployees,AnnualRevenue,IsDeleted,Owner.Name\n001000000000003AAA,Initech,7,0,false,Bob Ray\n',
]


class FakeBulk:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[str] = []
        self.rest_queries: list[str] = []
        self.polls = 0

    def handler(self, req: httpx.Request) -> httpx.Response:
        path, method = req.url.path, req.method
        self.calls.append(f"{method} {path}")
        if path.endswith("/jobs/query") and method == "POST":
            body = json.loads(req.content)
            assert body["operation"] == "query" and "COUNT(" not in body["query"]
            if self.fail:
                return httpx.Response(400, json=[{"errorCode": "INVALIDJOB", "message": "Object not supported"}])
            return httpx.Response(200, json={"id": "750000000000001AAA", "state": "UploadComplete"})
        if path.endswith("/jobs/query/750000000000001AAA") and method == "GET":
            self.polls += 1
            done = self.polls > 1  # in progress once, then finished
            return httpx.Response(200, json={"id": "750000000000001AAA", "state": "JobComplete" if done else "InProgress",
                                             "numberRecordsProcessed": 3})
        if path.endswith("/results"):
            n = 1 if req.url.params.get("locator") == "LOC2" else 0
            return httpx.Response(200, text=CSV_PAGES[n], headers={"Sforce-Locator": "LOC2" if n == 0 else "null"})
        if method == "DELETE":
            return httpx.Response(204)
        if path.endswith("/query"):
            self.rest_queries.append(req.url.params["q"])
            return httpx.Response(200, json={"totalSize": 3, "done": True, "records": []})
        return httpx.Response(404)


def _client(fake: FakeBulk, monkeypatch) -> SalesforceClient:
    monkeypatch.setattr(explorer, "_describe", lambda sf, name: DESCRIBE[name])
    bulk._columns.clear()
    conn = SalesforceConnectionRow(instance_url="https://acme.my.salesforce.com", access_token_enc=crypto.encrypt("token"),
                                   login_host="login.salesforce.com", environment="production", org_id="00D000000000001AAA")
    settings = get_settings().model_copy(update={"sf_query_api": "bulk"})
    sf = SalesforceClient(httpx.Client(transport=httpx.MockTransport(fake.handler)), conn, settings, None, lambda: None)
    sf._sleep = lambda s: None
    return sf


def test_a_record_query_runs_as_a_bulk_job_and_reads_like_rest(monkeypatch):
    fake = FakeBulk()
    sf = _client(fake, monkeypatch)
    out = sf.query("SELECT Id, Name, NumberOfEmployees, AnnualRevenue, IsDeleted, Owner.Name FROM Account")
    assert out["totalSize"] == 3 and out["done"] is True and [r["Id"] for r in out["records"]][-1] == "001000000000003AAA"
    acme, globex, _ = out["records"]
    # types come back as REST gives them; blanks are None; a parent field is nested, an empty lookup is null
    assert (acme["NumberOfEmployees"], acme["AnnualRevenue"], acme["IsDeleted"]) == (25, 1500.5, False)
    assert acme["Owner"] == {"Name": "Ann Lee"} and acme["attributes"] == {"type": "Account"}
    assert (globex["Name"], globex["NumberOfEmployees"], globex["IsDeleted"], globex["Owner"]) == ("Globex, Inc", None, True, None)
    assert "DELETE /services/data/v61.0/jobs/query/750000000000001AAA" in fake.calls  # tidied up once read
    assert not fake.rest_queries


def test_counts_stay_on_rest_and_a_refused_job_falls_back(monkeypatch):
    fake = FakeBulk()
    sf = _client(fake, monkeypatch)
    sf.query("SELECT COUNT() FROM Account")
    sf.query("SELECT Industry v, COUNT(Id) c FROM Account GROUP BY Industry")
    assert len(fake.rest_queries) == 2 and not any("jobs" in c for c in fake.calls)
    refused = FakeBulk(fail=True)
    sf = _client(refused, monkeypatch)
    assert sf.query("SELECT Id FROM Account")["done"] and refused.rest_queries == ["SELECT Id FROM Account"]


def test_record_tables_page_through_a_bulk_job(monkeypatch):
    fake = FakeBulk()
    sf = _client(fake, monkeypatch)
    first = sf.query_page("SELECT Id, Name FROM Account", 2)
    assert len(first["records"]) == 2 and first["totalSize"] == 3
    cursor = first["nextRecordsUrl"]
    assert explorer._CURSOR_RE.match(cursor) and cursor == "bulk:750000000000001AAA:Account~LOC2"
    rest = sf.query_more(cursor, 2)
    assert [r["Id"] for r in rest["records"]] == ["001000000000003AAA"] and rest["nextRecordsUrl"] is None
    assert not explorer._CURSOR_RE.match("bulk:750000000000001AAA:Account~LOC2&x=1")  # nothing else gets through


def test_auto_uses_bulk_only_for_big_objects(monkeypatch):
    fake = FakeBulk()
    sf = _client(fake, monkeypatch)
    sf.settings = sf.settings.model_copy(update={"sf_query_api": "auto", "sf_bulk_min_records": 20_000})
    monkeypatch.setattr(explorer, "_record_counts", lambda s: {"Account": 350_000, "Contact": 900})
    sf.query("SELECT Id, Name FROM Contact")  # small: REST
    assert fake.rest_queries == ["SELECT Id, Name FROM Contact"] and not any("jobs" in c for c in fake.calls)
    sf.query("SELECT Id, Name FROM Account")  # big: a Bulk job
    assert any(c.startswith("POST") and c.endswith("/jobs/query") for c in fake.calls) and len(fake.rest_queries) == 1
    sf.query("SELECT COUNT() FROM Account")  # a count never runs as a job
    assert len(fake.rest_queries) == 2
