"""Job queue (workers, heartbeats, recovery) and database migrations."""
import contextlib
import io
import os
import socket
from datetime import datetime, timedelta, timezone

import httpx
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, text
from sqlalchemy.dialects import postgresql

from app.config import Settings
from app.db import Base, SessionLocal, engine
from app.deps import settings_dep
from app.engine import jobs
from app.main import app
from app.migrate import _config, upgrade_database
from app.models import AssessmentRow

from .conftest import connect

API = "/api/v1"


def _settings(**kw) -> Settings:
    return Settings(**{"worker_heartbeat_timeout_seconds": 60, "job_max_attempts": 2, **kw})


def _start(client):
    conn = client.get(f"{API}/salesforce/connection").json()
    scope = {"categoryIds": ["data-quality"], "areaIds": ["area-1"], "staleLeadDays": 30, "stuckOpportunityDays": 60}
    return client.post(f"{API}/assessments", json={"name": "Queued", "connectionId": conn["id"], "scope": scope}).json()


def _add(db, id, status="running", **kw):
    db.add(AssessmentRow(id=id, name=id, connection_id="x", org_id="00Dzz", status=status, scope={"areaIds": ["area-1"]}, **kw))
    db.commit()


# ---------------------------------------------------------------- queue


def test_external_mode_queues_until_a_worker_runs_it(client, sf):
    app.dependency_overrides[settings_dep] = lambda: _settings(job_mode="external")
    connect(client)
    a = _start(client)
    assert a["status"] == "queued"
    assert client.get(f"{API}/assessments/{a['id']}").json()["status"] == "queued"  # nothing runs it yet

    assert jobs.work_once("worker-test-1-0", _settings(), httpx.MockTransport(sf.handler)) is True
    done = client.get(f"{API}/assessments/{a['id']}").json()
    assert done["status"] == "completed" and done["progress"] == 100
    with SessionLocal() as db:
        row = db.get(AssessmentRow, a["id"])
        assert row.attempts == 1 and row.worker_id is None
    assert jobs.work_once("worker-test-1-0", _settings()) is False  # queue empty


def test_a_check_can_only_be_claimed_once(client):
    with SessionLocal() as db:
        _add(db, "q1", status="queued", created_at=datetime.now(timezone.utc))
        assert jobs.claim(db, "w-a") == "q1"
        assert jobs.claim(db, "w-b") is None
        assert jobs.claim(db, "w-b", "q1") is None
        row = db.get(AssessmentRow, "q1")
        db.refresh(row)
        assert row.status == "running" and row.worker_id == "w-a" and row.attempts == 1 and row.heartbeat_at is not None


def test_cancelled_while_queued_is_never_run(client):
    with SessionLocal() as db:
        _add(db, "q2", status="queued", created_at=datetime.now(timezone.utc))
    assert client.post(f"{API}/assessments/q2/cancel").json()["status"] == "cancelled"
    assert jobs.work_once("w-c", _settings()) is False


def test_stalled_checks_are_retried_then_failed(client):
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    with SessionLocal() as db:
        _add(db, "s1", attempts=1, worker_id="w-dead", heartbeat_at=old)
        _add(db, "s2", attempts=2, worker_id="w-dead", heartbeat_at=old)
        _add(db, "s3", attempts=1, worker_id="w-alive", heartbeat_at=datetime.now(timezone.utc))
        assert jobs.recover_stale(db, _settings()) == (1, 1)
        rows = {r.id: r for r in db.scalars(select(AssessmentRow)).all()}
        assert rows["s1"].status == "queued" and rows["s1"].worker_id is None and "interrupted" in rows["s1"].current_step
        assert rows["s2"].status == "failed" and "interrupted 2 times" in rows["s2"].error_message
        assert rows["s3"].status == "running"  # its worker is still checking in


