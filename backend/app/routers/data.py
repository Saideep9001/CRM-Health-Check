"""Read-only data explorer: browse the connected org's objects, fields and records."""
from collections.abc import Callable
from typing import Literal, TypeVar

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import get_db
from ..deps import http_dep, settings_dep
from ..salesforce import duplicates, empty_fields, explorer, field_check, finder, service
from ..salesforce.client import SalesforceClient
from ..salesforce.errors import SalesforceAuthExpired, SalesforceError
from ..schemas import FieldCheckRequest, FieldCheckResult, FieldValues, DataAnswer, DataAskRequest, DuplicateOptions, DuplicateRequest, DuplicateResult, EmptyField, EmptyRequest, EmptyResult, DataObject, DataObjectDetail, DataRecord, DataRecordPage, DataRelatedPage, DataSearchGroup

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


class RecordTypeFields(ApiModel):
    name: str
    id: str
    fields: list[str]  # on this record type's page layout


class RecordTypesResult(ApiModel):
    record_types: list[RecordTypeFields]  # empty when the object has no record types
    other: list[str]  # fields on no record type's layout
    fillable: list[str]  # fields people fill in (what the field cards count)
    own_custom: list[str]  # custom fields built in the org (not from packages)
    setup_links: dict[str, str] = {}  # field -> its page in Setup (Object Manager)


@router.get("/objects/{name}/record-types", response_model=RecordTypesResult)
def record_types(name: str, db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    """Each record type's fields (from its page layout), for the field cards' record type filter."""
    return _run(db, http, settings, lambda sf: explorer.record_type_fields(sf, name))


@router.get("/objects/{name}/records", response_model=DataRecordPage)
def records(
    name: str,
    fields: str | None = Query(None, max_length=4000, description="Comma-separated field API names"),
    q: str | None = Query(None, max_length=100),
    sort: str | None = Query(None, max_length=120),
    dir: Literal["asc", "desc"] = "desc",
    cursor: str | None = Query(None, max_length=200),
    ids: str | None = Query(None, max_length=4000, description="Comma-separated record Ids to show only those"),
    filters: str | None = Query(None, max_length=12000, description='JSON list of {"field","op","value"} filters'),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    cols = [f.strip() for f in fields.split(",") if f.strip()] if fields else None
    only = [i.strip() for i in ids.split(",") if i.strip()] if ids is not None else None
    return _run(db, http, settings, lambda sf: explorer.list_records(sf, name, cols, q, sort, dir, cursor, only, finder.parse_filters(filters)))


@router.get("/objects/{name}/values", response_model=FieldValues)
def field_values(
    name: str,
    field: str = Query(..., max_length=120),
    q: str | None = Query(None, max_length=100),
    filters: str | None = Query(None, max_length=12000),
    db: Session = Depends(get_db),
    http: httpx.Client = Depends(http_dep),
    settings: Settings = Depends(settings_dep),
):
    """The different values of one column with how many records have each, for a column filter."""
    return _run(db, http, settings, lambda sf: explorer.field_values(sf, name, field, q, finder.parse_filters(filters)))


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


# ---------------------------------------------------------------- duplicate finder

@router.get("/duplicates/options", response_model=DuplicateOptions)
def duplicate_options(object: str = Query(..., max_length=80), db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    """Fields that can be compared to find duplicates, and Salesforce's standard rule for the object (if any)."""
    def load(sf: SalesforceClient):
        fields = duplicates.matchable_fields(sf, object)
        labels = {f["name"]: f["label"] for f in fields}
        std = duplicates.STANDARD.get(object)
        return DuplicateOptions(
            object=object,
            fields=[{**f, "method": duplicates.KINDS[f["kind"]][0]} for f in fields],
            standard_rule=std["name"] if std else None,
            standard_groups=[[labels.get(f, f) for f in g] for g in std["groups"]] if std else [],
        )
    return _run(db, http, settings, load)


@router.post("/duplicates", response_model=DuplicateResult)
def find_duplicates(body: DuplicateRequest, db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    """Groups of duplicate records, by Salesforce's standard rule or by fields the person chose (read-only)."""
    return _run(db, http, settings, lambda sf: duplicates.find_duplicates(sf, body.object, body.fields, body.standard))


# ---------------------------------------------------------------- field check

@router.post("/fields/check", response_model=FieldCheckResult)
def check_fields(body: FieldCheckRequest, db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    """For each chosen field: empty values, duplicates and inconsistent spellings; plus duplicates on all of them (read-only)."""
    return _run(db, http, settings, lambda sf: field_check.check_fields(sf, body.object, body.fields))


# ---------------------------------------------------------------- empty fields

@router.get("/empty/options", response_model=list[EmptyField])
def empty_options(object: str = Query(..., max_length=80), db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    """Fields that can be checked for being empty."""
    return _run(db, http, settings, lambda sf: empty_fields.empty_options(sf, object))


@router.post("/empty", response_model=EmptyResult)
def find_empty(body: EmptyRequest, db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    """Records whose chosen fields are empty (any or all of them), 200 per page (read-only)."""
    return _run(db, http, settings, lambda sf: empty_fields.find_empty(sf, body.object, body.fields, body.match, body.cursor))


@router.get("/empty.csv")
def empty_csv(object: str = Query(..., max_length=80), fields: str = Query(..., max_length=2000), match: Literal["any", "all"] = "any",
              db: Session = Depends(get_db), http: httpx.Client = Depends(http_dep), settings: Settings = Depends(settings_dep)):
    """Download the records with empty fields (up to 10,000) as a spreadsheet."""
    import csv
    import io

    from fastapi import Response

    def collect(sf: SalesforceClient):
        where, chosen = empty_fields.where_empty(sf, object, fields.split(","), match)
        order = explorer._name_field(explorer._describe(sf, object))
        page = explorer.records_matching(sf, object, where, page_size=2000, columns=chosen, order=order)
        rows = list(page["records"])
        while page["next_cursor"] and len(rows) < 10_000:
            page = explorer.records_matching(sf, object, where, page["next_cursor"], page_size=2000, columns=chosen, order=order)
            rows += page["records"]
        return page["columns"], rows[:10_000], page["record_url_prefix"]

    columns, rows, prefix = _run(db, http, settings, collect)
    out = io.StringIO()
    out.write("\ufeff")  # so Excel opens accents correctly
    w = csv.writer(out)
    w.writerow([c["label"] for c in columns] + ["Salesforce link"])
    for r in rows:
        vals = r["values"]
        w.writerow([r["ref_names"].get(c["name"]) or ("" if vals.get(c["name"]) is None else vals.get(c["name"])) for c in columns]
                   + [f"{prefix}{r['id']}" if r.get("id") else ""])
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="empty-{object.lower()}-fields.csv"'})
