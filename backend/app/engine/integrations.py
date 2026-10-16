"""Category 6 — Integrations, API & Data Flow (areas 18 to 21).

Based on the Aquarient RevenueOps Consultant Guide v1.0. Indicator labels match
src/config/categories.ts exactly. Installed packages and connected apps tell us
which outside systems are plugged in; the Limits API and job history show health.
Everything is read-only; setup reads are skipped with a note without "View Setup".
"""
import re
from collections import Counter

from ..salesforce import explorer
from .core import Ctx, FindingDraft, Unavailable, pct, rate_score
from .reporting import _reports


# Where in Salesforce each setup problem is fixed.
SETTING_FIX = {
    'No marketing automation connected': '/lightning/setup/ImportedPackage/home',
    'Campaigns aren’t used': '/lightning/o/Campaign/home',
    'No dedicated integration user': '/lightning/setup/ManageUsers/home',
    'Integration users have full admin rights': '/lightning/setup/ManageUsers/home',
    'Accounts have no External ID field': '/lightning/setup/ObjectManager/Account/FieldsAndRelationships/view',
    'Won deals can’t be traced to finance': '/lightning/setup/ObjectManager/Opportunity/FieldsAndRelationships/view',
    'Salesforce limits close to their maximum': '/lightning/setup/CompanyProfileInfo/home',
    'Connected apps with old, unused access': '/lightning/setup/ConnectedAppsUsage/home',
    'Very large objects': '/lightning/setup/CompanyResourceDisk/home',
}


def _setting(ctx: Ctx, name: str, description: str, action: str, severity: str = "medium", obj: str | None = None,
             why: str = "Connected systems only help when data flows reliably and someone can see when it doesn’t.") -> None:
    ctx.findings.append(FindingDraft(
        area_id=ctx.area_id,
        name=name,
        severity=severity,  # type: ignore[arg-type]
        affected_records=0,
        description=description,
        why_it_matters=why,
        business_impact="Re-keying data between systems, mismatched numbers, and failures nobody notices.",
        recommended_action=action,
        object_name=obj,
        fix_url=ctx.setup_url(SETTING_FIX[name]) if name in SETTING_FIX else None,
    ))


def _connected(ctx: Ctx) -> list[str]:
    """Names of installed packages and connected apps (cached). Empty if setup can't be read."""
    if "connected" not in ctx.memo:
        names: list[str] = []
        try:
            for p in ctx.setup("SELECT SubscriberPackage.Name, SubscriberPackage.NamespacePrefix FROM InstalledSubscriberPackage"):
                sp = p.get("SubscriberPackage") or {}
                names.append(f"{sp.get('Name') or ''} ({sp.get('NamespacePrefix') or ''})")
        except Unavailable:
            pass
        try:
            names += [a.get("Name") or "" for a in ctx.setup("SELECT Id, Name FROM ConnectedApplication", tooling=False)]
        except Unavailable:
            pass
        ctx.memo["connected"] = names
    return ctx.memo["connected"]


def _matches(ctx: Ctx, pattern: str) -> list[str]:
    rx = re.compile(pattern, re.I)
    return sorted({n for n in _connected(ctx) if rx.search(n)})


def _limits(ctx: Ctx) -> dict:
    if "limits" not in ctx.memo:
        ctx.memo["limits"] = ctx.sf.limits()
    return ctx.memo["limits"]


def _used_pct(lim: dict | None) -> float | None:
    if not lim or not lim.get("Max"):
        return None
    return 100.0 * (lim["Max"] - lim.get("Remaining", lim["Max"])) / lim["Max"]


MARKETING = r"pardot|account engagement|\bpi\b|hubspot|marketo|marketing cloud|\bet4ae\b|mailchimp|act-on|eloqua|constant contact|klaviyo|zoominfo"
ERP = r"mulesoft|boomi|netsuite|\bsap\b|quickbooks|xero|\bsage\b|dynamics|oracle|workato|celigo|jitterbit|informatica|zapier|\bmake\b|tray\.io|chargebee|zuora|stripe|avalara"
BI = r"tableau|power ?bi|fivetran|snowflake|stitch|informatica|domo|looker|qlik|crm analytics|einstein analytics|wave|segment|hightouch|census|airbyte|bigquery|redshift"
INTEGRATION_USER = re.compile(r"integration|api|sync|connector|mulesoft|boomi|hubspot|pardot|marketo|zapier|workato", re.I)


