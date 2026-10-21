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
    ctx.metric("Marketing integration status", 0 if found else 1, "count", "lower-better", 100 if found else 55,
               how="We look through your installed packages and connected apps for a known marketing platform, such as Account Engagement (Pardot), HubSpot, Marketo or Marketing Cloud. 0 means one was found, 1 means none was.",
               rule="100 when a marketing platform is connected, 55 when none is found.",
               criteria=[
                   ("What we inspect", f"{len(_connected(ctx)):,} installed packages and connected apps in your org"),
                   ("Counts as marketing", "A name containing Pardot, Account Engagement, HubSpot, Marketo, Marketing Cloud, ET4AE, Mailchimp, Act-On, Eloqua, Constant Contact, Klaviyo, ZoomInfo or the word “pi” (ignoring case)"),
                   ("Found", ", ".join(found) if found else "None"),
                   ("What's counted", "0 when at least one marketing platform is found, 1 when none is"),
                   ("Flagged when", "No marketing platform is found (a low-severity setup problem)"),
               ])
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
        ctx.metric("Lead synchronization concerns", 0, "%", "lower-better", 60 if ctx.memo.get("marketing") else 100,
                   how="We count Leads created in the last 90 days. None were created, so there were no new leads to check.",
                   rule="100 when no marketing platform is connected; 60 when one is connected but no new leads arrived, since the sync may be broken.",
                   criteria=[
                       ("Records checked", "Leads created in the last 90 days: none"),
                       ("Marketing platform", ", ".join(ctx.memo.get("marketing") or []) or "None connected"),
                       ("What's counted", "There are no new leads to check, so the value is 0"),
                       ("Flagged when", "A marketing platform is connected but no Leads were created in 90 days (high severity: the sync may be broken)"),
                   ])
        return
    conds = ["CreatedDate = LAST_N_DAYS:90"]
    gaps = []
    if ctx.has_field("Lead", "Email"):
        gaps.append("Email = null")
    if ctx.has_field("Lead", "LeadSource"):
        gaps.append("LeadSource = null")
    bad = ctx.count("Lead", *conds, "(" + " OR ".join(gaps) + ")", recent=False) if gaps else 0
    score = rate_score(bad / total, 0.5)
    ctx.metric("Lead synchronization concerns", pct(bad, total), "%", "lower-better", score,
               how=f"Of the {total:,} Leads created in the last 90 days, the share that arrived without an email address or without a lead source.",
               rule="100 when every new lead has both, falling evenly to 0 when 50% of new leads are missing one of them.",
               records=("Lead", *conds, "(" + " OR ".join(gaps) + ")") if gaps else None, recent=False,
               columns=["Name", "Email", "LeadSource", "CreatedDate"], order="CreatedDate",
               criteria=[
                   ("Records checked", f"{total:,} Leads created in the last 90 days"),
                   ("Fields checked", " and ".join(n for n, c in (("Email", "Email = null"), ("Lead Source", "LeadSource = null")) if c in gaps) or "Neither Email nor Lead Source exists in this org"),
                   ("Incomplete lead", "Email is empty, or Lead Source is empty (either one is enough)"),
                   ("What's counted", f"{bad:,} of {total:,} new Leads ({pct(bad, total):.0f}%) are incomplete"),
                   ("Flagged when", "More than 2.5% of new Leads are incomplete (score below 95)"),
                   ("Records listed", "Every incomplete Lead created in the last 90 days, sorted by created date"),
               ])
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
        ctx.metric("Campaign visibility", 100.0, "%", "lower-better", 40,
                   how="We count Campaigns created in the last year. None were, so no new deal can be linked to a campaign (shown as 100%).",
                   rule="A fixed score of 40 when no Campaigns were created in the last year.",
                   criteria=[
                       ("Records checked", f"Campaigns created in the last 365 days: none. Opportunities created in that time: {new_opps:,}"),
                       ("What's counted", "With no campaigns, no new deal can be linked to one, so the value is 100%"),
                       ("Flagged when", "No Campaigns were created in the last year"),
                   ])
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
    ctx.metric("Campaign visibility", pct(no_campaign, new_opps), "%", "lower-better", score,
               how=f"Of the {new_opps:,} Opportunities created in the last year, the share with no Primary Campaign Source. {campaigns:,} campaign(s) were created in that time.",
               rule="100 when every new deal is linked to a campaign, falling evenly to 0 when 100% of them have none. A problem is raised when the score is below 80.",
               records=("Opportunity", "CreatedDate = LAST_N_DAYS:365", "CampaignId = null") if ctx.has_field("Opportunity", "CampaignId") else ("Opportunity", "CreatedDate = LAST_N_DAYS:365"),
               recent=False,
               columns=["Name", "CampaignId", "LeadSource", "StageName", "CloseDate", "CreatedDate"], order="CreatedDate",
               criteria=[
                   ("Records checked", f"{new_opps:,} Opportunities created in the last 365 days"),
                   ("Campaigns run", f"{campaigns:,} Campaigns created in the same 365 days"),
                   ("Not linked", "Primary Campaign Source is empty" if ctx.has_field("Opportunity", "CampaignId") else "This org has no Primary Campaign Source field, so every new deal counts as not linked"),
                   ("What's counted", f"{no_campaign:,} of {new_opps:,} new deals ({pct(no_campaign, new_opps):.0f}%) have no campaign"),
                   ("Flagged when", "More than 20% of new deals have no campaign (score below 80)"),
                   ("Records listed", "Every Opportunity created in the last 365 days with no Primary Campaign Source, sorted by created date"),
               ])
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
    ctx.metric("Integration configuration gaps", len(gaps), "count", "lower-better", [100, 60, 30][len(gaps)],
               how="We look at active users whose name or profile suggests an integration (for example “integration”, “API” or “sync”) and count two gaps: outside systems are connected but there is no such user, and integration users have the System Administrator profile.",
               rule="100 with no gaps, 60 with one gap, 30 with both.",
               criteria=[
                   ("Users checked", f"{len(users):,} active standard users (up to 2,000)"),
                   ("Integration user", "Name or profile contains integration, API, sync, connector, MuleSoft, Boomi, HubSpot, Pardot, Marketo, Zapier or Workato (ignoring case)"),
                   ("Integration users found", f"{len(integ)}" + (": " + ", ".join(u.get("Name") or "" for u in integ[:5]) + (" …" if len(integ) > 5 else "") if integ else "")),
                   ("Outside systems connected", "Yes (a marketing, ERP or BI tool was found)" if has_integrations else "No marketing, ERP or BI tool found"),
                   ("Gap 1", "Outside systems are connected but there is no integration user"),
                   ("Gap 2", f"An integration user has the System Administrator profile ({len(admin_integ)} found)"),
                   ("What's counted", f"{len(gaps)} gap(s)" + (": " + ", ".join(gaps) if gaps else "")),
                   ("Flagged when", "Each gap raises its own problem (medium for no integration user, high for admin rights)"),
               ])


