"""Salesforce connection lifecycle: start sign-in, finish sign-in, check, disconnect.

Several orgs can be saved (a consultant's clients). One is *active*: the data explorer, new checks and the
dashboard use it. Scheduled checks use the connection of the org they belong to.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import crypto
from ..config import Settings
from ..models import OAuthStateRow, SalesforceConnectionRow
from ..schemas import OAuthCallbackRequest, OAuthStartRequest, OAuthStartResponse, SalesforceConnection
from . import oauth
from .app_config import get_credentials
from .client import SalesforceClient
from .errors import SalesforceAuthExpired, SalesforceError

WORKSPACE = "default"
STATE_TTL = timedelta(minutes=10)


class NotConfigured(Exception):
    pass


class NotConnected(Exception):
    pass


def _utc(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; treat them as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_row(db: Session) -> SalesforceConnectionRow | None:
    """The active org's connection (or the most recently connected one if none is marked active)."""
    q = select(SalesforceConnectionRow).order_by(SalesforceConnectionRow.active.desc(), SalesforceConnectionRow.connected_at.desc())
    return db.scalars(q.limit(1)).first()


def all_rows(db: Session) -> list[SalesforceConnectionRow]:
    return list(db.scalars(select(SalesforceConnectionRow).order_by(SalesforceConnectionRow.organization_name)))


def row_for_org(db: Session, org_id: str | None) -> SalesforceConnectionRow | None:
    if not org_id:
        return None
    return db.scalars(select(SalesforceConnectionRow).where(SalesforceConnectionRow.org_id == org_id).limit(1)).first()


def activate(db: Session, org_id: str) -> SalesforceConnectionRow:
    row = row_for_org(db, org_id)
    if row is None:
        raise NotConnected()
    for other in all_rows(db):
        other.active = other.id == row.id
    db.commit()
    return row


def to_schema(row: SalesforceConnectionRow | None, settings: Settings) -> SalesforceConnection:
    if row is None:
        return SalesforceConnection(status="disconnected")
    return SalesforceConnection(
        id=row.org_id or str(row.id),
        status=row.status,  # type: ignore[arg-type]
        environment=row.environment,  # type: ignore[arg-type]
        organization_name=row.organization_name,
        org_id=row.org_id,
        instance_url=row.instance_url,
        edition=row.edition,
        api_version=settings.sf_api_version,
        connected_by=row.connected_by,
        connected_at=_utc(row.connected_at),
        last_checked_at=_utc(row.last_checked_at),
        api_requests_max=row.api_requests_max,
        api_requests_remaining=row.api_requests_remaining,
        error_message=row.error_message,
    )


def _validate_redirect(redirect_uri: str, settings: Settings) -> None:
    # Only our own callback page may receive authorization codes.
    if redirect_uri != settings.oauth_callback_url:
        raise ValueError(f"Redirect address not allowed. Expected {settings.oauth_callback_url}.")


def start_oauth(db: Session, req: OAuthStartRequest, settings: Settings) -> OAuthStartResponse:
    creds = get_credentials(db, settings)
    if creds is None:
        raise NotConfigured()
    _validate_redirect(req.redirect_uri, settings)
    login_host = oauth.login_host_for(req.environment, req.my_domain)

    # Clean up expired states, then store a fresh one-time state + PKCE verifier.
    db.execute(delete(OAuthStateRow).where(OAuthStateRow.expires_at < _now()))
    state = oauth.new_state()
    verifier, challenge = oauth.new_pkce()
    db.add(OAuthStateRow(state=state, code_verifier=verifier, environment=req.environment, login_host=login_host, redirect_uri=req.redirect_uri, expires_at=_now() + STATE_TTL))
    db.commit()

    url = oauth.authorize_url(
        login_host=login_host,
        client_id=creds.client_id,
        redirect_uri=req.redirect_uri,
        scopes=settings.sf_scopes,
        state=state,
        code_challenge=challenge,
    )
    return OAuthStartResponse(authorization_url=url, state=state)


