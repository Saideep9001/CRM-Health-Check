"""Clicking around the app reuses recent Salesforce reads instead of spending an API call each time."""
from app.config import get_settings
from app.salesforce import client as sf_client, explorer

from .conftest import connect

API = "/api/v1"


def _calls(sf, path_part: str) -> int:
    return sum(1 for _, p in sf.calls if path_part in p)


def test_repeat_reads_are_free_and_refresh_reads_live(client, sf, monkeypatch):
    connect(client)
    monkeypatch.setattr(get_settings(), "sf_cache_seconds", 300)
    sf_client.forget_reads()
    explorer.clear_cache()

    def open_page():
        explorer.clear_cache()  # only the read cache may save calls here
        r = client.get(f"{API}/data/objects/Account/records")
        assert r.status_code == 200, r.text

    open_page()
    first = _calls(sf, "/query")
    describes = _calls(sf, "/describe")
    open_page()
    open_page()
    assert _calls(sf, "/query") == first and _calls(sf, "/describe") == describes  # same page again: no new calls

    assert client.post(f"{API}/data/refresh").status_code == 204  # Refresh: the next read goes to Salesforce
    open_page()
    assert _calls(sf, "/query") == first + 1


def test_health_checks_and_limits_always_read_live(client, sf, monkeypatch):
    connect(client)
    monkeypatch.setattr(get_settings(), "sf_cache_seconds", 300)
    sf_client.forget_reads()
    before = _calls(sf, "/limits")
    client.post(f"{API}/salesforce/connection/check")
    client.post(f"{API}/salesforce/connection/check")
    assert _calls(sf, "/limits") == before + 2  # live counters are never cached


def test_snapshot_refresh_reads_live(client, sf, monkeypatch):
    connect(client)
    monkeypatch.setattr(get_settings(), "sf_cache_seconds", 300)
    sf_client.forget_reads()
    assert client.get(f"{API}/salesforce/connection/snapshot").status_code == 200
    n = len(sf.calls)
    client.get(f"{API}/salesforce/connection/snapshot")
    cached = len(sf.calls) - n  # only the never-cached live counters
    n = len(sf.calls)
    client.get(f"{API}/salesforce/connection/snapshot", params={"fresh": "true"})
    assert len(sf.calls) - n > cached  # Refresh reads everything again
