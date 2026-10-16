"""Salesforce Connected App keys.

Keys can be entered on the Connect Salesforce page (stored in the database, secret encrypted)
or set in backend/.env. Page-entered keys take priority. The secret is never returned to the browser.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Session

from .. import crypto
from ..config import Settings
from ..models import SalesforceAppRow

APP_ROW_ID = 1


@dataclass(frozen=True)
class AppCredentials:
    client_id: str
    client_secret: str
    source: Literal["ui", "env"]


def get_credentials(db: Session, settings: Settings) -> AppCredentials | None:
    row = db.get(SalesforceAppRow, APP_ROW_ID)
    if row is not None:
        secret = crypto.decrypt(row.client_secret_enc)
        if secret:
            return AppCredentials(row.client_id, secret, "ui")
    if settings.sf_client_id and settings.sf_client_secret:
        return AppCredentials(settings.sf_client_id, settings.sf_client_secret, "env")
    return None


def save_credentials(db: Session, client_id: str, client_secret: str) -> None:
    row = db.get(SalesforceAppRow, APP_ROW_ID)
    if row is None:
        row = SalesforceAppRow(id=APP_ROW_ID, client_id=client_id, client_secret_enc="")
        db.add(row)
    row.client_id = client_id
    row.client_secret_enc = crypto.encrypt(client_secret) or ""
    row.updated_at = datetime.now(timezone.utc)
    db.commit()


def clear_credentials(db: Session) -> None:
    row = db.get(SalesforceAppRow, APP_ROW_ID)
    if row is not None:
        db.delete(row)
        db.commit()


def mask(client_id: str) -> str:
    """Show just enough of the key to recognise it, e.g. 3MVG…a1b2."""
    return client_id if len(client_id) <= 10 else f"{client_id[:4]}…{client_id[-4:]}"


def updated_at(db: Session) -> datetime | None:
    row = db.get(SalesforceAppRow, APP_ROW_ID)
    if row is None:
        return None
    dt = row.updated_at
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
