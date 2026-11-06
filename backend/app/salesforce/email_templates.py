"""Email template availability, read live from Salesforce (read-only): every email template with its type, status (active or
not), the area (object) it's used for, and its share of all template use.

From EmailTemplate: Name, TemplateType (Text, HTML, Custom, Visualforce), UiType (Classic or Lightning), IsActive,
RelatedEntityType (the object a Lightning template is for, e.g. Lead or Opportunity), TimesUsed and LastUsedDate. A field the
org doesn't have is left out and shown as not available. Usage % = the template's Times Used out of all templates' Times Used.

Where each template was really sent: the org's sent emails (EmailMessage, with the template used) by the object of the record
each was sent from (Related To), or, when there is none, of the person it went to (a Lead or Contact). Emails sent before
Enhanced Email, or outside Salesforce, aren't kept as email messages, so they can't be counted.
"""
from . import explorer
from .client import SalesforceClient
from .errors import SalesforceAuthExpired, SalesforceError

LIMIT = 2000
TEMPLATE_TYPES = {"text": "Text", "html": "HTML (letterhead)", "custom": "Custom HTML", "visualforce": "Visualforce"}
UI_TYPES = {"Aloha": "Classic", "SFX": "Lightning", "SFX_Sample": "Lightning sample"}
STATUSES = ("all", "active", "inactive")
SENT_LIMIT = 20000  # sent emails read for "Most used on"


def sent_by_object(sf: SalesforceClient) -> dict | None:
    """{template id: {object label: emails sent}} from the org's sent emails, or None when they can't be read."""
    try:
        prefixes = {o["keyPrefix"]: o.get("label") or name for name, o in explorer._global(sf).items() if o.get("keyPrefix")}
        emails = sf.query(f"SELECT Id, EmailTemplateId, RelatedToId FROM EmailMessage WHERE EmailTemplateId != null "
                          f"ORDER BY CreatedDate DESC LIMIT {SENT_LIMIT}", max_rows=SENT_LIMIT).get("records", [])
    except SalesforceAuthExpired:
        raise
    except SalesforceError:
        return None
    to: dict[str, str] = {}  # email -> the person it went to, for emails with no Related To
    if any(not e.get("RelatedToId") for e in emails):
        try:
            for r in sf.query("SELECT EmailMessageId, RelationId FROM EmailMessageRelation WHERE RelationType = 'ToAddress' "
                              f"AND RelationId != null AND EmailMessage.EmailTemplateId != null LIMIT {SENT_LIMIT}",
                              max_rows=SENT_LIMIT).get("records", []):
                to.setdefault(r.get("EmailMessageId"), r.get("RelationId"))
        except SalesforceAuthExpired:
            raise
        except SalesforceError:
            pass
    out: dict[str, dict[str, int]] = {}
    for e in emails:
        rid = e.get("RelatedToId") or to.get(e.get("Id"))
        obj = prefixes.get(str(rid or "")[:3], "Other") if rid else "No related record"
        per = out.setdefault(e["EmailTemplateId"][:15], {})
        per[obj] = per.get(obj, 0) + 1
    return {"byTemplate": out, "capped": len(emails) >= SENT_LIMIT}


def _type(r: dict) -> str:
    ui = UI_TYPES.get(r.get("UiType") or "", r.get("UiType") or "")
    kind = TEMPLATE_TYPES.get((r.get("TemplateType") or "").lower(), r.get("TemplateType") or "")
    return " · ".join(x for x in (ui, kind) if x) or "Unknown"


def email_templates(sf: SalesforceClient, status: str = "all") -> dict:
    """The templates (for the status picked), the counts per status, and template use by area."""
    if status not in STATUSES:
        raise ValueError("Pick all, active or inactive.")
    fields = explorer._fields(explorer._describe(sf, "EmailTemplate"))
    want = ["Id", "Name", "TemplateType", "UiType", "IsActive", "RelatedEntityType", "TimesUsed", "LastUsedDate", "FolderName"]
    cols = [f for f in want if f in fields]
    rows = sf.query(f"SELECT {', '.join(cols)} FROM EmailTemplate ORDER BY Name LIMIT {LIMIT}", max_rows=LIMIT).get("records", [])
    has_used = "TimesUsed" in fields
    labels: dict[str, str] = {}

    def area(obj: str | None) -> str:
        if not obj:
            return "Not tied to an object"
        if obj not in labels:
            try:
                labels[obj] = explorer._describe(sf, obj).get("label") or obj
            except SalesforceAuthExpired:
                raise
            except Exception:  # noqa: BLE001 - a label is a nicety; the API name still says which object
                labels[obj] = obj
        return labels[obj]

    total_used = sum(int(r.get("TimesUsed") or 0) for r in rows) if has_used else 0
    templates, by_area = [], {}
    for r in rows:
        used = int(r.get("TimesUsed") or 0) if has_used else None
        where = area(r.get("RelatedEntityType")) if "RelatedEntityType" in fields else "Not available"
        if used:
            by_area[where] = by_area.get(where, 0) + used
        templates.append({"id": r.get("Id"), "name": r.get("Name") or "", "type": _type(r), "active": bool(r.get("IsActive")),
                          "area": where, "folder": r.get("FolderName"), "timesUsed": used,
                          "usagePct": round(100 * used / total_used, 1) if used is not None and total_used else (0.0 if has_used else None),
                          "lastUsed": (r.get("LastUsedDate") or "")[:10] or None})
    sent = sent_by_object(sf)
    by_obj: dict[str, int] = {}
    for t in templates:
        per = (sent or {}).get("byTemplate", {}).get(str(t["id"] or "")[:15], {})
        t["sentFrom"] = sorted(({"object": o, "count": c} for o, c in per.items()), key=lambda x: -x["count"])
        t["mostUsedOn"] = t["sentFrom"][0]["object"] if t["sentFrom"] else None
        t["sent"] = sum(per.values())
        for o, c in per.items():
            by_obj[o] = by_obj.get(o, 0) + c
    sent_total = sum(by_obj.values())
    sent_objects = sorted(({"area": o, "timesUsed": c, "pct": round(100 * c / sent_total, 1)} for o, c in by_obj.items()),
                          key=lambda x: -x["timesUsed"])
    counts = {"all": len(templates), "active": sum(t["active"] for t in templates)}
    counts["inactive"] = counts["all"] - counts["active"]
    shown = [t for t in templates if status == "all" or t["active"] == (status == "active")]
    shown.sort(key=lambda t: (-(t["timesUsed"] or 0), t["name"].lower()))  # most used first
    areas = sorted(({"area": a, "timesUsed": n, "pct": round(100 * n / total_used, 1)} for a, n in by_area.items()),
                   key=lambda x: -x["timesUsed"])
    return {"status": status, "counts": counts, "templates": shown, "areas": areas, "totalUsed": total_used if has_used else None,
            "truncated": len(rows) >= LIMIT, "sentAvailable": sent is not None, "sentObjects": sent_objects, "sentTotal": sent_total,
            "sentCapped": bool(sent and sent["capped"])}
