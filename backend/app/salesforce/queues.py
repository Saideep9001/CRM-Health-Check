"""Leads waiting in a queue: how long each has been in its current queue, and the urgency that comes with it (read-only).

A Lead's time in its current queue runs from its last Lead Owner change in Lead History (the moment it entered that queue),
or from its Created Date when the owner never changed or Lead Owner changes aren't tracked.
"""
import re
from datetime import datetime, timezone

from .client import SalesforceClient
from .errors import SalesforceAuthExpired, SalesforceError

DAYS = (3, 5, 7)  # thresholds a person can pick ("in a queue for more than N days")
DEFAULT_DAYS = 3
COLUMN = {"name": "DaysInQueue", "label": "Days in Queue", "type": "int"}
URGENCY = {"name": "QueueUrgency", "label": "Urgency", "type": "string"}
_ID = re.compile(r"[A-Za-z0-9]{15,18}")


def urgency(days: int | None) -> str:
    """Urgency from days in the queue: Critical after 7 days, High after 5, Medium after 3, else Within 3 days."""
    if days is None:
        return "—"
    return "Critical" if days > 7 else "High" if days > 5 else "Medium" if days > 3 else "Within 3 days"


def longer_than(days: int, history: bool) -> list[str]:
    """SOQL conditions for "in its current queue for more than `days` days": created before then and, when Lead Owner changes
    are tracked, no owner change since (the last one is when it entered the queue)."""
    conds = [f"CreatedDate < LAST_N_DAYS:{int(days)}"]
    if history:
        conds.append(f"Id NOT IN (SELECT LeadId FROM LeadHistory WHERE Field = 'Owner' AND CreatedDate = LAST_N_DAYS:{int(days)})")
    return conds


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
    """Adds "Days in Queue" and its urgency to each record (in place) and returns the columns with them after the owner,
    named as the queue."""
    ids = [r["id"] for r in records if r.get("id") and _ID.fullmatch(r["id"])]
    changed = _last_owner_change(sf, ids) if ids else {}
    now = datetime.now(timezone.utc)
    for r in records:
        since = changed.get(r.get("id") or "") or _when(r["values"].get("CreatedDate"))
        days = max(0, (now - since).days) if since else None
        r["values"][COLUMN["name"]] = days
        r["values"][URGENCY["name"]] = urgency(days)
    out: list[dict] = []
    for c in columns:
        out.append({**c, "label": "Queue Name"} if c["name"] == "OwnerId" else c)
        if c["name"] == "OwnerId":
            out += [COLUMN, URGENCY]
    return out if COLUMN in out else out + [COLUMN, URGENCY]
