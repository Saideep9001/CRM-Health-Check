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
