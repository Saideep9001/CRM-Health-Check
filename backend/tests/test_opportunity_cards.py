"""Area 1 for Opportunities: missing and invalid fields, and the Opportunity cards."""
from .conftest import connect
from .test_engine import API, sf, start  # noqa: F401  (sf is the fake org fixture)


def test_opportunity_cards(client, sf):
    connect(client)
    aid = start(client, areas=("area-1",), objects=["Opportunity"]).json()["id"]
    res = client.get(f"{API}/assessments/{aid}/results").json()
    ind = {i["label"]: i for a in res["areas"] for i in a["indicators"]}
    missing = dict(ind["Missing Key Fields (Opportunities)"]["criteria"])
    assert missing["Fields checked"] == "Amount, NextStep"  # the fake org's Opportunity has no Close Date
    assert "Opportunities Without Contact Roles" not in ind  # in Area 4 now
    assert not any("OpportunityContactRole" in q for q in sf.soql)