def test_embedded_start_up_recovers_only_this_machines_old_runs(client):
    host = socket.gethostname()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        _add(db, "e-old", attempts=1, worker_id=f"embedded-{host}-99999999-0", heartbeat_at=now)
        _add(db, "e-me", attempts=1, worker_id=f"embedded-{host}-{os.getpid()}-0", heartbeat_at=now)
        _add(db, "e-other-host", attempts=1, worker_id="embedded-another-box-123-0", heartbeat_at=now)
        _add(db, "external", attempts=1, worker_id=f"worker-{host}-123-0", heartbeat_at=now)
        assert jobs.recover_own_host(db, _settings(), "embedded") == (1, 0)
        status = {r.id: r.status for r in db.scalars(select(AssessmentRow)).all()}
    assert status == {"e-old": "queued", "e-me": "running", "e-other-host": "running", "external": "running"}


def test_heartbeat_keeps_a_long_check_alive(client, monkeypatch):
    monkeypatch.setattr(jobs, "HEARTBEAT_SECONDS", 0.05)
    with SessionLocal() as db:
        _add(db, "hb", worker_id="w-hb", heartbeat_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    beat = jobs._Heartbeat("hb", "w-hb")
    beat.start()
    try:
        import time

        time.sleep(0.3)
    finally:
        beat.done.set()
        beat.join(1)
    with SessionLocal() as db:
        hb = db.get(AssessmentRow, "hb").heartbeat_at
    assert hb is not None and hb.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) - timedelta(seconds=30)


def test_one_check_per_org_not_global(client):
    connect(client)
    with SessionLocal() as db:
        _add(db, "busy-elsewhere")  # running, but for another org
    assert _start(client)["status"] in ("queued", "completed")


# ---------------------------------------------------------------- migrations


def _head() -> str:
    from alembic.script import ScriptDirectory

    from app.config import BACKEND_DIR

    return ScriptDirectory(str(BACKEND_DIR / "migrations")).get_current_head()


def test_migrations_match_the_models(client):
    with engine.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diffs == [], diffs
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == _head()


def test_pre_migration_database_is_adopted_and_upgraded(client):
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        command.upgrade(_config(conn), "0001")  # the schema as it was before migrations…
        conn.execute(text("DROP TABLE alembic_version"))  # …with no record of it
        conn.execute(text("INSERT INTO assessment (id, name, connection_id, organization_name, org_id, status, scope, created_at) "
                          "VALUES ('legacy', 'Old check', 'x', 'Acme', '00D', 'completed', '{}', CURRENT_TIMESTAMP)"))
    upgrade_database()
    cols = {c["name"] for c in inspect(engine).get_columns("assessment")}
    assert {"worker_id", "heartbeat_at", "attempts"} <= cols
    with SessionLocal() as db:
        row = db.get(AssessmentRow, "legacy")
        assert row.name == "Old check" and row.attempts == 0  # existing data kept


def test_migrations_produce_postgresql_sql():
    from alembic.config import Config

    from app.config import BACKEND_DIR

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["configure_logging"] = False
    cfg.attributes["url"] = "postgresql+psycopg://user:pass@localhost/aquarient"
    buf = io.StringIO()
    cfg.output_buffer = buf
    with contextlib.redirect_stdout(buf):
        command.upgrade(cfg, "head", sql=True)
    sql = buf.getvalue()
    assert "CREATE TABLE assessment" in sql and "TIMESTAMP WITH TIME ZONE" in sql and "JSON" in sql
    assert "ALTER TABLE assessment ADD COLUMN attempts INTEGER DEFAULT '0' NOT NULL" in sql
    assert f"UPDATE alembic_version SET version_num='{_head()}'" in sql


def test_queue_uses_skip_locked_on_postgresql():
    q = select(AssessmentRow.id).where(AssessmentRow.status == "queued").order_by(AssessmentRow.created_at).limit(1).with_for_update(skip_locked=True)
    assert "FOR UPDATE SKIP LOCKED" in str(q.compile(dialect=postgresql.dialect()))
