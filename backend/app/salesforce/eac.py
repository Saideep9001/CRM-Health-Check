"""Einstein Activity Capture (EAC) health, read live from Salesforce (read-only), and only what Salesforce's APIs expose.

- System status: the org's EAC settings (Metadata API EACSettings), each flag as Salesforce has it. The Master, Email,
  Calendar and Contact tiles are the flags whose names say so; a tile with no such flag is "Not available".
- Users: everyone assigned EAC, by a permission set whose name or label says "Activity Capture" or a permission set
  licence named so. Each is checked on what Salesforce knows about the user: deactivated, never logged in, or not logged
  in for 30+ days. Salesforce's APIs don't show a user's EAC mailbox connection (expired token, pending authentication),
  so that isn't claimed here.
- Pipeline: Activity Metrics updated (when the org has them), and tasks and events the EAC users logged, in the last 7
  and 30 days. The emails EAC captures are stored outside Salesforce, so they can't be counted.
"""
import re
import xml.etree.ElementTree as ET

from .client import SalesforceClient
from .errors import SalesforceAuthExpired, SalesforceError

NS = {"m": "http://soap.sforce.com/2006/04/metadata"}
SAFE_ID = re.compile(r"005[A-Za-z0-9]{12}([A-Za-z0-9]{3})?")
STALE_LOGIN_DAYS = 30
EAC_LABEL = "%Activity Capture%"

# the System status tiles: which EAC setting each one is (by the setting's API name)
TILES = [
    ("master", "Master status", re.compile(r"^enable(EAC|ActivityCapture)(ForEveryone)?$|EACForEveryone", re.I)),
    ("email", "Email sync", re.compile(r"email", re.I)),
    ("calendar", "Calendar sync", re.compile(r"event|calendar", re.I)),
    ("contact", "Contact sync", re.compile(r"contact", re.I)),
]


def _try(fn, default=None):
    try:
        return fn()
    except SalesforceAuthExpired:
        raise
    except (SalesforceError, ET.ParseError, KeyError, ValueError):
        return default


def _label(name: str) -> str:
    """enableEACForEveryone -> "Enable EAC for everyone"."""
    words = re.findall(r"[A-Z]{2,}(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|\d+", name)
    return " ".join(w if w.isupper() and len(w) > 1 else w.lower() for w in words).capitalize() if words else name


def settings(sf: SalesforceClient) -> dict:
    """The org's EAC settings: each on/off flag, from the Metadata API."""
    if not hasattr(sf, "read_metadata"):
        return {"available": False, "flags": [], "error": "The Metadata API isn’t available for this org."}
    try:
        xml = sf.read_metadata("EACSettings", ["EAC"])
        rec = next(ET.fromstring(xml).iter(f"{{{NS['m']}}}records"), None)
    except SalesforceAuthExpired:
        raise
    except (SalesforceError, ET.ParseError) as exc:
        return {"available": False, "flags": [], "error": f"Couldn’t read the EAC settings ({exc})."}
    flags = []
    for el in list(rec) if rec is not None else []:
        name = el.tag.split("}")[-1]
        value = (el.text or "").strip().lower()
        if value in ("true", "false"):
            flags.append({"name": name, "label": _label(name), "on": value == "true"})
    if not flags:
        return {"available": False, "flags": [], "error": "Salesforce returned no EAC settings (EAC may not be set up in this org)."}
    return {"available": True, "flags": flags, "error": None}


def tiles(flags: list[dict]) -> list[dict]:
    out = []
    for key, label, pattern in TILES:
        flag = next((f for f in flags if pattern.search(f["name"])), None)
        out.append({"key": key, "label": label, "on": flag["on"] if flag else None, "setting": flag["label"] if flag else None})
    return out


