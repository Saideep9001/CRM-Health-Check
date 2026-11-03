"""How long each listed Lead has sat in its queue, as a column worked out live (read-only).

A Lead's time in its queue runs from its last Lead Owner change in Lead History, or from its Created Date when the owner
never changed (or Lead Owner changes aren't tracked).
"""
import re
from datetime import datetime, timezone

from .client import SalesforceClient
from .errors import SalesforceAuthExpired, SalesforceError

COLUMN = {"name": "DaysInQueue", "label": "Days in Queue", "type": "int"}
_ID = re.compile(r"[A-Za-z0-9]{15,18}")


def _when(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00").replace("+0000", "+00:00")) if iso else None
    except ValueError:
        return None


def _last_owner_change(sf: SalesforceClient, ids: list[str]) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for i in range(0, len(ids), 300):
        chunk = ", ".join(f"'{x}'" for x in ids[i:i + 300])  # ids checked by _ID
        soql = f"SELECT LeadId, CreatedDate FROM LeadHistory WHERE Field = 'Owner' AND LeadId IN ({chunk}) ORDER BY CreatedDate DESC"
        try:
            for r in sf.query(soql, max_rows=10000).get("records", []):
                if (at := _when(r.get("CreatedDate"))) and r.get("LeadId") not in out:
                    out[r["LeadId"]] = at
        except SalesforceAuthExpired:
            raise
        except SalesforceError:
            return {}  # Lead History can't be read: every Lead counts from its Created Date
    return out


def add_days_in_queue(sf: SalesforceClient, columns: list[dict], records: list[dict]) -> list[dict]:
    """Adds "Days in Queue" to each record (in place) and returns the columns with it after the owner, named as the queue."""
    ids = [r["id"] for r in records if r.get("id") and _ID.fullmatch(r["id"])]
    changed = _last_owner_change(sf, ids) if ids else {}
    now = datetime.now(timezone.utc)
    for r in records:
        since = changed.get(r.get("id") or "") or _when(r["values"].get("CreatedDate"))
        r["values"][COLUMN["name"]] = max(0, (now - since).days) if since else None
    out: list[dict] = []
    for c in columns:
        out.append({**c, "label": "Queue Name"} if c["name"] == "OwnerId" else c)
        if c["name"] == "OwnerId":
            out.append(COLUMN)
    return out if COLUMN in out else out + [COLUMN]
