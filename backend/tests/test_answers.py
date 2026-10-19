"""Aqua's org-data answers: rule-based, read-only questions about the connected org."""
import pytest

from app.salesforce import finder

from .conftest import connect

API = "/api/v1/assistant/answer"


@pytest.fixture(autouse=True)
def _fresh_cache():
    finder.explorer.clear_cache()


def ask(client, question, context=None):
    return client.post(API, json={"question": question, "context": context})


def test_needs_a_connection(client):
    assert ask(client, "how many accounts").status_code == 409


def test_org_facts(client, sf):
    connect(client)
    a = ask(client, "what edition is our org?").json()
    assert "Enterprise Edition" in a["summary"] + " ".join(r["label"] + (r["detail"] or "") for r in a["rows"])
    assert any("FROM Organization" in q for q in sf.soql)


def test_record_lookup_searches_all_objects(client, sf):
    connect(client)
    a = ask(client, "find Acme").json()
    assert a["total"] == 2
    assert {r["label"] for r in a["rows"]} == {"Ada Lovelace", "Acme"}
    assert sf.search["q"] == ["Acme"]


def test_count_with_filters_links_to_your_data(client, sf):
    connect(client)
    a = ask(client, "how many Tech accounts").json()
    assert a["total"] == 42
    assert "Industry = 'Tech'" in sf.soql[-1] or any("Industry = 'Tech'" in q for q in sf.soql)
    assert a["appUrl"].startswith("/data/Account?")


def test_breakdown_uses_group_by(client, sf):
    connect(client)
    assert ask(client, "accounts by industry").status_code == 200
    assert any("GROUP BY Industry" in q for q in sf.soql)


def test_not_a_data_question_returns_null(client):
    connect(client)
    r = ask(client, "what is the weather")
    assert r.status_code == 200 and r.json() is None


def test_values_in_questions_are_escaped(client, sf):
    connect(client)
    ask(client, "accounts named \"x' OR Name != '\"")
    bs = chr(92)
    assert any(f"Name LIKE '%x{bs}' OR Name != {bs}'%'" in q for q in sf.soql)
    assert not any("OR Name != ''" in q for q in sf.soql)


def test_question_length_is_limited(client):
    connect(client)
    assert ask(client, "x" * 301).status_code == 422