def assigned_users(sf: SalesforceClient) -> tuple[list[str], set[str]]:
    """(what assigns EAC: permission sets and licences, by name; the ids of the users assigned)."""
    sources: list[str] = []
    ids: set[str] = set()
    sets = _try(lambda: sf.query(f"SELECT Id, Label FROM PermissionSet WHERE Label LIKE '{EAC_LABEL}' OR Name LIKE '%ActivityCapture%' LIMIT 50")
                .get("records", []), [])
    if sets:
        sources += [f"Permission set: {p.get('Label')}" for p in sets]
        rows = _try(lambda: sf.query("SELECT AssigneeId FROM PermissionSetAssignment WHERE PermissionSetId IN ("
                                     + ", ".join(f"'{p['Id']}'" for p in sets if re.fullmatch(r"[A-Za-z0-9]{15,18}", p.get("Id") or ""))
                                     + ") LIMIT 10000", max_rows=10000).get("records", []), [])
        ids |= {r["AssigneeId"] for r in rows if SAFE_ID.fullmatch(r.get("AssigneeId") or "")}
    lic = _try(lambda: sf.query(f"SELECT Id, MasterLabel FROM PermissionSetLicense WHERE MasterLabel LIKE '{EAC_LABEL}' LIMIT 20").get("records", []), [])
    if lic:
        sources += [f"Licence: {p.get('MasterLabel')}" for p in lic]
        rows = _try(lambda: sf.query("SELECT AssigneeId FROM PermissionSetLicenseAssign WHERE PermissionSetLicenseId IN ("
                                     + ", ".join(f"'{p['Id']}'" for p in lic if re.fullmatch(r"[A-Za-z0-9]{15,18}", p.get("Id") or ""))
                                     + ") LIMIT 10000", max_rows=10000).get("records", []), [])
        ids |= {r["AssigneeId"] for r in rows if SAFE_ID.fullmatch(r.get("AssigneeId") or "")}
    return sources, ids


def _days_ago(iso: str | None) -> int | None:
    from datetime import datetime, timezone
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).days


def users(sf: SalesforceClient, ids: set[str]) -> dict:
    """The assigned users, with the ones Salesforce shows a problem for (deactivated, never or long not logged in)."""
    rows: list[dict] = []
    ordered = sorted(ids)
    for i in range(0, len(ordered), 200):
        chunk = ", ".join(f"'{x}'" for x in ordered[i:i + 200])
        rows += _try(lambda: sf.query(f"SELECT Id, Name, Profile.Name, IsActive, LastLoginDate FROM User WHERE Id IN ({chunk})")
                     .get("records", []), [])
    issues, active = [], 0
    for u in rows:
        days = _days_ago(u.get("LastLoginDate"))
        if not u.get("IsActive"):
            status, tone = "Deactivated user", "bad"
        elif days is None:
            status, tone = "Never logged in", "warn"
        elif days > STALE_LOGIN_DAYS:
            status, tone = f"No login in {days} days", "warn"
        else:
            active += 1
            continue
        issues.append({"id": u["Id"], "name": u.get("Name") or u["Id"], "profile": (u.get("Profile") or {}).get("Name"),
                       "status": status, "tone": tone})
    issues.sort(key=lambda r: (r["tone"] != "bad", r["name"].lower()))
    return {"total": len(rows), "active": active, "attention": len(issues), "issues": issues}


def pipeline(sf: SalesforceClient, ids: set[str]) -> list[dict]:
    """What Salesforce shows of the activity flowing in: Activity Metrics updated, and tasks and events the EAC users logged."""
    def count(soql: str) -> int | None:
        return _try(lambda: int(sf.query(soql).get("totalSize") or 0))

    out = []
    for days in (7, 30):
        out.append({"key": f"metrics{days}", "label": f"Activity Metrics updated (last {days} days)",
                    "value": count(f"SELECT COUNT() FROM ActivityMetric WHERE LastModifiedDate = LAST_N_DAYS:{days}")})
    owners = ", ".join(f"'{x}'" for x in sorted(ids)[:200])
    for obj, what in (("Task", "Tasks"), ("Event", "Events")):
        out.append({"key": obj.lower(), "label": f"{what} logged by EAC users (last 7 days)",
                    "value": count(f"SELECT COUNT() FROM {obj} WHERE OwnerId IN ({owners}) AND CreatedDate = LAST_N_DAYS:7") if owners else 0})
    return out


def eac_health(sf: SalesforceClient) -> dict:
    """Everything the EAC Health card shows, live."""
    conf = settings(sf)
    sources, ids = assigned_users(sf)
    people = users(sf, ids)
    master = next((t["on"] for t in tiles(conf["flags"]) if t["key"] == "master"), None)
    if not people["total"] and master is not True:
        status = "Not set up"
    elif people["attention"] or any(t["on"] is False for t in tiles(conf["flags"])):
        status = "Warning"
    else:
        status = "Healthy"
    return {"status": status, "settings": conf, "tiles": tiles(conf["flags"]), "sources": sources, "users": people,
            "pipeline": pipeline(sf, ids)}