# ---------------------------------------------------------------- area 18: marketing automation & lead flow

def marketing_integration(ctx: Ctx) -> None:
    if not _connected(ctx):
        raise Unavailable("Couldn’t read installed packages or connected apps. The connected user may need “View Setup and Configuration”.")
    found = _matches(ctx, MARKETING)
    ctx.memo["marketing"] = found
    ctx.metric("Marketing integration status", 0 if found else 1, "count", "lower-better", 100 if found else 55)
    if not found:
        _setting(
            ctx,
            "No marketing automation connected",
            "No marketing platform (Account Engagement/Pardot, HubSpot, Marketo, Marketing Cloud…) is installed or connected, so reps can’t see which emails a lead opened or how engaged they are.",
            "If you use a marketing platform, connect it with its official Salesforce connector so leads, engagement, and campaigns sync both ways.",
            severity="low",
            obj="Lead",
        )


def lead_sync(ctx: Ctx) -> None:
    total = ctx.count("Lead", "CreatedDate = LAST_N_DAYS:90", recent=False)
    if not total:
        if ctx.memo.get("marketing"):
            _setting(
                ctx,
                "No new leads in 90 days",
                f"A marketing platform is connected ({', '.join(ctx.memo['marketing'][:2])}), but no Leads were created in the last 90 days. The sync may be broken.",
                "Check the connector’s sync status and error log, and test by creating a prospect in the marketing tool.",
                severity="high",
                obj="Lead",
            )
        ctx.metric("Lead synchronization concerns", 0, "%", "lower-better", 60 if ctx.memo.get("marketing") else 100)
        return
    conds = ["CreatedDate = LAST_N_DAYS:90"]
    gaps = []
    if ctx.has_field("Lead", "Email"):
        gaps.append("Email = null")
    if ctx.has_field("Lead", "LeadSource"):
        gaps.append("LeadSource = null")
    bad = ctx.count("Lead", *conds, "(" + " OR ".join(gaps) + ")", recent=False) if gaps else 0
    score = rate_score(bad / total, 0.5)
    ctx.metric("Lead synchronization concerns", pct(bad, total), "%", "lower-better", score)
    ctx.finding(
        name="New leads arriving incomplete",
        records=("Lead", *conds, "(" + " OR ".join(gaps) + ")") if gaps else None,
        recent=False,
        score=score,
        affected=bad,
        description=f"{bad:,} of {total:,} Leads created in the last 90 days ({pct(bad, total):.0f}%) arrived without an email or a lead source.",
        why="Leads that sync without basic details can’t be routed, scored, or followed up, and their source is lost.",
        impact="Lost attribution and leads that slip through the cracks.",
        action="Map Email and Lead Source in your marketing connector and web forms, and make them required for new leads.",
        obj="Lead",
        url=ctx.list_url("Lead"),
    )


def campaign_visibility(ctx: Ctx) -> None:
    if not ctx.has_object("Campaign"):
        raise Unavailable("Campaigns aren’t available in this org.")
    campaigns = ctx.count("Campaign", "CreatedDate = LAST_N_DAYS:365", recent=False)
    new_opps = ctx.count("Opportunity", "CreatedDate = LAST_N_DAYS:365", recent=False)
    if not campaigns:
        ctx.metric("Campaign visibility", 100.0, "%", "lower-better", 40)
        _setting(
            ctx,
            "Campaigns aren’t used",
            "No Campaigns were created in the last year, so marketing’s impact on pipeline can’t be measured in Salesforce.",
            "Track marketing programs as Campaigns, add leads and contacts as members, and set Primary Campaign Source on new deals.",
            obj="Campaign",
        )
        return
    no_campaign = ctx.count("Opportunity", "CreatedDate = LAST_N_DAYS:365", "CampaignId = null", recent=False) if new_opps and ctx.has_field("Opportunity", "CampaignId") else new_opps
    score = rate_score(no_campaign / new_opps, 1.0) if new_opps else 100
    ctx.metric("Campaign visibility", pct(no_campaign, new_opps), "%", "lower-better", score)
    ctx.finding(
        name="New deals not linked to a campaign",
        records=("Opportunity", "CreatedDate = LAST_N_DAYS:365", "CampaignId = null"),
        recent=False,
        score=score,
        affected=no_campaign,
        description=f"{no_campaign:,} of {new_opps:,} Opportunities created in the last year ({pct(no_campaign, new_opps):.0f}%) have no Primary Campaign Source, though {campaigns:,} campaign{'s' if campaigns != 1 else ''} ran in that time.",
        why="Without campaign links, you can’t tell which marketing programs create pipeline and revenue.",
        impact="Marketing budget decisions made without ROI data.",
        action="Set Primary Campaign Source on new deals (it fills in automatically when a lead from a campaign converts) and turn on Campaign Influence.",
        obj="Opportunity",
        min_score=80,
    )


