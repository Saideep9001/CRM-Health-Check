"""Health, current user, settings, notifications, reports, and (disabled) sign-in."""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import get_db
from ..deps import settings_dep
from ..engine.runner import EXECUTABLE_AREA_IDS
from ..models import UserPrefsRow
from ..schemas import ApiHealth, AppSettings, UserProfile, UserProfileUpdate

router = APIRouter(tags=["workspace"])


# ---------------- System ----------------


@router.get("/health", response_model=ApiHealth)
def health(settings: Settings = Depends(settings_dep)):
    # Areas the engine can run automatically (others show as "coming soon" in the UI).
    return ApiHealth(status="ok", version=settings.app_version, executable_area_ids=EXECUTABLE_AREA_IDS)


# ---------------- Current user (single local user until sign-in exists) ----------------


def _prefs(db: Session, settings: Settings) -> UserPrefsRow:
    row = db.get(UserPrefsRow, 1)
    if row is None:
        row = UserPrefsRow(
            id=1,
            profile={"id": "local-user", "name": settings.local_user_name, "email": settings.local_user_email, "title": None, "role": "Administrator"},
            settings=AppSettings().model_dump(by_alias=True),
        )
        db.add(row)
        db.commit()
    return row


@router.get("/me", response_model=UserProfile)
def me(db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    return UserProfile.model_validate(_prefs(db, settings).profile)


@router.patch("/me", response_model=UserProfile)
def update_me(body: UserProfileUpdate, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    row = _prefs(db, settings)
    profile = dict(row.profile)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "name" and not (value or "").strip():
            raise HTTPException(422, "Name is required.")
        profile[key] = value.strip() if isinstance(value, str) else value
    row.profile = profile
    db.commit()
    return UserProfile.model_validate(profile)


@router.get("/me/settings", response_model=AppSettings)
def get_settings(db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    return AppSettings.model_validate(_prefs(db, settings).settings)


@router.put("/me/settings", response_model=AppSettings)
def put_settings(body: AppSettings, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    row = _prefs(db, settings)
    row.settings = body.model_dump(by_alias=True)
    db.commit()
    return body


# ---------------- Reports ----------------


@router.post("/reports/export")
def export_report():
    raise HTTPException(501, "PDF reports aren’t available yet.")


# ---------------- Sign-in (not enabled yet; the app runs without sign-in) ----------------


@router.post("/auth/login")
@router.post("/auth/sso/start")
@router.post("/auth/password/forgot")
def auth_disabled():
    raise HTTPException(501, "Sign-in isn’t enabled on this server yet.")


@router.post("/auth/logout", status_code=204)
def logout():
    return Response(status_code=204)
