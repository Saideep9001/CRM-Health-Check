"""Opportunity Sales Paths, read live from Setup (read-only): each Path, whether it's active, its record type and sales
process, and for every stage of that sales process the "Guidance for Success" text and key fields, exactly as entered in
Salesforce (nothing is made up here).

Where it comes from: the Tooling API's PathAssistant (one row per Path, its Metadata holds the steps: picklistValueName,
info = the guidance as rich text, fieldNames = the key fields); the Path's record type (RecordType.BusinessProcessId) and
that Sales Process's stages (BusinessProcess Metadata values); and OpportunityStage for the stage labels and order. When a
Path is on the Master record type, or its sales process can't be read, its stages are every active Opportunity stage.
"""
import html
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

from . import explorer
from .client import SalesforceClient
from .errors import SalesforceAuthExpired, SalesforceError

NS = {"m": "http://soap.sforce.com/2006/04/metadata"}
SAFE_ID = re.compile(r"[A-Za-z0-9]{15,18}")


def _tooling(sf: SalesforceClient, soql: str) -> list[dict]:
    return sf.get(f"/services/data/{sf.settings.sf_api_version}/tooling/query?q={quote(soql)}").get("records", [])


def guidance_lines(info: str | None) -> list[str]:
    """The guidance's rich text as plain lines, as Salesforce shows it: paragraphs as lines, list items as "• item"."""
    if not info:
        return []
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", info)
    text = re.sub(r"(?i)<li[^>]*>", "\n• ", text)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|li|ul|ol|h[1-6])>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return [ln for ln in lines if ln and ln != "•"]


def _steps_from_xml(xml: str) -> dict:
    rec = next(ET.fromstring(xml).iter(f"{{{NS['m']}}}records"), None)
    if rec is None:
        return {}
    return {
        "recordTypeName": rec.findtext("m:recordTypeName", None, NS),
        "pathAssistantSteps": [{"picklistValueName": s.findtext("m:picklistValueName", "", NS), "info": s.findtext("m:info", "", NS),
                                "fieldNames": [f.text for f in s.findall("m:fieldNames", NS) if f.text]}
                               for s in rec.findall("m:pathAssistantSteps", NS)],
    }


def _path_metadata(sf: SalesforceClient, path: dict) -> dict:
    """A Path's steps and record type: from the Tooling API's Metadata, else the Metadata API's readMetadata."""
    try:
        rows = _tooling(sf, f"SELECT Id, Metadata FROM PathAssistant WHERE Id = '{path['Id']}'")
        meta = (rows[0] if rows else {}).get("Metadata")
        if meta:
            return meta
    except SalesforceAuthExpired:
        raise
    except SalesforceError:
        pass
    if path.get("DeveloperName") and hasattr(sf, "read_metadata"):
        try:
            return _steps_from_xml(sf.read_metadata("PathAssistant", [path["DeveloperName"]]))
        except SalesforceAuthExpired:
            raise
        except (SalesforceError, ET.ParseError):
            pass
    return {}


def _process_stages(sf: SalesforceClient, record_type: str | None) -> tuple[str | None, str | None, list[str] | None]:
    """(record type label, sales process name, its stage API names in order) for a Path's record type ("Opportunity.Channel");
    None for the stages when it's the Master record type or can't be read."""
    dev = (record_type or "").split(".", 1)[-1]
    if not dev or dev == "__MASTER__" or not re.fullmatch(r"\w+", dev):
        return ("Master" if dev == "__MASTER__" else None), None, None
    try:
        rt = sf.query(f"SELECT Name, BusinessProcessId FROM RecordType WHERE SobjectType = 'Opportunity' AND DeveloperName = '{dev}' LIMIT 1").get("records", [])
        if not rt:
            return dev, None, None
        name, bp = rt[0].get("Name") or dev, rt[0].get("BusinessProcessId")
        if not bp or not SAFE_ID.fullmatch(bp):
            return name, None, None
        rows = _tooling(sf, f"SELECT Id, Name, Metadata FROM BusinessProcess WHERE Id = '{bp}'")
        if not rows:
            return name, None, None
        values = (rows[0].get("Metadata") or {}).get("values") or []
        return name, rows[0].get("Name"), [v["fullName"] for v in values if v.get("fullName")] or None
    except SalesforceAuthExpired:
        raise
    except SalesforceError:
        return dev, None, None


def sales_paths(sf: SalesforceClient) -> list[dict]:
    """Every Opportunity Sales Path (active first), each with its stages and their guidance, read live from Setup."""
    try:
        paths = [p for p in _tooling(sf, "SELECT Id, DeveloperName, MasterLabel, SobjectType, IsActive FROM PathAssistant")
                 if p.get("SobjectType") == "Opportunity" and SAFE_ID.fullmatch(str(p.get("Id") or ""))]
    except SalesforceAuthExpired:
        raise
    except SalesforceError as exc:
        raise ValueError(f"Couldn’t read the Sales Paths ({exc}). The connected user needs “View Setup and Configuration”.") from None
    stages = sf.query("SELECT ApiName, MasterLabel, IsClosed, SortOrder FROM OpportunityStage WHERE IsActive = true ORDER BY SortOrder").get("records", [])
    by_api = {s["ApiName"]: s for s in stages if s.get("ApiName")}
    try:
        labels = {n: f.get("label") or n for n, f in explorer._fields(explorer._describe(sf, "Opportunity")).items()}
    except SalesforceAuthExpired:
        raise
    except Exception:  # noqa: BLE001 - labels are a nicety; the API names still say which field
        labels = {}
    out = []
    for p in paths:
        meta = _path_metadata(sf, p)
        steps = {s.get("picklistValueName"): s for s in meta.get("pathAssistantSteps") or [] if s.get("picklistValueName")}
        rt_name, process, order = _process_stages(sf, meta.get("recordTypeName"))
        names = order or list(by_api)
        rows = []
        for api in names:
            stage, step = by_api.get(api, {}), steps.get(api) or {}
            lines = guidance_lines(step.get("info"))
            rows.append({"stage": stage.get("MasterLabel") or api, "apiName": api, "closed": bool(stage.get("IsClosed")),
                         "available": bool(lines), "details": lines,
                         "keyFields": [labels.get(f, f) for f in step.get("fieldNames") or []]})
        open_rows = [r for r in rows if not r["closed"]]
        out.append({"id": p["Id"], "name": p.get("MasterLabel") or p.get("DeveloperName") or "Sales Path", "active": bool(p.get("IsActive")),
                    "recordType": rt_name, "salesProcess": process, "stages": rows,
                    "openStages": len(open_rows), "guided": sum(r["available"] for r in open_rows)})
    return sorted(out, key=lambda x: (not x["active"], x["name"].lower()))
