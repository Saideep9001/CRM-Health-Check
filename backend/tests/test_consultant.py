"""Consultant features: saved orgs (portfolio), scheduled checks and alerts, notifications, proposals, benchmarks, fix plans."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import alerts, crypto
from app.db import SessionLocal
from app.engine import jobs, scheduler
from app.main import app
from app.models import AssessmentRow, FindingRow, NotificationRow, SalesforceConnectionRow, ScanScheduleRow
from app.salesforce import explorer

from . import test_engine as te
from .conftest import connect

API = "/api/v1"
ORG_A = "00Dxx0000001"


@pytest.fixture
def sf():
    explorer.clear_cache()
    return te.FakeOrg()


def _add_org(org_id: str, name: str, active: bool = False) -> None:
    with SessionLocal() as db:
        db.add(SalesforceConnectionRow(
            workspace=f"org-{org_id}", status="connected", environment="production", login_host="login.salesforce.com",
            instance_url=f"https://{org_id}.my.salesforce.com", org_id=org_id, organization_name=name,
            access_token_enc=crypto.encrypt("x"), refresh_token_enc=crypto.encrypt("y"), active=active,
        ))
        db.commit()


def _completed(org_id: str, name: str, score: int, when: datetime, areas: dict[str, int] | None = None) -> str:
    aid = str(uuid.uuid4())
    area_rows = [{"areaId": a, "score": s, "status": "assessed", "indicators": [], "recordsEvaluated": None, "message": None}
                 for a, s in (areas or {"area-1": score}).items()]
    with SessionLocal() as db:
        db.add(AssessmentRow(id=aid, name="Check", connection_id=org_id, organization_name=name, org_id=org_id, status="completed",
                             scope={"categoryIds": ["data-quality"], "areaIds": list((areas or {"area-1": 0}).keys())},
                             created_at=when, completed_at=when, overall_score=score, findings_count=0,
                             results={"assessmentId": aid, "areas": area_rows, "categories": [{"categoryId": "data-quality", "score": score}],
                                      "overallScore": score}))
        db.commit()
    return aid


def test_portfolio_switching_and_history_per_org(client, sf):
    connect(client)
    _add_org("00Dyy0000002", "Beta Corp")
    _completed(ORG_A, "Acme Inc", 70, datetime(2026, 9, 1, tzinfo=timezone.utc))
    _completed("00Dyy0000002", "Beta Corp", 55, datetime(2026, 9, 2, tzinfo=timezone.utc))
    _completed("00Dzz0000003", "Gamma (disconnected)", 80, datetime(2026, 9, 3, tzinfo=timezone.utc))

    orgs = {o["orgId"]: o for o in client.get(f"{API}/portfolio").json()}
    assert set(orgs) == {ORG_A, "00Dyy0000002", "00Dzz0000003"}
    assert orgs[ORG_A]["active"] and orgs[ORG_A]["score"] == 70 and orgs["00Dzz0000003"]["connectionStatus"] == "disconnected"
    assert orgs[ORG_A]["categoryScores"] == [{"categoryId": "data-quality", "score": 70}] and orgs[ORG_A]["topProblems"] == []

    # History and the dashboard follow the active org.
    assert [a["organizationName"] for a in client.get(f"{API}/assessments").json()["items"]] == ["Acme Inc"]
    assert len(client.get(f"{API}/assessments", params={"allOrgs": True}).json()["items"]) == 3
    assert client.post(f"{API}/salesforce/connections/00Dyy0000002/activate").json()["active"] is True
    assert client.get(f"{API}/salesforce/connection").json()["organizationName"] == "Beta Corp"
    assert [a["organizationName"] for a in client.get(f"{API}/assessments").json()["items"]] == ["Beta Corp"]
    assert client.post(f"{API}/salesforce/connections/00Dnope/activate").status_code == 404

    # Removing the active org makes another saved org active; its past checks stay.
    assert client.delete(f"{API}/salesforce/connections/00Dyy0000002").status_code == 204
    assert client.get(f"{API}/salesforce/connection").json()["orgId"] == ORG_A
    assert "00Dyy0000002" in {o["orgId"] for o in client.get(f"{API}/portfolio").json()}


def test_reconnecting_keeps_one_row_per_org(client, sf):
    connect(client)
    connect(client)
    with SessionLocal() as db:
        assert db.query(SalesforceConnectionRow).count() == 1


def test_schedule_runs_and_alerts(client, sf, monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "send_email", lambda settings, to, subject, text, wait=False: sent.append((to, subject, text)))
    connect(client)
    _completed(ORG_A, "Acme Inc", 99, datetime.now(timezone.utc) - timedelta(days=30))

    assert client.put(f"{API}/schedules/00Dnope", json={"frequency": "weekly"}).status_code == 404
    assert client.put(f"{API}/schedules/{ORG_A}", json={"frequency": "hourly"}).status_code == 422
    assert client.put(f"{API}/schedules/{ORG_A}", json={"frequency": "weekly", "alertEmail": "not-an-email"}).status_code == 422
    s = client.put(f"{API}/schedules/{ORG_A}", json={"frequency": "weekly", "areaIds": ["area-1", "area-99"], "alertEmail": "cs@aquarient.test", "scoreDrop": 5}).json()
    assert s["areaIds"] == ["area-1"] and s["enabled"]
    next_run = datetime.fromisoformat(s["nextRunAt"])
    assert timedelta(days=6) < next_run - datetime.now(timezone.utc) < timedelta(days=8)

    with SessionLocal() as db:
        assert scheduler.enqueue_due(db) == []  # not due yet
        ids = scheduler.enqueue_due(db, now=next_run + timedelta(minutes=1))
        assert len(ids) == 1
        assert scheduler.enqueue_due(db, now=next_run + timedelta(minutes=2)) == []  # claimed once only
        row = db.get(AssessmentRow, ids[0])
        assert row.created_by == alerts.SCHEDULER and row.scope["areaIds"] == ["area-1"] and row.status == "queued"
        sched = db.query(ScanScheduleRow).one()
        assert sched.next_run_at.replace(tzinfo=timezone.utc) > next_run + timedelta(days=6)

    jobs.run_now(ids[0], app.state.http_transport)
    a = client.get(f"{API}/assessments/{ids[0]}").json()
    assert a["status"] == "completed", a

    notes = client.get(f"{API}/me/notifications").json()
    titles = [n["title"] for n in notes]
    assert "Alert: Acme Inc" in titles and "Scheduled check finished: Acme Inc" in titles
    alert = next(n for n in notes if n["kind"] == "alert")
    assert "fell from 99" in alert["body"] and alert["link"] == f"/results?assessment={ids[0]}"
    assert sent and sent[0][0] == "cs@aquarient.test" and "Alert" in sent[0][1]

    assert client.post(f"{API}/me/notifications/read", json={"ids": [alert["id"]]}).status_code == 204
    assert {n["id"]: n["read"] for n in client.get(f"{API}/me/notifications").json()}[alert["id"]] is True
    assert client.post(f"{API}/me/notifications/read", json={}).status_code == 204
    assert all(n["read"] for n in client.get(f"{API}/me/notifications").json())


def test_expired_connection_skips_schedule(client, sf):
    connect(client)
    client.put(f"{API}/schedules/{ORG_A}", json={"frequency": "daily"})
    with SessionLocal() as db:
        db.query(SalesforceConnectionRow).one().status = "expired"
        db.commit()
        assert scheduler.enqueue_due(db, now=datetime.now(timezone.utc) + timedelta(days=2)) == []
        assert db.query(NotificationRow).filter(NotificationRow.title == "Scheduled check skipped").count() == 1


def test_monthly_schedule_handles_short_months():
    assert scheduler.advance(datetime(2026, 1, 31, tzinfo=timezone.utc), "monthly") == datetime(2026, 2, 28, tzinfo=timezone.utc)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert scheduler.next_after(datetime(2026, 1, 20, tzinfo=timezone.utc), start, "weekly") == datetime(2026, 1, 22, tzinfo=timezone.utc)


def test_proposal_and_fix_plan(client, sf):
    connect(client)
    aid = client.post(f"{API}/assessments", json={"name": "DQ", "connectionId": client.get(f"{API}/salesforce/connection").json()["id"],
                                                  "scope": {"categoryIds": ["data-quality"], "areaIds": ["area-1", "area-2"]}}).json()["id"]
    p = client.get(f"{API}/assessments/{aid}/proposal", params={"rate": 200}).json()
    assert p["summary"] and p["lines"] and p["rate"] == 200
    assert round(sum(ln["hours"] for ln in p["lines"]), 1) == p["hours"] and p["cost"] == round(p["hours"] * 200, 2)
    assert [ph["id"] for ph in p["phases"]] == ["P1", "P2", "P3"]
    assert sum(ph["problems"] for ph in p["phases"]) == len(p["lines"])
    assert all(ln["phase"] == {"critical": "P1", "high": "P2"}.get(ln["severity"], "P3") for ln in p["lines"])

    f = next(x for x in client.get(f"{API}/assessments/{aid}/findings").json()["items"] if x["recordsAvailable"])
    plan = client.post(f"{API}/findings/{f['id']}/fix-plan").json()
    assert plan["steps"][0]["title"] == "See exactly what’s affected" and plan["effortHours"] > 0
    assert client.post(f"{API}/findings/nope/fix-plan").status_code == 404


def test_benchmarks_need_three_peers(client, sf):
    connect(client)
    now = datetime.now(timezone.utc)
    mine = _completed(ORG_A, "Acme Inc", 60, now)
    assert client.get(f"{API}/assessments/{mine}/benchmarks").json()["ready"] is False
    for i, s in enumerate((40, 50, 80)):
        _completed(f"00Dpeer{i}", f"Peer {i}", s, now - timedelta(days=1))
    b = client.get(f"{API}/assessments/{mine}/benchmarks").json()
    overall = b["lines"][0]
    assert b["ready"] and b["peers"] == 3 and overall["percentile"] == 67 and overall["median"] == 50


def test_branding_settings_validated(client):
    s = client.get(f"{API}/me/settings").json()
    assert s["branding"]["showAquarient"] is True and s["hourlyRate"] == 150
    ok = {**s, "branding": {"companyName": "Northwind Consulting", "accentColor": "#0a7cff", "logoDataUrl": "data:image/png;base64,iVBORw0KGgo="}}
    assert client.put(f"{API}/me/settings", json=ok).status_code == 200
    assert client.get(f"{API}/me/settings").json()["branding"]["companyName"] == "Northwind Consulting"
    bad = {**s, "branding": {"logoDataUrl": "javascript:alert(1)"}}
    assert client.put(f"{API}/me/settings", json=bad).status_code == 422
    assert client.put(f"{API}/me/settings", json={**s, "branding": {"accentColor": "red"}}).status_code == 422


def test_no_ai_settings_or_chat(client):
    assert "ai" not in client.get(f"{API}/me/settings").json()
    assert client.get(f"{API}/assistant/status").json() == {"mode": "guide", "model": None}
    assert client.post(f"{API}/assistant/chat", json={"messages": [{"role": "user", "content": "hi"}]}).status_code in (404, 405)
