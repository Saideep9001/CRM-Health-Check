"""Reps with No Activities Logged Recently, read live from Salesforce (read-only).

Reps: active, standard users who own at least one open Opportunity or open Lead (bots, integration, API-only, automated and
Chatter users left out), with their Profile, Email and Title from Salesforce. Activity: what each of them logged in the last
N days, by type: Emails (Tasks whose Task Subtype is Email: logged emails), Tasks (the other Tasks) and Events, each with
how many and the latest one. A rep counts as quiet for a type when they logged none of it.
"""
import re
from datetime import date, timedelta

from .client import SalesforceClient
from .errors import SalesforceAuthExpired, SalesforceError

DAYS = (7, 14, 30, 90)  # the periods the card offers
DEFAULT_DAYS = 30
BOT_NAME = re.compile(r"integration|automated|einstein|agentforce|\bbot\b", re.I)
NON_REP_PROFILE = re.compile(r"integration|api only|automated process|chatter", re.I)
TYPES = ("email", "event", "task")
SAFE_USER = re.compile(r"005[A-Za-z0-9]{12}([A-Za-z0-9]{3})?")


def _query(sf: SalesforceClient, soql: str) -> list[dict] | None:
    try:
        return sf.query(soql).get("records", [])
    except SalesforceAuthExpired:
        raise
    except SalesforceError:
        return None


def reps(sf: SalesforceClient) -> list[dict]:
    """Active people who own open deals or leads, with their Profile, Email and Title."""
    owners: set[str] = set()
    for obj, cond in (("Opportunity", "IsClosed = false"), ("Lead", "IsConverted = false")):
        for r in _query(sf, f"SELECT OwnerId o, COUNT(Id) c FROM {obj} WHERE {cond} GROUP BY OwnerId LIMIT 2000") or []:
            if SAFE_USER.fullmatch(str(r.get("o") or "")):
                owners.add(r["o"])
    out = []
    ids = sorted(owners)
    for i in range(0, len(ids), 200):
        chunk = ", ".join(f"'{x}'" for x in ids[i:i + 200])
        for u in _query(sf, "SELECT Id, Name, Email, Title, UserType, Profile.Name, LastLoginDate FROM User "
                            f"WHERE IsActive = true AND Id IN ({chunk})") or []:
            profile = (u.get("Profile") or {}).get("Name") or ""
            if u.get("UserType", "Standard") == "Standard" and not BOT_NAME.search(u.get("Name") or "") and not NON_REP_PROFILE.search(profile):
                out.append({"id": u["Id"], "name": u.get("Name") or u["Id"], "profile": profile or None, "email": u.get("Email"),
                            "title": u.get("Title"), "lastLogin": (u.get("LastLoginDate") or "")[:10] or None})
    return sorted(out, key=lambda r: r["name"].lower())


def window(days: int = DEFAULT_DAYS, start: date | None = None, end: date | None = None) -> str:
    """The CreatedDate condition: the last `days` days, or between two dates (both included)."""
    if start or end:
        if not (start and end) or start > end or start > date.today():
            raise ValueError("Pick a From date on or before the To date, and not in the future.")
        return f"CreatedDate >= {start.isoformat()}T00:00:00Z AND CreatedDate < {(end + timedelta(days=1)).isoformat()}T00:00:00Z"
    if days not in DAYS:
        raise ValueError("Pick 7, 14, 30 or 90 days.")
    return f"CreatedDate = LAST_N_DAYS:{days}"


def _by_owner(sf: SalesforceClient, obj: str, when: str, extra: str = "") -> dict[str, tuple[int, str | None]] | None:
    rows = _query(sf, f"SELECT OwnerId o, COUNT(Id) c, MAX(CreatedDate) m FROM {obj} WHERE {when}{extra} "
                      "GROUP BY OwnerId LIMIT 2000")
    return None if rows is None else {str(r.get("o")): (int(r.get("c") or 0), (r.get("m") or "")[:10] or None) for r in rows}


def rep_activity(sf: SalesforceClient, days: int = DEFAULT_DAYS, start: date | None = None, end: date | None = None) -> dict:
    """Each rep with how many Emails, Events and Tasks they logged in the last `days` days, or between two dates (and the
    latest date), quietest first."""
    when = window(days, start, end)
    people = reps(sf)
    emails = _by_owner(sf, "Task", when, " AND TaskSubtype = 'Email'")  # None: this org has no Task Subtype
    tasks = _by_owner(sf, "Task", when, " AND TaskSubtype != 'Email'" if emails is not None else "") or {}
    events = _by_owner(sf, "Event", when) or {}
    available = {"email": emails is not None, "event": True, "task": True}
    emails = emails or {}
    for r in people:
        found = {"email": emails.get(r["id"]), "event": events.get(r["id"]), "task": tasks.get(r["id"])}
        r["counts"] = {t: (found[t] or (0, None))[0] for t in TYPES}
        dates = [d for t in TYPES if found[t] and (d := found[t][1])]
        r["lastActivity"] = max(dates) if dates else None
    people.sort(key=lambda r: (sum(r["counts"].values()), r["name"].lower()))  # nothing logged first
    return {"days": None if start else days, "from": start.isoformat() if start else None, "to": end.isoformat() if end else None,
            "available": available, "reps": people,
            "quiet": {t: sum(1 for r in people if not r["counts"][t]) for t in TYPES}
            | {"all": sum(1 for r in people if not any(r["counts"].values()))}}
