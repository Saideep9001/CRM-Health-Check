"""Excel-style column filters on the records behind a measure or a problem."""
import json

from .conftest import connect
from .test_engine import API, sf, start  # noqa: F401  (sf is the fake org fixture)

ONLY = json.dumps([{"field": "Email", "op": "in", "value": ["a@x.com", None]}])


def _contact_measure_and_problem(client):
    aid = start(client, areas=("area-1",), objects=["Contact"]).json()["id"]
    res = client.get(f"{API}/assessments/{aid}/results").json()
    measure = next(i for a in res["areas"] for i in a["indicators"] if "Contact" in i.get("recordObjects", []))
    problem = next(f for f in client.get(f"{API}/assessments/{aid}/findings").json()["items"] if f["recordsAvailable"])
    return aid, measure, problem


def test_filters_narrow_a_measures_records_and_its_values(client, sf):
    connect(client)
    aid, measure, _ = _contact_measure_and_problem(client)
    base = f"{API}/assessments/{aid}/areas/area-1"
    params = {"label": measure["label"], "object": "Contact"}

    assert client.get(f"{base}/indicator-records", params={**params, "filters": ONLY}).status_code == 200
    q = sf.soql[-1]
    # the measure's own records, then the column filter on top (a None value means "or blank")
    assert " FROM Contact WHERE (" in q and "AND (Email IN ('a@x.com') OR Email = null)" in q

    assert client.get(f"{base}/indicator-values", params={**params, "field": "Email"}).status_code == 200
    q = sf.soql[-1]
    assert q.startswith("SELECT Email v, COUNT(Id) c FROM Contact WHERE (") and "GROUP BY Email" in q

    csv = client.get(f"{base}/indicator-records.csv", params={**params, "filters": ONLY})
    assert csv.status_code == 200 and "Email IN ('a@x.com')" in sf.soql[-1]


def test_filters_narrow_a_problems_records_and_bad_filters_are_refused(client, sf):
    connect(client)
    _, _, problem = _contact_measure_and_problem(client)
    url = f"{API}/findings/{problem['id']}"
    assert client.get(f"{url}/records", params={"filters": ONLY}).status_code == 200
    assert "(Email IN ('a@x.com') OR Email = null)" in sf.soql[-1]
    assert client.get(f"{url}/values", params={"field": "Email"}).status_code == 200
    assert sf.soql[-1].startswith("SELECT Email v, COUNT(Id) c FROM ")
    evil = json.dumps([{"field": "Email) FROM User --", "op": "in", "value": ["x"]}])
    assert client.get(f"{url}/records", params={"filters": evil}).status_code == 422
    assert client.get(f"{url}/records", params={"filters": "not json"}).status_code == 422


def test_a_column_asked_for_twice_is_selected_once(monkeypatch):
    from app.salesforce import explorer as ex

    class SF:
        base = "https://acme.my.salesforce.com"
        soql: list[str] = []

        def get(self, url, headers=None):
            from urllib.parse import parse_qs, urlparse
            self.soql.append(parse_qs(urlparse(url).query)["q"][0])
            return {"records": [], "totalSize": 0, "done": True}

        def query_page(self, soql, page_size):
            self.soql.append(soql)
            return {"records": [], "totalSize": 0, "done": True}

    fake = SF()
    monkeypatch.setattr(ex, "_api", lambda s: "/services/data/v61.0")
    monkeypatch.setattr(ex, "_describe", lambda s, name: {"fields": [{"name": n, "type": "string", "sortable": True, "filterable": True}
                                                                     for n in ("Id", "Name", "Website")]})
    ex.records_matching(fake, "Account", None, columns=["Name", "Name", "Website"])  # e.g. the name and a compared field
    assert fake.soql[-1].startswith("SELECT Name, Website") and fake.soql[-1].count("Name,") == 1