def integration_config(ctx: Ctx) -> None:
    users = ctx.rows("SELECT Id, Name, Profile.Name, UserType FROM User WHERE IsActive = true AND UserType = 'Standard' LIMIT 2000", 2000)
    integ = [u for u in users if INTEGRATION_USER.search(f"{u.get('Name')} {(u.get('Profile') or {}).get('Name') or ''}")]
    admin_integ = [u for u in integ if re.search(r"system administrator", (u.get("Profile") or {}).get("Name") or "", re.I)]
    gaps = []
    has_integrations = bool(_matches(ctx, MARKETING) or _matches(ctx, ERP) or _matches(ctx, BI))
    if has_integrations and not integ:
        gaps.append("no dedicated integration user")
        _setting(
            ctx,
            "No dedicated integration user",
            "Outside systems are connected, but there’s no user set aside for integrations, so they probably run as a real person’s login.",
            "Create a dedicated integration user (the free “Salesforce Integration” licence) with only the permissions each integration needs.",
            severity="medium",
            obj="User",
        )
    if admin_integ:
        gaps.append("integration users with admin rights")
        _setting(
            ctx,
            "Integration users have full admin rights",
            f"{len(admin_integ)} integration user(s) use the System Administrator profile: {', '.join(u.get('Name') or '' for u in admin_integ[:5])}.",
            "Give integration users a minimal profile or permission set instead of System Administrator.",
            severity="high",
            obj="User",
            why="An integration with admin rights can change or delete anything if its credentials leak.",
        )
    ctx.metric("Integration configuration gaps", len(gaps), "count", "lower-better", [100, 60, 30][len(gaps)])


# ---------------------------------------------------------------- area 19: ERP / finance & order flow

_ERP_FIELD = re.compile(r"erp|netsuite|\bsap\b|order.?(id|number|no)|invoice|external|billing.?id|finance", re.I)


def external_ids(ctx: Ctx) -> None:
    fields = ctx.fields("Account")
    ext = [f for f in fields.values() if f.get("externalId") and f.get("filterable")]
    total = ctx.total("Account")
    if not ext:
        ctx.metric("Missing external identifiers", 100.0 if total else 0.0, "%", "lower-better", 45 if total else 100)
        _setting(
            ctx,
            "Accounts have no External ID field",
            "There’s no External ID field on Account, so other systems (ERP, billing) can’t reliably match their customers to Salesforce records.",
            "Add an External ID field (e.g. ERP_Customer_ID__c, marked Unique) and fill it from your ERP so syncs match records instead of creating duplicates.",
            obj="Account",
        )
        return
    f = ext[0]
    missing = ctx.count("Account", f"{f['name']} = null") if total else 0
    score = rate_score(missing / total, 0.9) if total else 100
    ctx.metric("Missing external identifiers", pct(missing, total), "%", "lower-better", score)
    ctx.finding(
        name="Accounts with no external ID",
        records=("Account", f"{f['name']} = null"),
        fix="/lightning/setup/ObjectManager/Account/FieldsAndRelationships/view",
        score=score,
        affected=missing,
        description=f"{missing:,} of {total:,} Accounts ({pct(missing, total):.0f}%) have no {f.get('label') or f['name']}, so they can’t be matched to other systems.",
        why="Records without an external ID get duplicated or mismatched when systems sync.",
        impact="Invoices and orders attached to the wrong customer, and manual reconciliation.",
        action=f"Fill in {f.get('label') or f['name']} for active customers (start with Accounts that have won deals).",
        obj="Account",
        url=ctx.list_url("Account"),
        min_score=85,
    )


