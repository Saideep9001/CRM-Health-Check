"""Salesforce connection endpoints (see docs/API_CONTRACT.md → Salesforce connection)."""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from .. import org_data
from ..auth import Principal, require_admin, require_editor
from ..config import Settings
from ..db import get_db
from ..deps import http_dep, settings_dep
from ..salesforce import app_config, service, snapshot
from ..salesforce.errors import SalesforceAuthExpired, SalesforceError
from ..schemas import (
    OAuthCallbackRequest,
    OAuthStartRequest,
    OAuthStartResponse,
    SalesforceAppConfig,
    SalesforceAppUpdate,
    ConnectionSnapshot,
    SalesforceConnection,
)

router = APIRouter(prefix="/salesforce", tags=["salesforce"])

NOT_CONFIGURED = "Salesforce app keys aren’t set up yet. Add your Consumer Key and Secret under “Salesforce app setup” on this page."


# ---------------- Connected App keys (entered on the Connect Salesforce page) ----------------


def _describe_app(db: Session, settings: Settings) -> SalesforceAppConfig:
    creds = app_config.get_credentials(db, settings)
    return SalesforceAppConfig(
        configured=creds is not None,
        source=creds.source if creds else None,
        client_id_preview=app_config.mask(creds.client_id) if creds else None,
        callback_url=settings.oauth_callback_url,
        updated_at=app_config.updated_at(db) if creds and creds.source == "ui" else None,
    )


@router.get("/app", response_model=SalesforceAppConfig)
def get_app(db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    return _describe_app(db, settings)


@router.put("/app", response_model=SalesforceAppConfig)
def put_app(body: SalesforceAppUpdate, _: Principal = Depends(require_admin), db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    current = app_config.get_credentials(db, settings)
    client_id, secret = body.client_id.strip(), body.client_secret.strip()
    # Tokens belong to the app that issued them: switching apps ends the current connection.
    if current is not None and current.client_id != client_id:
        service.disconnect_all(db, http)  # new app keys invalidate every org's tokens
    app_config.save_credentials(db, client_id, secret)
    return _describe_app(db, settings)


@router.delete("/app", response_model=SalesforceAppConfig)
def delete_app(_: Principal = Depends(require_admin), db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    before = app_config.get_credentials(db, settings)
    app_config.clear_credentials(db)
    after = app_config.get_credentials(db, settings)
    if before is not None and (after is None or after.client_id != before.client_id):
        service.disconnect_all(db, http)  # new app keys invalidate every org's tokens
    return _describe_app(db, settings)


@router.get("/connection", response_model=SalesforceConnection)
def get_connection(db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    return service.to_schema(service.get_row(db), settings)


@router.get("/connection/snapshot", response_model=ConnectionSnapshot)
def connection_snapshot(db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    """Live, read-only facts about the active org: limits, users, record counts and response time."""
    try:
        sf = service.client_for(db, http, settings)
    except service.NotConnected:
        raise HTTPException(409, "Salesforce isn’t connected.")
    try:
        return snapshot.snapshot(sf)
    except SalesforceAuthExpired as exc:
        service.mark_expired(db, str(exc))
        raise HTTPException(409, "Your Salesforce connection has timed out. Please reconnect.")
    except SalesforceError as exc:
        raise HTTPException(424, f"Salesforce couldn’t answer. {exc}")
    except httpx.HTTPError:
        raise HTTPException(424, "Couldn’t reach Salesforce. Please try again.")


@router.post("/oauth/start", response_model=OAuthStartResponse)
def start(req: OAuthStartRequest, _: Principal = Depends(require_editor), db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    try:
        return service.start_oauth(db, req, settings)
    except service.NotConfigured:
        raise HTTPException(501, NOT_CONFIGURED)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/oauth/callback", response_model=SalesforceConnection)
def callback(req: OAuthCallbackRequest, _: Principal = Depends(require_editor), db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    try:
        return service.complete_oauth(db, http, req, settings)
    except service.NotConfigured:
        raise HTTPException(501, NOT_CONFIGURED)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except SalesforceError as exc:
        raise HTTPException(400, str(exc))
    except httpx.HTTPError:
        raise HTTPException(502, "Couldn’t reach Salesforce. Please try again.")


@router.post("/connection/check", response_model=SalesforceConnection)
def check(db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    return service.check(db, http, settings)


@router.delete("/connection", status_code=204)
def disconnect(delete_results: bool = Query(False, alias="deleteResults"), me_: Principal = Depends(require_admin),
               db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep)):
    """Disconnect the active org. Its past checks are kept unless `deleteResults=true` (permanent)."""
    row = service.get_row(db)
    if row is not None and row.org_id:
        org_data.disconnect_org(db, http, row.org_id, delete_results=delete_results, actor=me_)
    elif row is not None:
        service.disconnect(db, http)
    return Response(status_code=204)
