"""Help assistant endpoints. The assistant is a built-in guide plus fixed, read-only Salesforce lookups (no AI)."""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import get_db
from ..deps import http_dep, settings_dep
from ..salesforce import service
from ..salesforce.crm_queries import LOOKUPS, run_lookup
from ..salesforce.errors import SalesforceAuthExpired, SalesforceError
from ..schemas import AssistantStatus, CrmAnswer, CrmQueryRequest

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/status", response_model=AssistantStatus)
def status():
    return AssistantStatus(mode="guide", model=None)


@router.post("/crm-query", response_model=CrmAnswer)
def crm_query(req: CrmQueryRequest, db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    if req.query_id not in LOOKUPS:
        raise HTTPException(422, "Unknown question.")
    try:
        sf = service.client_for(db, http, settings)
    except service.NotConnected:
        raise HTTPException(409, "Salesforce isn’t connected. Connect it first to ask about your data.")
    try:
        return run_lookup(req.query_id, sf)
    except SalesforceAuthExpired as exc:
        service.mark_expired(db, str(exc))
        raise HTTPException(409, "Your Salesforce connection has timed out. Please reconnect.")
    except SalesforceError as exc:
        raise HTTPException(502, f"Salesforce couldn’t answer that. {exc}")
    except httpx.HTTPError:
        raise HTTPException(502, "Couldn’t reach Salesforce. Please try again.")