def complete_oauth(db: Session, http: httpx.Client, req: OAuthCallbackRequest, settings: Settings) -> SalesforceConnection:
    creds = get_credentials(db, settings)
    if creds is None:
        raise NotConfigured()
    pending = db.get(OAuthStateRow, req.state)
    if pending is not None:
        db.delete(pending)  # one-time use, even if the rest fails
        db.commit()
    if pending is None or (_utc(pending.expires_at) or _now()) < _now() or pending.redirect_uri != req.redirect_uri:
        raise ValueError("This sign-in link has expired or was already used. Please connect again.")

    tokens = oauth.exchange_code(
        http,
        login_host=pending.login_host,
        client_id=creds.client_id,
        client_secret=creds.client_secret,
        code=req.code,
        code_verifier=pending.code_verifier,
        redirect_uri=pending.redirect_uri,
    )

    for other in all_rows(db):
        other.active = False  # the newly connected org becomes the active one
    row = SalesforceConnectionRow(
        workspace=f"pending-{uuid.uuid4()}",
        active=True,
        status="connected",
        environment=pending.environment,
        login_host=pending.login_host,
        instance_url=tokens.instance_url,
        access_token_enc=crypto.encrypt(tokens.access_token),
        refresh_token_enc=crypto.encrypt(tokens.refresh_token),
        connected_at=_now(),
    )
    db.add(row)
    db.commit()

    # Fill in org details. A failure here keeps the connection but records the problem.
    try:
        if tokens.identity_url:
            ident = oauth.fetch_identity(http, tokens.identity_url, tokens.access_token)
            row.org_id = ident.get("organization_id")
            row.connected_by = ident.get("display_name") or ident.get("username")
            # Reconnecting an org that's already saved replaces its old connection.
            for old in all_rows(db):
                if old.id != row.id and old.org_id and old.org_id == row.org_id:
                    db.delete(old)
            db.flush()
            row.workspace = f"org-{row.org_id}" if row.org_id else row.workspace
        sf = SalesforceClient(http, row, settings, creds, db.commit)
        org = sf.query("SELECT Name, OrganizationType FROM Organization LIMIT 1").get("records", [])
        if org:
            row.organization_name = org[0].get("Name")
            row.edition = org[0].get("OrganizationType")
        _refresh_limits(sf, row)
    except SalesforceError as exc:
        row.status = "error"
        row.error_message = f"Connected, but reading org details failed: {exc}"
    db.commit()
    return to_schema(row, settings)


def _refresh_limits(sf: SalesforceClient, row: SalesforceConnectionRow) -> None:
    daily = sf.limits().get("DailyApiRequests") or {}
    row.api_requests_max = daily.get("Max")
    row.api_requests_remaining = daily.get("Remaining")
    row.last_checked_at = _now()
    row.status = "connected"
    row.error_message = None


def client_for(db: Session, http: httpx.Client, settings: Settings, org_id: str | None = None) -> SalesforceClient:
    """A client for `org_id`'s saved connection, or for the active org."""
    row = row_for_org(db, org_id) if org_id else get_row(db)
    if row is None or row.status == "expired":
        raise NotConnected()
    return SalesforceClient(http, row, settings, get_credentials(db, settings), db.commit)


def check(db: Session, http: httpx.Client, settings: Settings, org_id: str | None = None) -> SalesforceConnection:
    row = row_for_org(db, org_id) if org_id else get_row(db)
    if row is None:
        return to_schema(None, settings)
    try:
        _refresh_limits(SalesforceClient(http, row, settings, get_credentials(db, settings), db.commit), row)
    except SalesforceAuthExpired as exc:
        row.status, row.error_message, row.last_checked_at = "expired", str(exc), _now()
    except SalesforceError as exc:
        row.status, row.error_message, row.last_checked_at = "error", str(exc), _now()
    except httpx.HTTPError:
        row.status, row.error_message, row.last_checked_at = "error", "Couldn’t reach Salesforce. Check your internet connection.", _now()
    db.commit()
    return to_schema(row, settings)


def mark_expired(db: Session, message: str, org_id: str | None = None) -> None:
    row = row_for_org(db, org_id) if org_id else get_row(db)
    if row is not None:
        row.status, row.error_message = "expired", message
        db.commit()


def disconnect_all(db: Session, http: httpx.Client) -> None:
    for row in all_rows(db):
        disconnect(db, http, row.org_id) if row.org_id else (db.delete(row), db.commit())


def disconnect(db: Session, http: httpx.Client, org_id: str | None = None) -> None:
    """Forget an org's connection (the active one by default) and revoke its tokens. Another saved org becomes active."""
    row = row_for_org(db, org_id) if org_id else get_row(db)
    if row is None:
        return
    was_active = row.active
    try:
        token = crypto.decrypt(row.refresh_token_enc) or crypto.decrypt(row.access_token_enc)
        if token:
            oauth.revoke(http, login_host=row.login_host, token=token)
    except RuntimeError:
        pass  # undecryptable tokens: nothing to revoke, just forget them
    db.delete(row)
    db.flush()
    if was_active:
        rest = sorted(all_rows(db), key=lambda r: _utc(r.connected_at) or _now(), reverse=True)
        if rest:
            rest[0].active = True
    db.commit()
    from . import explorer  # local import: explorer depends on the client module

    explorer.clear_cache()
