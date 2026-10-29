"""Uploading CRM data from a CSV or Excel file, checked like a connected Salesforce org.

1. POST /uploads/preview (the file as the request body): its columns, the Salesforce field each one matches, a few rows.
2. POST /uploads/import: load it as an object (Account, Contact, Lead, Opportunity or another name) into a new upload
   or one made earlier. The upload is saved like an org (Client Portfolio) and becomes the active one, so
   Your Data and the Data Quality checks work on it.
"""
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..auth import Principal, ensure_org, require_editor
from ..db import get_db
from ..salesforce import explorer, local_org, service
from ..schemas import ApiModel

router = APIRouter(prefix="/uploads", tags=["uploads"])

MAX_BYTES = 50 * 1024 * 1024
STAGING = local_org.UPLOAD_DIR / "staging"


class UploadColumn(ApiModel):
    header: str
    field: str | None = None
    type: str
    filled: int
    sample: str


class StandardField(ApiModel):
    name: str
    label: str
    type: str


class UploadPreview(ApiModel):
    token: str
    filename: str
    object: str
    rows: int
    columns: list[UploadColumn]
    preview: list[dict[str, str]]
    standard_fields: list[StandardField]


class UploadImport(ApiModel):
    token: str
    object: str
    mapping: dict[str, str | None] = {}
    org_id: str | None = None  # add to this upload; none = a new upload
    name: str | None = None  # the new upload's name


class UploadedObject(ApiModel):
    name: str
    label: str
    plural: str
    filename: str | None = None
    rows: int
    loaded_at: str | None = None


class UploadResult(ApiModel):
    org_id: str
    name: str
    object: str
    rows: int
    objects: list[UploadedObject]


def _staged(token: str) -> tuple[Path, str]:
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        raise HTTPException(404, "This upload has expired. Choose the file again.")
    meta = STAGING / f"{token}.name"
    data = STAGING / f"{token}.bin"
    if not data.exists() or not meta.exists():
        raise HTTPException(404, "This upload has expired. Choose the file again.")
    return data, meta.read_text(encoding="utf-8")


def _read(data: Path, filename: str) -> tuple[list[str], list[list[str]]]:
    try:
        return local_org.read_table(filename, data.read_bytes())
    except local_org.UploadError as exc:
        raise HTTPException(422, str(exc)) from exc


def _preview(token: str, filename: str, obj: str, headers: list[str], rows: list[list[str]]) -> UploadPreview:
    s = local_org.summarize(headers, rows, obj)
    return UploadPreview(token=token, filename=filename, object=obj, rows=s["rows"], columns=s["columns"],
                         preview=s["preview"], standard_fields=s["standardFields"])


@router.post("/preview", response_model=UploadPreview)
async def preview(request: Request, filename: str = Query(min_length=1, max_length=255), object: str = Query("Account"),
                  _: Principal = Depends(require_editor)):
    """The file is the request body (no form encoding), so nothing extra is needed to receive it."""
    body = await request.body()
    if not body:
        raise HTTPException(422, "The file is empty.")
    if len(body) > MAX_BYTES:
        raise HTTPException(413, "The file is larger than 50 MB. Split it into smaller files.")
    name = Path(filename).name
    try:
        headers, rows = local_org.read_table(name, body)
    except local_org.UploadError as exc:
        raise HTTPException(422, str(exc)) from exc
    STAGING.mkdir(parents=True, exist_ok=True)
    for old in sorted(STAGING.glob("*.bin"), key=lambda p: p.stat().st_mtime)[:-20]:  # keep the last few only
        old.unlink(missing_ok=True)
        old.with_suffix(".name").unlink(missing_ok=True)
    token = uuid.uuid4().hex
    (STAGING / f"{token}.bin").write_bytes(body)
    (STAGING / f"{token}.name").write_text(name, encoding="utf-8")
    return _preview(token, name, object, headers, rows)


@router.get("/preview/{token}", response_model=UploadPreview)
def preview_again(token: str, object: str = Query("Account"), _: Principal = Depends(require_editor)):
    """The same file matched to another object."""
    data, name = _staged(token)
    headers, rows = _read(data, name)
    return _preview(token, name, object, headers, rows)


def _upload_row(db: Session, org_id: str):
    ensure_org(org_id)
    row = service.row_for_org(db, org_id)
    dataset = local_org.dataset_of(row.instance_url) if row else None
    if row is None or not dataset:
        raise HTTPException(404, "That upload no longer exists.")
    return row, dataset


@router.post("/import", response_model=UploadResult)
def import_file(body: UploadImport, db: Session = Depends(get_db), user: Principal = Depends(require_editor)):
    data, filename = _staged(body.token)
    headers, rows = _read(data, filename)
    obj = body.object.strip()
    if body.org_id:
        row, dataset = _upload_row(db, body.org_id)
        service.activate(db, row.org_id)
    else:
        name = (body.name or "").strip() or Path(filename).stem.replace("_", " ").strip() or "Uploaded data"
        row = service.create_upload(db, name[:120], user.name or user.email)
        dataset = local_org.dataset_of(row.instance_url)
    try:
        n = local_org.load_object(dataset, obj, filename, headers, rows, body.mapping)
    except local_org.UploadError as exc:
        if not body.org_id:  # nothing loaded into the new upload: don't leave an empty one behind
            service.disconnect(db, None, row.org_id)
            db.commit()
        raise HTTPException(422, str(exc)) from exc
    explorer.clear_cache()  # describe and counts change with the new file
    data.unlink(missing_ok=True)
    data.with_suffix(".name").unlink(missing_ok=True)
    return UploadResult(org_id=row.org_id, name=row.organization_name or "Uploaded data", object=obj, rows=n,
                        objects=[UploadedObject(**o) for o in local_org.objects(dataset)])


@router.get("/{org_id}/objects", response_model=list[UploadedObject])
def uploaded_objects(org_id: str, db: Session = Depends(get_db), _: Principal = Depends(require_editor)):
    _, dataset = _upload_row(db, org_id)
    return [UploadedObject(**o) for o in local_org.objects(dataset)]


@router.delete("/{org_id}/objects/{name}", status_code=204)
def remove_object(org_id: str, name: str, db: Session = Depends(get_db), _: Principal = Depends(require_editor)):
    _, dataset = _upload_row(db, org_id)
    local_org.remove_object(dataset, name)
    explorer.clear_cache()