def sync_gaps(ctx: Ctx) -> None:
    won = ("IsWon = true", "CloseDate = LAST_N_DAYS:90")
    total = ctx.count("Opportunity", *won, recent=False)
    fields = ctx.fields("Opportunity")
    candidates = [f for f in fields.values() if f.get("custom") and f.get("filterable") and (_ERP_FIELD.search(f["name"]) or _ERP_FIELD.search(f.get("label") or ""))]
    candidates.sort(key=lambda f: bool(re.search(r"external", f["name"] + " " + (f.get("label") or ""), re.I)))  # ERP-specific names first
    ref = candidates[0] if candidates else None
    if ref is not None:
        gap_cond = f"{ref['name']} = null"
        n = ctx.count("Opportunity", *won, gap_cond, recent=False) if total else 0
        how = f"no {ref.get('label') or ref['name']}"
    elif ctx.has_object("Order") and ctx.has_field("Order", "OpportunityId"):
        gap_cond = "Id NOT IN (SELECT OpportunityId FROM Order WHERE OpportunityId != null)"
        n = ctx.count("Opportunity", *won, gap_cond, recent=False) if total else 0
        how = "no Order"
    else:
        ctx.metric("Potential synchronization gaps", 0, "count", "lower-better", 70 if total else 100)
        if total:
            _setting(
                ctx,
                "Won deals can’t be traced to finance",
                f"{total:,} deals were won in the last 90 days, but there’s no Order or ERP reference field to confirm they reached finance or billing.",
                "Add an ERP/Order ID field on Opportunity (written back by the integration), or create Orders from won deals.",
                severity="low",
                obj="Opportunity",
            )
        return
    score = rate_score(n / total, 0.5) if total else 100
    ctx.metric("Potential synchronization gaps", n, "count", "lower-better", score)
    ctx.finding(
        name="Won deals that didn’t reach finance",
        records=("Opportunity", *won, gap_cond),
        recent=False,
        score=score,
        affected=n,
        description=f"{n:,} of {total:,} deals won in the last 90 days ({pct(n, total):.0f}%) have {how}, so they may not have synced to your ERP or billing system.",
        why="A won deal that never reaches billing is revenue that may never be invoiced.",
        impact="Delayed or missed invoices and month-end surprises.",
        action="Review these deals with finance, fix the sync errors, and add an alert when a won deal has no ERP reference after a day.",
        obj="Opportunity",
        url=ctx.list_url("Opportunity"),
    )


_FINANCE_OBJ = re.compile(r"invoice|order|billing|payment|subscription|contract|quote", re.I)


def order_visibility(ctx: Ctx) -> None:
    custom = [o for o in explorer._global(ctx.sf).values() if o.get("custom") and _FINANCE_OBJ.search(o["name"]) and not o["name"].endswith(("__Share", "__History", "__Feed"))]
    orders = ctx.count("Order", "CreatedDate = LAST_N_DAYS:365", recent=False) if ctx.has_object("Order") else 0
    issues = 0 if (orders or custom) else 1
    ctx.metric("Order integration visibility", issues, "count", "lower-better", 100 if not issues else 65)
    if issues:
        _setting(
            ctx,
            "No order or invoice data in Salesforce",
            "No Orders were created in the last year and there are no invoice, billing, or payment objects, so reps can’t see what customers ordered or whether they’ve paid.",
            "Bring key finance data into Salesforce (Orders, or a read-only Invoice object from your ERP) so account teams see the full customer picture.",
            severity="low",
            obj="Order",
        )


