"""Field check: empty values, duplicates and inconsistent spellings for each chosen field, plus all fields together."""
import pytest

from app.salesforce import duplicates, field_check

from .test_duplicates import DESCRIBE, StubSF

ROWS = [
    {"Id": "001A", "Name": "Acme, Inc.", "Phone": "415-555-1234", "BillingState": "California", "Industry": "Tech"},
    {"Id": "001B", "Name": "ACME", "Phone": "(415) 555-1234", "BillingState": "CA", "Industry": "Tech"},
    {"Id": "001C", "Name": "Globex", "Phone": None, "BillingState": "CA", "Industry": None},
    {"Id": "001D", "Name": "Initech", "Phone": "312-555-9999", "BillingState": "CA", "Industry": "Tech"},
    {"Id": "001E", "Name": "Hooli", "Phone": None, "BillingState": None, "Industry": "tech"},
]


@pytest.fixture(autouse=True)
def _describe(monkeypatch):
    monkeypatch.setattr(duplicates.explorer, "_describe", lambda sf, name: DESCRIBE[name])
    monkeypatch.setattr(duplicates.explorer, "_fields", lambda desc: {f["name"]: f for f in desc["fields"]})


def by_name(result):
    return {f["name"]: f for f in result["fields"]}


def test_each_field_gets_empty_duplicates_and_spellings():
    sf = StubSF(ROWS)
    out = field_check.check_fields(sf, "Account", ["Name", "Phone", "BillingState", "Industry"])
    assert len(sf.soql) == 1  # records are read once for every field
    f = by_name(out)
    assert out["scanned"] == 5
    assert (f["Phone"]["filled"], f["Phone"]["empty"]) == (3, 2)
    assert out["any_empty"] == 2  # Globex (no phone, industry) and Hooli (no phone, state): each counted once
    # Acme / ACME are the same company; the two phones are the same number written differently
    assert f["Name"]["duplicates"]["total_groups"] == 1 and f["Name"]["duplicates"]["extra_copies"] == 1
    assert f["Phone"]["duplicates"]["total_groups"] == 1
    # "California" is the odd spelling of CA (3 records use "CA")
    std = f["BillingState"]["standardization"]
    assert std["odd_records"] == 1 and std["variants"][0]["usual"] == "CA"
    assert [r["id"] for r in std["records"]] == ["001A"]
    # a shared picklist choice isn't a duplicate, but "tech" vs "Tech" is still an odd spelling
    assert f["Industry"]["duplicates"] is None and f["BillingState"]["duplicates"] is None  # shared by design
    assert f["Industry"]["standardization"]["odd_records"] == 1
    # several fields: duplicates must match on all of them (the two Acmes differ in state, so they don't)
    assert out["combined"]["total_groups"] == 0
    both = field_check.check_fields(StubSF(ROWS), "Account", ["Name", "Phone"])
    assert both["combined"]["total_groups"] == 1 and both["combined"]["rules"] == [["Account Name", "Account Phone"]]


def test_unknown_fields_are_refused():
    with pytest.raises(ValueError):
        field_check.check_fields(StubSF(ROWS), "Account", ["Nope) FROM User --"])
