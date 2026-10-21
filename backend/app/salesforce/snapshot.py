"""A live, read-only snapshot of the connected org for the Connect Salesforce page.

Three light calls: Organization + active users (SOQL), /limits, and /limits/recordCount (cached by the explorer).
"""
import time
from datetime import datetime, timezone

from . import explorer
from .client import SalesforceClient
from .errors import SalesforceError

# Org limits worth watching, in plain words.
LIMITS = (
    ("DailyApiRequests", "API calls today", "calls"),
    ("DataStorageMB", "Data storage", "MB"),
    ("FileStorageMB", "File storage", "MB"),
    ("DailyAsyncApexExecutions", "Background Apex jobs today", "jobs"),
    ("DailyBulkV2QueryJobs", "Bulk data exports today", "jobs"),
    ("SingleEmail", "Emails sent from Apex today", "emails"),
)

# Objects people recognise, shown first.
KEY_OBJECTS = (
    ("Account", "Accounts"), ("Contact", "Contacts"), ("Lead", "Leads"), ("Opportunity", "Opportunities"),
    ("Case", "Cases"), ("Task", "Tasks"), ("Event", "Events"), ("Campaign", "Campaigns"),
    ("Product2", "Products"), ("Quote", "Quotes"), ("Contract", "Contracts"), ("Order", "Orders"),
)


def snapshot(sf: SalesforceClient) -> dict:
    org = (sf.query("SELECT Name, OrganizationType, InstanceName, IsSandbox, CreatedDate, LanguageLocaleKey, "
                    "DefaultLocaleSidKey, TimeZoneSidKey FROM Organization LIMIT 1").get("records") or [{}])[0]
    # Timed after the first call, so a sign-in token refresh doesn't count as Salesforce being slow.
    started = time.perf_counter()
    users = sf.query("SELECT COUNT() FROM User WHERE IsActive = true AND UserType = 'Standard'").get("totalSize")
    response_ms = round((time.perf_counter() - started) * 1000)

    limits = []
    try:
        raw = sf.limits() or {}
    except SalesforceError:
        raw = {}
    for key, label, unit in LIMITS:
        v = raw.get(key) or {}
        if v.get("Max"):
            limits.append({"key": key, "label": label, "unit": unit, "max": v["Max"], "used": max(0, v["Max"] - v.get("Remaining", 0))})

    counts = explorer._record_counts(sf)
    records = [{"name": n, "label": label, "count": counts[n]} for n, label in KEY_OBJECTS if counts.get(n)]
    created = org.get("CreatedDate")
    return {
        "as_of": datetime.now(timezone.utc),
        "response_ms": response_ms,
        "is_sandbox": bool(org.get("IsSandbox")),
        "instance_name": org.get("InstanceName"),
        "org_created": created[:10] if isinstance(created, str) else None,
        "time_zone": org.get("TimeZoneSidKey"),
        "locale": org.get("DefaultLocaleSidKey"),
        "active_users": users,
        "limits": limits,
        "records": records,
        "total_records": sum(counts.values()) if counts else None,
        "object_count": len(counts) if counts else None,
    }