def erp_concerns(ctx: Ctx) -> None:
    if not _connected(ctx):
        raise Unavailable("Couldn’t read installed packages or connected apps. The connected user may need “View Setup and Configuration”.")
    found = _matches(ctx, ERP)
    won = ctx.count("Opportunity", "IsWon = true", "CloseDate = LAST_N_DAYS:365", recent=False)
    concern = 0 if found or not won else 1
    ctx.metric("ERP integration concerns", concern, "count", "lower-better", 100 if not concern else 60)
    if concern:
        _setting(
            ctx,
            "No ERP or integration platform connected",
            f"{won:,} deals were won in the last year, but no ERP, billing, or integration platform (MuleSoft, Boomi, NetSuite, QuickBooks…) is connected, so won deals are probably re-keyed into finance by hand.",
            "Connect your ERP or billing system (directly or through an integration platform) so won deals, customers, and invoices sync automatically.",
            severity="low",
        )


# ---------------------------------------------------------------- area 20: API governance & health

def api_usage(ctx: Ctx) -> None:
    used = _used_pct(_limits(ctx).get("DailyApiRequests"))
    if used is None:
        raise Unavailable("Salesforce didn’t report daily API usage.")
    score = 100 if used <= 50 else max(10, 100 - (used - 50) * 1.8)
    ctx.metric("API usage", used, "%", "lower-better", score)
    if used > 70:
        lim = _limits(ctx)["DailyApiRequests"]
        ctx.finding(
            name="High daily API usage",
            fix="/lightning/setup/CompanyProfileInfo/home",
            score=score,
            affected=int(lim["Max"] - lim["Remaining"]),
            description=f"{used:.0f}% of today’s {lim['Max']:,} API calls are already used. Hitting the limit stops every integration until it resets.",
            why="When the daily API limit runs out, syncs, apps, and integrations all stop at once.",
            impact="Outages across connected systems and data that stops flowing.",
            action="Find the heaviest users in Setup → System Overview / API Usage report, switch bulk loads to the Bulk API, and set an API usage notification at 80%.",
            obj=None,  # org-wide
            min_score=101,
        )


_WATCHED_LIMITS = {
    "DailyAsyncApexExecutions": "Async Apex executions",
    "DailyBulkApiBatches": "Bulk API batches",
    "DailyBulkV2QueryJobs": "Bulk API query jobs",
    "DailyStreamingApiEvents": "Streaming API events",
    "HourlyPublishedPlatformEvents": "Platform events (hourly)",
    "DailyWorkflowEmails": "Workflow emails",
    "SingleEmail": "Single emails",
    "MassEmail": "Mass emails",
    "HourlyTimeBasedWorkflow": "Time-based workflow (hourly)",
}


def api_limit_monitoring(ctx: Ctx) -> None:
    limits = _limits(ctx)
    close = [(label, u) for key, label in _WATCHED_LIMITS.items() if (u := _used_pct(limits.get(key))) is not None and u >= 80]
    ctx.metric("API limit monitoring", len(close), "count", "lower-better", 100 - 20 * min(len(close), 4))
    if close:
        _setting(
            ctx,
            "Salesforce limits close to their maximum",
            "These limits are 80%+ used: " + ", ".join(f"{label} ({u:.0f}%)" for label, u in close) + ".",
            "Review what is using these limits, spread heavy jobs out, and set up limit notifications so someone is warned before things stop.",
            severity="high" if any(u >= 95 for _, u in close) else "medium",
        )


def connected_apps(ctx: Ctx) -> None:
    try:
        tokens = ctx.setup("SELECT AppName, LastUsedDate FROM OauthToken ORDER BY LastUsedDate DESC LIMIT 2000", tooling=False)
    except Unavailable:
        tokens = None
    if tokens is None:
        names = _connected(ctx)
        if not names:
            raise Unavailable("Couldn’t read connected apps. The connected user may need “View Setup and Configuration” and “Manage Users”.")
        ctx.metric("Connected application visibility", 0, "count", "lower-better", 85)
        return
    last: dict[str, str] = {}
    for t in tokens:
        app = t.get("AppName") or "Unknown app"
        if t.get("LastUsedDate") and (app not in last or t["LastUsedDate"] > last[app]):
            last[app] = t["LastUsedDate"]
        last.setdefault(app, t.get("LastUsedDate") or "")
    from .workflows import _days_since

    stale = sorted(app for app, d in last.items() if (_days_since(d) or 9999) > 90)
    score = rate_score(len(stale) / len(last), 0.6) if last else 100
    ctx.metric("Connected application visibility", len(stale), "count", "lower-better", score)
    if stale:
        _setting(
            ctx,
            "Connected apps with old, unused access",
            f"{len(stale)} of {len(last)} connected apps still hold access but haven’t been used in 90+ days: {', '.join(stale[:6])}{' …' if len(stale) > 6 else ''}.",
            "Revoke access for apps you no longer use (Setup → Connected Apps OAuth Usage) and review the rest every quarter.",
            severity="medium" if len(stale) >= 3 else "low",
            why="Every app with standing access is a door into your data. Unused ones are pure risk.",
        )


