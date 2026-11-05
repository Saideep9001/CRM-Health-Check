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


def _process_values(sf: SalesforceClient, process_id: str) -> tuple[str | None, list[str] | None]:
    """A Sales Process's (name, stages as API names in its order); None for what can't be read."""
    try:
        rows = _tooling(sf, f"SELECT Id, Name, Metadata FROM BusinessProcess WHERE Id = '{process_id}'")
    except SalesforceAuthExpired:
        raise
    except SalesforceError:
        return None, None
    row = rows[0] if rows else {}
    values = (row.get("Metadata") or {}).get("values") or []
    return row.get("Name"), [v["fullName"] for v in values if v.get("fullName")] or None


def _query(sf: SalesforceClient, soql: str) -> list[dict]:
    try:
        return sf.query(soql).get("records", [])
    except SalesforceAuthExpired:
        raise
    except SalesforceError:
        return []


def sales_paths(sf: SalesforceClient) -> list[dict]:
    """Every Opportunity Sales Process (those with an active Path first), each with the Path for its record types and every
    stage of the process with that Path's guidance, read live from Setup. A Master Path (Opportunities with no record type)
    and any Path whose sales process can't be found are listed too."""
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
    for p in paths:  # each Path's steps and record type ("Opportunity.Channel", or "__MASTER__")
        meta = _path_metadata(sf, p)
        p["_steps"] = {st.get("picklistValueName"): st for st in meta.get("pathAssistantSteps") or [] if st.get("picklistValueName")}
        p["_rt"] = (meta.get("recordTypeName") or "").split(".", 1)[-1]
    rtypes = _query(sf, "SELECT Name, DeveloperName, BusinessProcessId, IsActive FROM RecordType WHERE SobjectType = 'Opportunity' ORDER BY Name")
    processes = _query(sf, "SELECT Id, Name, IsActive FROM BusinessProcess WHERE TableEnumOrId = 'Opportunity' ORDER BY Name")
    known = {b["Id"] for b in processes}
    for r in rtypes:  # a process a record type uses but the list didn't show (e.g. no access to BusinessProcess)
        bp = r.get("BusinessProcessId")
        if bp and bp not in known:
            known.add(bp)
            processes.append({"Id": bp, "Name": None, "IsActive": True})

    def entry(key: str, name: str, process_active: bool, order: list[str] | None, rts: list[str], on: list[dict]) -> dict:
        shown = next((p for p in on if p.get("IsActive")), on[0] if on else None)  # the active Path, else an inactive one
        steps = shown["_steps"] if shown else {}
        rows = []
        for api in order or list(by_api):
            stage, step = by_api.get(api, {}), steps.get(api) or {}
            lines = guidance_lines(step.get("info"))
            rows.append({"stage": stage.get("MasterLabel") or api, "apiName": api, "closed": bool(stage.get("IsClosed")),
                         "available": bool(lines), "details": lines,
                         "keyFields": [labels.get(f, f) for f in step.get("fieldNames") or []]})
        open_rows = [r for r in rows if not r["closed"]]
        return {"id": key, "name": name, "active": bool(shown and shown.get("IsActive")), "processActive": process_active,
                "pathName": (shown.get("MasterLabel") or shown.get("DeveloperName")) if shown else None,
                "pathActive": bool(shown and shown.get("IsActive")) if shown else None,
                "recordType": ", ".join(rts) or None, "salesProcess": name, "stages": rows,
                "openStages": len(open_rows), "guided": sum(r["available"] for r in open_rows)}

    out, used = [], set()
    for b in processes:
        if not SAFE_ID.fullmatch(str(b.get("Id") or "")):
            continue
        rts = [r for r in rtypes if r.get("BusinessProcessId") == b["Id"]]
        devs = {r.get("DeveloperName") for r in rts}
        on = [p for p in paths if p["_rt"] in devs]
        used.update(p["Id"] for p in on)
        name, order = _process_values(sf, b["Id"])
        out.append(entry(b["Id"], b.get("Name") or name or "Sales Process", bool(b.get("IsActive")), order,
                         [r.get("Name") or r.get("DeveloperName") for r in rts], on))
    for p in paths:  # the Master Path, and Paths whose sales process wasn't found: every active stage
        if p["Id"] not in used:
            master = p["_rt"] == "__MASTER__"
            out.append(entry(p["Id"], "Master (no record type)" if master else (p.get("MasterLabel") or "Sales Path"), True, None,
                             ["Master"] if master else ([p["_rt"]] if p["_rt"] else []), [p]))
    return sorted(out, key=lambda x: (not x["active"], x["name"].lower()))
