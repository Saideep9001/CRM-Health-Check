"""Read-only data explorer: browse the connected org's objects, fields and records."""
from collections.abc import Callable
from typing import Literal, TypeVar

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import get_db
from ..deps import http_dep, settings_dep
from ..salesforce import explorer, finder, service
from ..salesforce.client import SalesforceClient
from ..salesforce.errors import SalesforceAuthExpired, SalesforceError
from ..schemas import DataAnswer, DataAskRequest, DataObject, DataObjectDetail, DataRecord, DataRecordPage, DataRelatedPage, DataSearchGroup

router = APIRouter(prefix="/data", tags=["data"])

T = TypeVar("T")


def _run(db: Session, http: httpx.Client, settings: Settings, fn: Callable[[SalesforceClient], T]) -> T:
    """Call Salesforce and turn its failures into clear messages.

    424 (not 502) is used for Salesforce-side problems so the UI doesn't mistake them for our API being down.
    """
    try:
        sf = service.client_for(db, http, settings)
    except service.NotConnected:
        raise HTTPException(409, "Salesforce isn’t connected. Connect it first to see your data.")
    try:
        return fn(sf)
    except explorer.NotFound:
        raise HTTPException(404, "That object or record wasn’t found, or you don’t have access to it.")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except SalesforceAuthExpired as exc:
        service.mark_expired(db, str(exc))
        raise HTTPException(409, "Your Salesforce connection has timed out. Please reconnect.")
    except SalesforceError as exc:
        raise HTTPException(424, f"Salesforce couldn’t return this data. {exc}")
    except httpx.HTTPError:
        raise HTTPException(424, "Couldn’t reach Salesforce. Please try again.")


@router.get("/objects", response_model=list[DataObject])
def objects(db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    return _run(db, http, settings, explorer.list_objects)


@router.get("/objects/{name}", response_model=DataObjectDetail)
def object_detail(name: str, db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    return _run(db, http, settings, lambda sf: explorer.describe_object(sf, name))


@router.get("/objects/{name}/records", response_model=DataRecordPage)
def records(
    name: str,
    fields: str | None = Query(None, max_length=4000, description="Comma-separated field API names"),
    q: str | None = Query(None, max_length=100),
    sort: str | None = Query(None, max_length=120),
    dir: Literal["asc", "desc"] = "desc",
    cursor: str | None = Query(None, max_length=200),
    ids: str | None = Query(None, max_length=4000, description="Comma-separated record Ids to show only those"),
    filters: str | None = Query(None, max_length=6000, description='JSON list of {"field","op","value"} filters'),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    cols = [f.strip() for f in fields.split(",") if f.strip()] if fields else None
    only = [i.strip() for i in ids.split(",") if i.strip()] if ids is not None else None
    return _run(db, http, settings, lambda sf: explorer.list_records(sf, name, cols, q, sort, dir, cursor, only, finder.parse_filters(filters)))


@router.get("/search", response_model=list[DataSearchGroup])
def search(
    q: str = Query(..., max_length=100),
    objects: str | None = Query(None, max_length=2000, description="Comma-separated objects to search (default: the main ones)"),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    """Find records by name, email, phone or other text across many objects at once."""
    names = [o.strip() for o in objects.split(",") if o.strip()] if objects else None
    return _run(db, http, settings, lambda sf: finder.search_all(sf, q, names))


@router.post("/ask", response_model=DataAnswer)
def ask(req: DataAskRequest, db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    """Turn a plain-English question into filters on one object, with how many records match."""
    return _run(db, http, settings, lambda sf: finder.ask(sf, req.question, req.objects, req.context))


@router.get("/objects/{name}/records/{record_id}", response_model=DataRecord)
def record(name: str, record_id: str, db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    return _run(db, http, settings, lambda sf: explorer.get_record(sf, name, record_id))


@router.get("/objects/{name}/records/{record_id}/related/{relationship}", response_model=DataRelatedPage)
def related(name: str, record_id: str, relationship: str, db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    """One related list of a record, e.g. an Account's Contacts or Opportunities."""
    return _run(db, http, settings, lambda sf: explorer.related_records(sf, name, record_id, relationship))


@router.post("/refresh", status_code=204)
def refresh():
    """Forget cached object lists and field descriptions (e.g. after adding a custom field)."""
    explorer.clear_cache()