def test_flagged_values_come_with_the_reason_on_their_cell(client, sf, monkeypatch):
    from app.routers import assessments as routes
    from app.salesforce import explorer

    connect(client)
    aid = start(client, areas=("area-1",), objects=["Account"]).json()["id"]
    params = {"label": "Data Standardization Issues (Accounts)", "object": "Account"}
    shown = ["001000000000001AAA", "001000000000099AAA"]  # a flagged record, and one that isn't
    page = {"object": "Account", "columns": [{"name": "Phone", "label": "Phone", "type": "phone"}], "totalSize": 2, "next_cursor": None,
            "record_url_prefix": "https://acme.my.salesforce.com/", "records": [{"id": i, "values": {"Phone": "415-555-1234"}, "ref_names": {}} for i in shown]}
    monkeypatch.setattr(explorer, "records_matching", lambda *a, **k: page)
    monkeypatch.setattr(routes, "_salesforce", lambda db, http, settings, fn, org_id: fn(None))
    got = client.get(f"{API}/assessments/{aid}/areas/area-1/indicator-records", params=params).json()["cellNotes"]
    assert list(got) == [shown[0]] and got[shown[0]]["Phone"].startswith("no country code")  # "415-555-1234"
    csv = client.get(f"{API}/assessments/{aid}/areas/area-1/indicator-records.csv", params=params).text
    assert "Why it’s flagged" in csv.splitlines()[0]


def test_a_measures_records_narrow_to_chosen_fields(client, sf):
    connect(client)
    aid = start(client, areas=("area-1",), objects=["Account"]).json()["id"]
    base = f"{API}/assessments/{aid}/areas/area-1"
    # missing key fields: records with any chosen field empty
    params = {"label": "Missing Key Fields (Accounts)", "object": "Account", "only": "Phone,Website"}
    assert client.get(f"{base}/indicator-records", params=params).status_code == 200
    assert "AND (Phone = null OR Website = null)" in sf.soql[-1]  # within the measure's own records
    # data standardization: records with a reason on a chosen field
    params = {"label": "Data Standardization Issues (Accounts)", "object": "Account", "only": "Phone"}
    assert client.get(f"{base}/indicator-records", params=params).status_code == 200
    assert "Id IN ('001000000000001AAA'" in sf.soql[-1]
    assert client.get(f"{base}/indicator-records.csv", params=params).status_code == 200
    bad = {**params, "only": "Phone) FROM User --"}
    assert client.get(f"{base}/indicator-records", params=bad).status_code == 422


def test_no_activity_records_take_another_period(client, sf):
    from datetime import date, timedelta

    connect(client)
    aid = start(client, areas=("area-1",), objects=["Account"]).json()["id"]
    base = f"{API}/assessments/{aid}/areas/area-1"
    params = {"label": "No Activity in 6 Months (Accounts)", "object": "Account"}
    assert client.get(f"{base}/indicator-records", params={**params, "period": "90"}).status_code == 200
    q = sf.soql[-1]
    assert "LastModifiedDate < LAST_N_DAYS:90" in q and "LAST_N_DAYS:180" not in q  # this fake Account has no activity date

    rng = "range:2024-01-15:2024-03-31"  # last activity between these days, both included
    assert client.get(f"{base}/indicator-values", params={**params, "field": "Industry", "period": rng}).status_code == 200
    assert "(LastModifiedDate >= 2024-01-15T00:00:00Z AND LastModifiedDate < 2024-04-01T00:00:00Z)" in sf.soql[-1]
    assert client.get(f"{base}/indicator-records.csv", params={**params, "period": rng}).status_code == 200

    later = (date.today() + timedelta(days=3)).isoformat()
    for bad in ("100", "range:2024-13-01:2024-12-01", "range:2024-03-01:2024-01-01", f"range:{later}:{later}", "range:2024-01-01:2024-02-01 OR Id != null"):
        assert client.get(f"{base}/indicator-records", params={**params, "period": bad}).status_code == 422, bad
    other = {"label": "Missing Key Fields (Accounts)", "object": "Account", "period": "90"}
    assert client.get(f"{base}/indicator-records", params=other).status_code == 422