# ---------------------------------------------------------------- area 19: ERP / finance & order flow

_ERP_FIELD = re.compile(r"erp|netsuite|\bsap\b|order.?(id|number|no)|invoice|external|billing.?id|finance", re.I)


def external_ids(ctx: Ctx) -> None:
    fields = ctx.fields("Account")
    ext = [f for f in fields.values() if f.get("externalId") and f.get("filterable")]
    total = ctx.total("Account")
    if not ext:
        ctx.metric("Missing external identifiers", 100.0 if total else 0.0, "%", "lower-better", 45 if total else 100,
                   how="We look for an External ID field on Account. There isn’t one, so no Account can be matched to other systems (shown as 100% when you have Accounts).",
                   rule="A fixed score of 45 when Accounts exist but there’s no External ID field; 100 when there are no Accounts.",
                   criteria=[
                       ("What we inspect", f"All {len(fields):,} fields on Account, looking for one marked External ID that can be filtered on"),
                       ("Records checked", f"{total:,} Accounts" + (f" changed in the last {ctx.scope.lookback_days} days" if ctx.scope.lookback_days else "")),
                       ("What's counted", "There is no External ID field, so 100% of Accounts are missing one" if total else "There are no Accounts, so nothing is missing"),
                       ("Flagged when", "Account has no External ID field"),
                   ])
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
    ctx.metric("Missing external identifiers", pct(missing, total), "%", "lower-better", score,
               how=f"Of your {total:,} Accounts, the share with the External ID field “{f.get('label') or f['name']}” left empty.",
               rule="100 when every Account has it filled in, falling evenly to 0 when 90% are empty. A problem is raised when the score is below 85.",
               records=("Account", f"{f['name']} = null"),
               columns=[f["name"], "Name", "Type", "OwnerId", "CreatedDate"], order="Name",
               criteria=[
                   ("Records checked", f"{total:,} Accounts" + (f" changed in the last {ctx.scope.lookback_days} days" if ctx.scope.lookback_days else "")),
                   ("Field used", f"{f.get('label') or f['name']} ({f['name']})" + (f", the first of {len(ext)} External ID fields" if len(ext) > 1 else "")),
                   ("Missing", "The field is empty"),
                   ("What's counted", f"{missing:,} of {total:,} Accounts ({pct(missing, total):.0f}%) have it empty"),
                   ("Flagged when", "More than 13.5% of Accounts have it empty (score below 85)"),
                   ("Records listed", "Every Account with the field empty, sorted by name"),
               ])
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
        ctx.metric("Potential synchronization gaps", 0, "count", "lower-better", 70 if total else 100,
                   how="We look for an ERP or order reference field on Opportunity, or Orders linked to deals. Neither exists, so won deals can’t be checked (shown as 0).",
                   rule="A fixed score of 70 when deals were won in the last 90 days but can’t be traced; 100 when no deals were won.",
                   criteria=[
                       ("Records checked", f"{total:,} Opportunities won in the last 90 days"),
                       ("ERP reference field", "None: no custom, filterable Opportunity field has ERP, NetSuite, SAP, Order ID/Number/No, Invoice, External, Billing ID or Finance in its name or label"),
                       ("Orders", "The Order object (with a link to Opportunity) isn’t available"),
                       ("What's counted", "Nothing can be traced, so the value is 0"),
                       ("Flagged when", "Deals were won in the last 90 days but can’t be traced (a low-severity setup problem)"),
                   ])
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
    ctx.metric("Potential synchronization gaps", n, "count", "lower-better", score,
               how=f"Of the {total:,} Opportunities won in the last 90 days, the number with {how}, which suggests they never reached finance or billing.",
               rule="100 when every won deal is traced, falling evenly to 0 when 50% of won deals have no trace.",
               records=("Opportunity", *won, gap_cond), recent=False,
               columns=([ref["name"]] if ref is not None else []) + ["Name", "Amount", "StageName", "CloseDate", "OwnerId"], order="CloseDate",
               criteria=[
                   ("Records checked", f"{total:,} Opportunities won in the last 90 days"),
                   ("Trace used", f"The {ref.get('label') or ref['name']} field ({ref['name']})" if ref is not None else "A linked Order (an Order whose Opportunity is this deal)"),
                   ("ERP field matching", "A custom, filterable Opportunity field whose name or label contains ERP, NetSuite, SAP, Order ID/Number/No, Invoice, External, Billing ID or Finance. Fields without “external” in the name are preferred. If none exists, we use Orders."),
                   ("No trace", "The field is empty" if ref is not None else "No Order is linked to the deal"),
                   ("What's counted", f"{n:,} of {total:,} won deals ({pct(n, total):.0f}%) have {how}"),
                   ("Flagged when", "More than 2.5% of won deals have no trace (score below 95)"),
                   ("Records listed", "Every deal won in the last 90 days with no trace, sorted by close date"),
               ])
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
    ctx.metric("Order integration visibility", issues, "count", "lower-better", 100 if not issues else 65,
               how="We check for Orders created in the last year, or custom objects for invoices, orders, billing, payments, subscriptions, contracts or quotes. 0 means finance data is present, 1 means none was found.",
               rule="100 when order or invoice data is present, 65 when none is found.",
               criteria=[
                   ("Orders checked", f"{orders:,} Orders created in the last 365 days" if ctx.has_object("Order") else "The Order object isn’t available in this org"),
                   ("Finance objects", "Custom objects whose name contains invoice, order, billing, payment, subscription, contract or quote (not sharing, history or feed objects)"),
                   ("Found", ", ".join(o["name"] for o in custom[:8]) + (" …" if len(custom) > 8 else "") if custom else "None"),
                   ("What's counted", "0 when Orders or a finance object exist, 1 when neither does"),
                   ("Flagged when", "No Orders in the last year and no finance objects (a low-severity setup problem)"),
               ])
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
    ctx.metric("ERP integration concerns", concern, "count", "lower-better", 100 if not concern else 60,
               how="We look through your installed packages and connected apps for an ERP, billing or integration platform (such as MuleSoft, Boomi, NetSuite or QuickBooks). 1 means deals were won in the last year but no such system is connected.",
               rule="100 when one is connected or no deals were won in the last year, 60 otherwise.",
               criteria=[
                   ("What we inspect", f"{len(_connected(ctx)):,} installed packages and connected apps in your org"),
                   ("Counts as ERP or integration", "A name containing MuleSoft, Boomi, NetSuite, SAP, QuickBooks, Xero, Sage, Dynamics, Oracle, Workato, Celigo, Jitterbit, Informatica, Zapier, Make, Tray.io, Chargebee, Zuora, Stripe or Avalara (ignoring case)"),
                   ("Found", ", ".join(found) if found else "None"),
                   ("Won deals", f"{won:,} Opportunities won in the last 365 days"),
                   ("What's counted", "1 when deals were won but no ERP or integration platform is found, otherwise 0"),
                   ("Flagged when", "Deals were won in the last year but no ERP or integration platform is found (a low-severity setup problem)"),
               ])
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
    ctx.metric("API usage", used, "%", "lower-better", score,
               how="The share of today’s daily API call allowance that is already used, as reported by Salesforce.",
               rule="100 up to 50% used, then 1.8 points lower for every percent above 50, never below 10. A problem is raised when more than 70% is used.",
               criteria=[
                   ("What we inspect", "The Daily API Requests limit reported by Salesforce (every API call from apps, integrations and tools)"),
                   ("What's counted", f"{used:.0f}% used ({_limits(ctx)['DailyApiRequests']['Max'] - _limits(ctx)['DailyApiRequests'].get('Remaining', _limits(ctx)['DailyApiRequests']['Max']):,} of {_limits(ctx)['DailyApiRequests']['Max']:,} calls)"),
                   ("Scoring", "No penalty up to 50% used; above that, 1.8 points off for every percent, never below 10"),
                   ("Flagged when", "More than 70% of the daily allowance is used"),
               ])
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
    ctx.metric("API limit monitoring", len(close), "count", "lower-better", 100 - 20 * min(len(close), 4),
               how="The number of other Salesforce limits that are 80% or more used: async Apex jobs, Bulk API batches and query jobs, streaming and platform events, workflow, single and mass emails, and time-based workflow.",
               rule="100 when none are close, 20 points lower for each limit that is, down to 20 at four or more.",
               criteria=[
                   ("Limits watched", ", ".join(_WATCHED_LIMITS.values())),
                   ("Current use", ", ".join(f"{lbl} {pu:.0f}%" for k, lbl in _WATCHED_LIMITS.items() if (pu := _used_pct(limits.get(k))) is not None) or "Salesforce reported none of these limits"),
                   ("Close to the limit", "80% or more used"),
                   ("What's counted", f"{len(close)} limit(s) close to the maximum" + (": " + ", ".join(f"{label} ({u:.0f}%)" for label, u in close) if close else "")),
                   ("Flagged when", "Any watched limit is 80% or more used (high severity if any is 95% or more)"),
               ])
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
        ctx.metric("Connected application visibility", 0, "count", "lower-better", 85,
                   how="We couldn’t read when each connected app last used its access, so unused apps can’t be counted (shown as 0).",
                   rule="A fixed score of 85 when app usage can’t be read.",
                   criteria=[
                       ("What we inspect", "OAuth usage (when each connected app last used its access) couldn’t be read with this user"),
                       ("Apps seen", f"{len(names):,} installed packages and connected apps"),
                       ("What's counted", "Unused apps can’t be counted, so the value is 0"),
                       ("Flagged when", "Never: no problem is raised without usage data"),
                   ])
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
    ctx.metric("Connected application visibility", len(stale), "count", "lower-better", score,
               how=f"Of the {len(last)} connected apps that hold access to your org, the number that haven’t been used in more than 90 days.",
               rule="100 when every app has been used recently, falling evenly to 0 when 60% of apps are unused.",
               criteria=[
                   ("Records checked", f"{len(tokens):,} OAuth access grants (up to 2,000, most recently used first) across {len(last):,} apps"),
                   ("Last used", "The most recent use across all of an app’s grants"),
                   ("Unused", "Not used in more than 90 days, or never used"),
                   ("What's counted", f"{len(stale)} of {len(last)} apps are unused" + (": " + ", ".join(stale[:6]) + (" …" if len(stale) > 6 else "") if stale else "")),
                   ("Flagged when", "At least one app is unused (medium severity at 3 or more, otherwise low)"),
               ])
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
    ctx.metric("Integration health indicators", failed, "count", "lower-better", score,
               how=f"Of the {total:,} background (Apex) jobs that ran in the last 7 days, the number that failed.",
               rule="100 when no jobs failed, falling evenly to 0 when 20% of jobs failed. A problem is raised whenever any job failed.",
               records=("AsyncApexJob", "Status = 'Failed'", "CreatedDate = LAST_N_DAYS:7"), recent=False,
               columns=["ApexClassId", "JobType", "Status", "ExtendedStatus", "NumberOfErrors", "CreatedDate"], order="CreatedDate",
               criteria=[
                   ("Records checked", f"{total:,} background (Apex) jobs created in the last 7 days: batch, queueable, future and scheduled jobs"),
                   ("Failed job", "Status is Failed (aborted, queued or still-running jobs don’t count)"),
                   ("What's counted", f"{failed:,} of {total:,} jobs ({pct(failed, total):.0f}%) failed"),
                   ("Flagged when", "Any job failed in the last 7 days"),
                   ("Records listed", "Every failed job from the last 7 days, sorted by created date"),
               ])
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
    ctx.metric("BI integration visibility", 0 if found else 1, "count", "lower-better", 100 if found else 75,
               how="We look through your installed packages and connected apps for a BI or data tool, such as Tableau, Power BI, Snowflake, Fivetran or CRM Analytics. 0 means one was found, 1 means none was.",
               rule="100 when a BI or data tool is connected, 75 when none is found.",
               criteria=[
                   ("What we inspect", f"{len(_connected(ctx)):,} installed packages and connected apps in your org"),
                   ("Counts as BI or data", "A name containing Tableau, Power BI, Fivetran, Snowflake, Stitch, Informatica, Domo, Looker, Qlik, CRM Analytics, Einstein Analytics, Wave, Segment, Hightouch, Census, Airbyte, BigQuery or Redshift (ignoring case)"),
                   ("Found", ", ".join(found) if found else "None"),
                   ("What's counted", "0 when at least one BI or data tool is found, 1 when none is"),
                   ("Flagged when", "No BI or data tool is found (a low-severity setup problem)"),
               ])
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
    ctx.metric("Data extraction concerns", len(big), "count", "lower-better", 100 if not big else 80 if len(big) <= 2 else 60,
               how="The number of business objects holding over 1,000,000 records, which are slow and API-heavy to extract. Salesforce’s own setup and system objects are left out.",
               rule="100 with none, 80 with one or two, 60 with three or more.",
               criteria=[
                   ("Records checked", f"Record counts Salesforce reports for {len(counts):,} objects"),
                   ("Very large", "1,000,000 records or more"),
                   ("Left out", "Salesforce’s own setup, permission, sharing, history, feed and change-event objects, and system objects"),
                   ("What's counted", f"{len(big)} large object(s)" + (": " + ", ".join(f"{n} ({c:,})" for n, c in big[:6]) + (" …" if len(big) > 6 else "") if big else "")),
                   ("Flagged when", "At least one business object has 1,000,000 or more records (a low-severity note)"),
               ])
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
    ctx.metric("Storage utilization indicators", used, "%", "lower-better", score,
               how="How full your storage is: whichever is higher of data storage and file storage, as a share of what your org is allowed.",
               rule="100 up to 60% full, then 2.2 points lower for every percent above 60, never below 10. A problem is raised at 75% full or more.",
               criteria=[
                   ("What we inspect", "The data storage and file storage limits reported by Salesforce"),
                   ("Data storage", f"{data:.0f}% used" if data is not None else "Not reported"),
                   ("File storage", f"{files:.0f}% used" if files is not None else "Not reported"),
                   ("What's counted", f"The higher of the two: {used:.0f}%"),
                   ("Scoring", "No penalty up to 60% full; above that, 2.2 points off for every percent, never below 10"),
                   ("Flagged when", "Either storage is 75% full or more"),
               ])
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
    ctx.metric("Reporting consistency concerns", extra, "count", "lower-better", score,
               how=f"Across your {len(reports):,} reports, the number of extra copies that share a name with another report (ignoring capital letters and spaces at the ends).",
               rule="100 when every report name is unique, falling evenly to 0 when extra copies make up 60% of reports. A problem is raised when the score is below 90.",
               records=("Report", ctx.ids_in([r["Id"] for r in reports if (r.get("Name") or "").strip().lower() in dupes])) if dupes else None,
               recent=False,
               columns=["Name", "FolderName", "LastRunDate", "CreatedDate"], order="Name",
               criteria=[
                   ("Records checked", f"{len(reports):,} reports you can see (not from installed packages, up to 10,000)"),
                   ("Name matching", "Ignores upper/lower case and spaces at the start or end. So “Pipeline ” and “pipeline” match."),
                   ("What's counted", f"{extra:,} extra copies across {len(dupes):,} repeated names (each group minus the one you keep)"),
                   ("Flagged when", "Extra copies are more than 6% of all reports (score below 90)"),
                   ("Records listed", "Every report in a repeated-name group, including the one you’d keep, sorted by name so copies sit together (up to 200)"),
               ])
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
