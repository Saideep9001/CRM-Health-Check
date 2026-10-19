"""Database tables."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SalesforceConnectionRow(Base):
    """A connected Salesforce org. Several can be saved (a consultant's client portfolio); one is active at a time.
    Tokens are stored encrypted (see crypto.py)."""

    __tablename__ = "salesforce_connection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace: Mapped[str] = mapped_column(String(64), unique=True, default="default")
    status: Mapped[str] = mapped_column(String(16), default="connected")  # connected | expired | error
    environment: Mapped[str] = mapped_column(String(16))
    login_host: Mapped[str] = mapped_column(String(255))
    instance_url: Mapped[str] = mapped_column(String(255))
    org_id: Mapped[str | None] = mapped_column(String(32))
    organization_name: Mapped[str | None] = mapped_column(String(255))
    edition: Mapped[str | None] = mapped_column(String(64))
    connected_by: Mapped[str | None] = mapped_column(String(255))
    access_token_enc: Mapped[str] = mapped_column(Text)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    api_requests_max: Mapped[int | None] = mapped_column(Integer)
    api_requests_remaining: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class SalesforceAppRow(Base):
    """Connected App keys entered on the Connect Salesforce page. The secret is encrypted."""

    __tablename__ = "salesforce_app"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(256))
    client_secret_enc: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OAuthStateRow(Base):
    """One-time OAuth `state` + PKCE verifier, valid for 10 minutes."""

    __tablename__ = "oauth_state"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    code_verifier: Mapped[str] = mapped_column(String(128))
    environment: Mapped[str] = mapped_column(String(16))
    login_host: Mapped[str] = mapped_column(String(255))
    redirect_uri: Mapped[str] = mapped_column(String(512))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserPrefsRow(Base):
    """Local profile and settings (single local user until sign-in is enabled)."""

    __tablename__ = "user_prefs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)


class AssessmentRow(Base):
    """One health check run. `results` holds the scored areas once it finishes."""

    __tablename__ = "assessment"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    connection_id: Mapped[str] = mapped_column(String(64))
    organization_name: Mapped[str] = mapped_column(String(255), default="")
    org_id: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued | running | completed | failed | cancelled
    scope: Mapped[dict] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress: Mapped[int | None] = mapped_column(Integer)
    current_step: Mapped[str | None] = mapped_column(String(255))
    records_assessed: Mapped[int | None] = mapped_column(Integer)
    findings_count: Mapped[int | None] = mapped_column(Integer)
    overall_score: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    results: Mapped[dict | None] = mapped_column(JSON)
    # Job queue (see engine/jobs.py): which worker runs it, when it last checked in, and how many tries so far.
    worker_id: Mapped[str | None] = mapped_column(String(128))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class FindingRow(Base):
    """A problem found by a health check. Users can update status and notes."""

    __tablename__ = "finding"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(255))
    category_id: Mapped[str] = mapped_column(String(32))
    area_id: Mapped[str] = mapped_column(String(16))
    severity: Mapped[str] = mapped_column(String(16))
    priority: Mapped[str] = mapped_column(String(4))
    affected_records: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text)
    why_it_matters: Mapped[str] = mapped_column(Text)
    business_impact: Mapped[str] = mapped_column(Text)
    recommended_action: Mapped[str] = mapped_column(Text)
    sample_records_url: Mapped[str | None] = mapped_column(String(512))
    object_name: Mapped[str | None] = mapped_column(String(80))  # Salesforce object the problem is about
    # Which records are affected: the engine's own filter (never user input), used to list and export them.
    records_object: Mapped[str | None] = mapped_column(String(80))
    records_where: Mapped[str | None] = mapped_column(Text)
    value_at_risk: Mapped[float | None] = mapped_column(Float)  # e.g. total Amount of the deals involved
    fix_url: Mapped[str | None] = mapped_column(String(512))  # Salesforce page where it can be fixed
    # Same problem across checks: fingerprint = area + name + object. previous_affected is from the last check.
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    previous_affected: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="open")
    notes: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScanScheduleRow(Base):
    """Automatic health checks for one org (weekly, monthly…), with alert settings."""

    __tablename__ = "scan_schedule"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    frequency: Mapped[str] = mapped_column(String(16))  # daily | weekly | monthly
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    area_ids: Mapped[list | None] = mapped_column(JSON)  # None = every area
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_assessment_id: Mapped[str | None] = mapped_column(String(36))
    alert_email: Mapped[str | None] = mapped_column(String(255))
    score_drop: Mapped[int] = mapped_column(Integer, default=5, server_default="5")  # alert when the score falls this much
    alert_new_critical: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationRow(Base):
    """An in-app notification (e.g. a scheduled check finished, or the score dropped)."""

    __tablename__ = "notification"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    org_id: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))  # alert | info
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(512))
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class UserRow(Base):
    """A person who can sign in. Password is a salted scrypt hash."""

    __tablename__ = "app_user"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)  # stored lower-case
    name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str | None] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="consultant")  # admin | consultant | viewer
    all_orgs: Mapped[bool] = mapped_column(Boolean, default=False)  # admins always see every org
    org_ids: Mapped[list | None] = mapped_column(JSON)  # orgs this user may see when not all_orgs
    active_org_id: Mapped[str | None] = mapped_column(String(32))  # the org this user is working on
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionRow(Base):
    """A signed-in browser. The id is the SHA-256 of the cookie token (the token itself is never stored)."""

    __tablename__ = "user_session"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(255))
