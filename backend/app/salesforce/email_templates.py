"""Email template availability, read live from Salesforce (read-only): every email template with its Description (what it's
for), type, status (active or not) and its share of all template use.

From EmailTemplate: Name, Description, TemplateType (Text, HTML, Custom, Visualforce), UiType (Classic or Lightning),
IsActive, TimesUsed and FolderName. A field the org doesn't have is left out and shown as not available. Usage % = the
template's Times Used out of all templates' Times Used.
"""
from . import explorer
from .client import SalesforceClient

LIMIT = 2000
TEMPLATE_TYPES = {"text": "Text", "html": "HTML (letterhead)", "custom": "Custom HTML", "visualforce": "Visualforce"}
UI_TYPES = {"Aloha": "Classic", "SFX": "Lightning", "SFX_Sample": "Lightning sample"}
STATUSES = ("all", "active", "inactive")


def _type(r: dict) -> str:
    ui = UI_TYPES.get(r.get("UiType") or "", r.get("UiType") or "")
    kind = TEMPLATE_TYPES.get((r.get("TemplateType") or "").lower(), r.get("TemplateType") or "")
    return " · ".join(x for x in (ui, kind) if x) or "Unknown"


def email_templates(sf: SalesforceClient, status: str = "all") -> dict:
    """The templates (for the status picked), most used first, and the counts per status."""
    if status not in STATUSES:
        raise ValueError("Pick all, active or inactive.")
    fields = explorer._fields(explorer._describe(sf, "EmailTemplate"))
    want = ["Id", "Name", "Description", "TemplateType", "UiType", "IsActive", "TimesUsed", "FolderName"]
    cols = [f for f in want if f in fields]
    rows = sf.query(f"SELECT {', '.join(cols)} FROM EmailTemplate ORDER BY Name LIMIT {LIMIT}", max_rows=LIMIT).get("records", [])
    has_used = "TimesUsed" in fields
    total_used = sum(int(r.get("TimesUsed") or 0) for r in rows) if has_used else 0
    templates = []
    for r in rows:
        used = int(r.get("TimesUsed") or 0) if has_used else None
        templates.append({"id": r.get("Id"), "name": r.get("Name") or "", "description": (r.get("Description") or "").strip() or None,
                          "type": _type(r), "active": bool(r.get("IsActive")), "folder": r.get("FolderName"), "timesUsed": used,
                          "usagePct": round(100 * used / total_used, 1) if used is not None and total_used else (0.0 if has_used else None)})
    counts = {"all": len(templates), "active": sum(t["active"] for t in templates)}
    counts["inactive"] = counts["all"] - counts["active"]
    shown = [t for t in templates if status == "all" or t["active"] == (status == "active")]
    shown.sort(key=lambda t: (-(t["timesUsed"] or 0), t["name"].lower()))  # most used first
    return {"status": status, "counts": counts, "templates": shown, "totalUsed": total_used if has_used else None,
            "truncated": len(rows) >= LIMIT}
