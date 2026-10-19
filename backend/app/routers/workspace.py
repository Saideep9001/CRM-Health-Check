"""Health, workspace settings and report export. Sign-in and users live in users.py."""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import get_db
from ..deps import settings_dep
from ..engine.runner import EXECUTABLE_AREA_IDS
from ..models import UserPrefsRow
from ..auth import Principal, require_user
from ..schemas import ApiHealth, AppSettings

router = APIRouter(tags=["workspace"])


# ---------------- System ----------------


@router.get("/health", response_model=ApiHealth)
def health(settings: Settings = Depends(settings_dep)):
    # Areas the engine can run automatically (others show as "coming soon" in the UI).
    return ApiHealth(status="ok", version=settings.app_version, executable_area_ids=EXECUTABLE_AREA_IDS)


# ---------------- Settings (shared by the workspace) ----------------


WORKSPACE_FIELDS = ("branding", "hourlyRate", "currency")  # only admins change these


def _prefs(db: Session, settings: Settings) -> UserPrefsRow:
    row = db.get(UserPrefsRow, 1)
    if row is None:
        row = UserPrefsRow(id=1, profile={}, settings=AppSettings().model_dump(by_alias=True))
        db.add(row)
        db.commit()
    return row


@router.get("/me/settings", response_model=AppSettings)
def get_settings(_: Principal = Depends(require_user), db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    return AppSettings.model_validate(_prefs(db, settings).settings)


@router.put("/me/settings", response_model=AppSettings)
def put_settings(body: AppSettings, user: Principal = Depends(require_user), db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    row = _prefs(db, settings)
    new = body.model_dump(by_alias=True)
    old = AppSettings.model_validate(row.settings).model_dump(by_alias=True)
    if not user.is_admin and any(new[k] != old[k] for k in WORKSPACE_FIELDS):
        raise HTTPException(403, "Only admins can change report branding and proposal defaults.")
    row.settings = body.model_dump(by_alias=True)
    db.commit()
    return body


# ---------------- Reports ----------------


@router.post("/reports/export")
def export_report(_: Principal = Depends(require_user)):
    raise HTTPException(501, "PDF reports aren’t available yet.")