def integration_health(ctx: Ctx) -> None:
    if not ctx.has_object("AsyncApexJob"):
        raise Unavailable("Background job history can’t be read with this user.")
    total = ctx.count("AsyncApexJob", "CreatedDate = LAST_N_DAYS:7", recent=False)
    failed = ctx.count("AsyncApexJob", "Status = 'Failed'", "CreatedDate = LAST_N_DAYS:7", recent=False) if total else 0
    score = rate_score(failed / total, 0.2) if total else 100
    ctx.metric("Integration health indicators", failed, "count", "lower-better", score)
    if failed:
        groups = ctx.sf.query(
            "SELECT ApexClass.Name n, COUNT(Id) c FROM AsyncApexJob WHERE Status = 'Failed' AND CreatedDate = LAST_N_DAYS:7 GROUP BY ApexClass.Name ORDER BY COUNT(Id) DESC LIMIT 5"
        ).get("records", [])
        top = ", ".join(f"{g.get('n') or 'unknown'} ({g.get('c')})" for g in groups)
        ctx.finding(
            name="Failed background jobs",
            records=("AsyncApexJob", "Status = 'Failed'", "CreatedDate = LAST_N_DAYS:7"),
            recent=False,
            fix="/lightning/setup/AsyncApexJobs/home",
            score=score,
            affected=failed,
            description=f"{failed:,} of {total:,} background (Apex) jobs failed in the last 7 days" + (f". Most failures: {top}." if top else "."),
            why="Failed jobs often mean a sync or automation silently stopped — nobody notices until data is wrong.",
            impact="Missing or stale data in Salesforce and connected systems.",
            action="Open Setup → Apex Jobs, fix the failing classes, and add failure alerts so the owner hears about it the same day.",
            obj="AsyncApexJob",
            min_score=101,
        )


# ---------------------------------------------------------------- area 21: data warehouse & BI

def bi_integration(ctx: Ctx) -> None:
    if not _connected(ctx):
        raise Unavailable("Couldn’t read installed packages or connected apps. The connected user may need “View Setup and Configuration”.")
    found = _matches(ctx, BI)
    ctx.metric("BI integration visibility", 0 if found else 1, "count", "lower-better", 100 if found else 75)
    if not found:
        _setting(
            ctx,
            "No BI or data warehouse connection found",
            "No BI or data tool (Tableau, Power BI, Snowflake, Fivetran, CRM Analytics…) appears to be connected, so cross-system analysis happens in spreadsheets.",
            "If leaders need data beyond Salesforce reports, connect a BI tool or data warehouse through an approved connector with a dedicated integration user.",
            severity="low",
        )


LARGE = 1_000_000
# Salesforce's own setup/permission records aren't business data you'd extract.
_METADATA = re.compile(r"(Permissions?|Access|Assignment|Share|History|Feed|ChangeEvent|Definition|Info)$|^(Setup|Apex|Auth|Login|Permission|Field|Entity)", re.I)


def data_extraction(ctx: Ctx) -> None:
    counts = explorer._record_counts(ctx.sf)
    if not counts:
        raise Unavailable("Salesforce didn’t report record counts.")
    big = sorted(((n, c) for n, c in counts.items() if c >= LARGE and not _METADATA.search(n) and not explorer.is_system(n)), key=lambda x: -x[1])
    ctx.metric("Data extraction concerns", len(big), "count", "lower-better", 100 if not big else 80 if len(big) <= 2 else 60)
    if big:
        _setting(
            ctx,
            "Very large objects",
            "These objects hold over a million records, which makes full extracts slow and API-heavy: " + ", ".join(f"{n} ({c:,})" for n, c in big[:6]) + ".",
            "Extract them incrementally (by SystemModstamp) with the Bulk API, and archive old records you no longer need.",
            severity="low",
        )


def storage(ctx: Ctx) -> None:
    limits = _limits(ctx)
    data, files = _used_pct(limits.get("DataStorageMB")), _used_pct(limits.get("FileStorageMB"))
    used = max(v for v in (data, files, 0.0) if v is not None)
    score = 100 if used <= 60 else max(10, 100 - (used - 60) * 2.2)
    ctx.metric("Storage utilization indicators", used, "%", "lower-better", score)
    if used >= 75:
        which = "data" if (data or 0) >= (files or 0) else "file"
        lim = limits.get("DataStorageMB" if which == "data" else "FileStorageMB") or {}
        ctx.finding(
            name="Storage is filling up",
            fix="/lightning/setup/CompanyResourceDisk/home",
            score=score,
            affected=max(1, int((lim.get("Max") or 0) - (lim.get("Remaining") or 0))),  # MB used
            description=f"Data storage is {data or 0:.0f}% used and file storage {files or 0:.0f}% used. When {which} storage is full, people can’t save new records.",
            why="Running out of storage blocks new records and attachments and leads to costly emergency purchases.",
            impact="Work stops and extra storage must be bought at short notice.",
            action="Check Setup → Storage Usage, archive or delete old records and large files, and plan any purchase before you hit 90%.",
            obj=None,  # org-wide
            min_score=101,
        )


def reporting_consistency(ctx: Ctx) -> None:
    reports = _reports(ctx)
    names = Counter((r.get("Name") or "").strip().lower() for r in reports if (r.get("Name") or "").strip())
    dupes = {n: c for n, c in names.items() if c > 1}
    extra = sum(c - 1 for c in dupes.values())
    score = rate_score(extra / len(reports), 0.6) if reports else 100
    ctx.metric("Reporting consistency concerns", extra, "count", "lower-better", score)
    if dupes:
        top = sorted(dupes.items(), key=lambda x: -x[1])[:4]
        ctx.finding(
            name="Reports with the same name",
            records=("Report", ctx.ids_in([r["Id"] for r in reports if (r.get("Name") or "").strip().lower() in dupes])),
            recent=False,
            score=score,
            affected=extra,
            description=f"{len(dupes)} report names are used more than once ({extra} extra copies), e.g. "
            + ", ".join(f"“{next(r.get('Name') for r in reports if (r.get('Name') or '').strip().lower() == n)}” ({c})" for n, c in top) + ".",
            why="Several reports with the same name usually show slightly different numbers, so meetings argue about data instead of decisions.",
            impact="Conflicting numbers between Salesforce, BI tools, and spreadsheets.",
            action="Pick one trusted version of each report, mark it “certified” in its folder or description, and archive the rest.",
            obj="Report",
            min_score=90,
        )


AREAS = {
    "area-18": [marketing_integration, lead_sync, campaign_visibility, integration_config],
    "area-19": [external_ids, sync_gaps, order_visibility, erp_concerns],
    "area-20": [api_usage, api_limit_monitoring, connected_apps, integration_health],
    "area-21": [bi_integration, data_extraction, storage, reporting_consistency],
}

STEP_LABELS = {
    marketing_integration: "Looking for marketing platforms",
    lead_sync: "Checking leads arriving from integrations",
    campaign_visibility: "Checking campaigns on deals",
    integration_config: "Checking integration users",
    external_ids: "Checking external IDs on Accounts",
    sync_gaps: "Checking won deals reach finance",
    order_visibility: "Checking orders and invoices",
    erp_concerns: "Looking for ERP connections",
    api_usage: "Checking API usage",
    api_limit_monitoring: "Checking Salesforce limits",
    connected_apps: "Reviewing connected apps",
    integration_health: "Checking failed background jobs",
    bi_integration: "Looking for BI connections",
    data_extraction: "Checking very large objects",
    storage: "Checking storage",
    reporting_consistency: "Checking for duplicate reports",
}
