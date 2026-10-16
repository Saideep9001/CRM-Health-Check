"""Category 4 — User Adoption & Enablement (areas 12 to 14).

Unlike metadata-only scanners, adoption here is tied to what people actually do with
their records: a rep who rarely logs in AND whose deals are going stale is a coaching
priority, and an unused paid licence is money. Everything is read-only SOQL; setup
reads (home pages, help text) are skipped with a note when the user can't view setup.
Indicator labels match src/config/categories.ts exactly.
"""
from ..salesforce.errors import SalesforceAuthExpired, SalesforceError
from .core import Ctx, FindingDraft, Unavailable, pct, range_score, rate_score
from .workflows import _BOT_NAME, _NON_REP_PROFILE, _days_since, activity_by_owner, sales_reps

# Estimate for an unused licence: Sales Cloud Enterprise list price per user per month (USD).
# Shown as an assumption next to the number — real contracts vary. Only full "Salesforce" licences are priced;
# Platform, Field Service, partner and other licence types cost different amounts, so they're counted but not priced.
LICENSE_PER_MONTH = 165
PRICED_LICENSES = {"Salesforce"}
CORE = ("Account", "Contact", "Lead", "Opportunity")
OPEN_OPPS = "IsClosed = false"

SETTING_FIX = {
    "Profiles used by only one or two people": "/lightning/setup/EnhancedProfiles/home",
    "Too many people can change all data": "/lightning/setup/PermSets/home",
    "Everyone can edit every deal": "/lightning/setup/SecuritySharing/home",
    "Everyone can edit every lead": "/lightning/setup/SecuritySharing/home",
    "Permission sets nobody uses": "/lightning/setup/PermSets/home",
    "The role hierarchy is very deep": "/lightning/setup/Roles/home",
    "Custom fields without help text": "/lightning/setup/ObjectManager/home",
    "No custom home page for the sales team": "/lightning/setup/FlexiPageList/home",
    "Cluttered or unused list views": "/lightning/o/Opportunity/list",
}


def _setting(ctx: Ctx, name: str, description: str, why: str, action: str, severity: str = "medium", affected: int = 0, obj: str | None = None) -> None:
    ctx.findings.append(FindingDraft(
        area_id=ctx.area_id, name=name, severity=severity,  # type: ignore[arg-type]
        affected_records=affected, description=description, why_it_matters=why,
        business_impact="People avoid tools that are confusing or that they don’t trust, and data quality follows.",
        recommended_action=action, object_name=obj,
        fix_url=ctx.setup_url(SETTING_FIX[name]) if name in SETTING_FIX else None,
    ))


def _money(v: float) -> str:
    return f"{v:,.0f}"


def people(ctx: Ctx) -> list[dict]:
    """Active, licensed people (not integration or automated users)."""
    if "people" in ctx.memo:
        return ctx.memo["people"]
    if not ctx.has_object("User"):
        raise Unavailable("Users can’t be read in this org.")
    want = ["LastLoginDate", "UserRoleId", "UserPreferencesLightningExperiencePreferred"]
    cols = ["Id", "Name", "Profile.Name", "Profile.UserLicense.Name"] + [f for f in want if ctx.has_field("User", f, None)]
    rows = ctx.rows(f"SELECT {', '.join(cols)} FROM User WHERE IsActive = true AND UserType = 'Standard' ORDER BY Name", limit=5000)
    out = [u for u in rows
           if not _BOT_NAME.search(u.get("Name") or "") and not _NON_REP_PROFILE.search((u.get("Profile") or {}).get("Name") or "")]
    ctx.memo["people"] = out
    ctx.totals["User"] = len(out)
    return out


def _per_owner(ctx: Ctx, where: str, amount: bool = False) -> dict[str, tuple[int, float]]:
    """{owner id: (records, total amount)} for open deals matching `where`."""
    if not ctx.has_object("Opportunity"):
        return {}
    total = ", SUM(Amount) a" if amount and ctx.has_field("Opportunity", "Amount") else ""
    recs = ctx.sf.query(f"SELECT OwnerId o, COUNT(Id) c{total} FROM Opportunity WHERE {where} GROUP BY OwnerId LIMIT 2000").get("records", [])
    return {str(r.get("o")): (int(r.get("c") or 0), float(r.get("a") or 0)) for r in recs}


def _names(items: list[str], n: int = 6) -> str:
    return ", ".join(items[:n]) + (f" and {len(items) - n} more" if len(items) > n else "")


# ---------------------------------------------------------------- area 12: logins, low adopters, training

def inactive_users(ctx: Ctx) -> None:
    users = people(ctx)
    if not users or "LastLoginDate" not in users[0]:
        raise Unavailable("Login dates can’t be read for this user.")
    idle = [u for u in users if (d := _days_since(u.get("LastLoginDate"))) is None or d > 30]
    rate = len(idle) / len(users) if users else 0
    score = rate_score(rate, 0.3)
    ctx.metric("Inactive users", len(idle), "count", "lower-better", score)
    full = [u for u in idle if ((u.get("Profile") or {}).get("UserLicense") or {}).get("Name") in PRICED_LICENSES]
    cost = len(full) * LICENSE_PER_MONTH * 12
    never = sum(1 for u in idle if not u.get("LastLoginDate"))
    priced = (f" {len(full)} of them {'is' if len(full) == 1 else 'are'} on full Salesforce licences — at about ${LICENSE_PER_MONTH}/user/month "
              f"(Sales Cloud Enterprise list price) that’s roughly ${_money(cost)} a year." if full else "")
    ctx.finding(
        name="Paid licenses not being used",
        obj="User", records=("User", ctx.ids_in([u["Id"] for u in idle])), recent=False,
        score=score, affected=len(idle), value=cost or None,
        description=f"{len(idle)} of {len(users)} active people haven’t logged in for over 30 days"
        + (f" ({never} never have)" if never else "") + f": {_names([u['Name'] for u in idle])}." + priced,
        why="Every active user is a paid licence, and people who don’t log in leave their records unmanaged.",
        impact="Wasted licence spend, and Accounts, Leads and deals that nobody is looking after.",
        action="Confirm who still needs access: freeze or deactivate leavers, reassign their records, and re-train people who should be using it.",
        fix="/lightning/setup/ManageUsers/home",
    )


def login_activity(ctx: Ctx) -> None:
    users = people(ctx)
    if not users:
        raise Unavailable("No licensed users found.")
    weekly = sum(1 for u in users if (d := _days_since(u.get("LastLoginDate"))) is not None and d <= 7)
    share = pct(weekly, len(users))
    score = range_score(share, 40, 90)
    ctx.metric("Login activity", share, "%", "higher-better", score)
    if score < 80:
        _setting(
            ctx, "Few people log in each week",
            f"Only {weekly} of {len(users)} people ({share:.0f}%) logged in during the last 7 days.",
            "If Salesforce isn’t part of the weekly routine, it won’t hold the truth about customers and deals.",
            "Run pipeline reviews and 1:1s from Salesforce dashboards, make it the only place deals are updated, and add the mobile app.",
            severity="high" if score < 40 else "medium", affected=len(users) - weekly, obj="User",
        )


def low_adoption(ctx: Ctx) -> None:
    """Reps whose own pipeline shows they aren't using Salesforce: little activity and mostly stale deals."""
    reps = sales_reps(ctx)
    if not reps:
        raise Unavailable("No sales reps own open deals or leads.")
    acts = activity_by_owner(ctx, 30)
    open_ = _per_owner(ctx, OPEN_OPPS, amount=True)
    stale = _per_owner(ctx, f"{OPEN_OPPS} AND LastModifiedDate < LAST_N_DAYS:30", amount=True)
    low, low_ids, at_risk, stale_deals = [], [], 0.0, 0
    for uid, name in reps.items():
        n_open, _ = open_.get(uid, (0, 0.0))
        n_stale, amt = stale.get(uid, (0, 0.0))
        few_acts = acts.get(uid, 0) < 5
        mostly_stale = n_open >= 3 and n_stale / n_open >= 0.5
        if (few_acts and n_open > 0) or mostly_stale:
            low.append(f"{name} ({acts.get(uid, 0)} activities in 30 days, {n_stale} of {n_open} deals not updated in 30 days)")
            low_ids.append(uid)
            at_risk += amt
            stale_deals += n_stale
    score = rate_score(len(low) / len(reps), 0.4)
    ctx.metric("Low adoption indicators", len(low), "count", "lower-better", score)
    ctx.finding(
        name="Reps whose pipeline is going stale",
        obj="User", records=("Opportunity", OPEN_OPPS, "LastModifiedDate < LAST_N_DAYS:30", f"OwnerId IN ({', '.join(repr(i) for i in low_ids[:200])})" if low_ids else "Id = null"),
        recent=False, score=score, affected=len(low), value=at_risk or None,
        description=f"{len(low)} of {len(reps)} reps show low adoption, measured by their own records — {stale_deals} of their open deals "
        f"haven’t been updated in 30 days: " + "; ".join(low[:5]) + (" …" if len(low) > 5 else "") + ".",
        why="Low activity plus untouched deals means the pipeline these reps report isn’t real — and managers can’t coach what they can’t see.",
        impact="Forecasts built on stale deals, and revenue at risk on deals nobody is working.",
        action="Review these reps’ deals together in the next 1:1, close out dead deals, and set a weekly ‘update your pipeline’ habit with a list view of untouched deals.",
    )


def training_opportunities(ctx: Ctx) -> None:
    """Reps whose open deals are often overdue or have no next step — a hygiene coaching list."""
    reps = sales_reps(ctx)
    if not reps or not ctx.has_object("Opportunity"):
        raise Unavailable("No sales reps own open deals.")
    sloppy_cond = "CloseDate < TODAY OR NextStep = null" if ctx.has_field("Opportunity", "NextStep") else "CloseDate < TODAY"
    open_ = _per_owner(ctx, OPEN_OPPS)
    sloppy = _per_owner(ctx, f"{OPEN_OPPS} AND ({sloppy_cond})")
    coach = []
    for uid, name in reps.items():
        n_open = open_.get(uid, (0, 0))[0]
        n_bad = sloppy.get(uid, (0, 0))[0]
        if n_open >= 3 and n_bad / n_open >= 0.4:
            coach.append((n_bad / n_open, f"{name} ({n_bad} of {n_open} deals overdue or without a next step)"))
    coach.sort(reverse=True)
    score = rate_score(len(coach) / len(reps), 0.5)
    ctx.metric("Training opportunities", len(coach), "count", "lower-better", score)
    if coach:
        _setting(
            ctx, "Reps who need coaching on deal updates",
            f"{len(coach)} reps let many of their deals go out of date: " + "; ".join(t for _, t in coach[:5]) + (" …" if len(coach) > 5 else "") + ".",
            "Close dates and next steps drive the forecast and reminders; when they’re missing, deals slip silently.",
            "Give these reps a short refresher on updating close dates and next steps, add In-App Guidance on the Opportunity page, and track the share each week.",
            severity="medium" if score >= 40 else "high", affected=len(coach), obj="User",
        )


# ---------------------------------------------------------------- area 13: roles, permissions, profiles

def profile_complexity(ctx: Ctx) -> None:
    users = people(ctx)
    by_profile: dict[str, int] = {}
    for u in users:
        p = (u.get("Profile") or {}).get("Name") or "Unknown"
        by_profile[p] = by_profile.get(p, 0) + 1
    tiny = sorted(p for p, n in by_profile.items() if n <= 2)
    score = 100 if len(users) < 10 else max(0, 100 - 12 * max(0, len(tiny) - 2))
    ctx.metric("Profile complexity", len(by_profile), "count", "lower-better", score)
    if score < 80:
        _setting(
            ctx, "Profiles used by only one or two people",
            f"{len(by_profile)} profiles are in use for {len(users)} people; {len(tiny)} of them have only one or two people: {_names(tiny)}.",
            "Every extra profile is another place permissions can drift, which makes access hard to reason about and audit.",
            "Move to a few base profiles plus permission sets and permission set groups for extra access (Salesforce’s recommended model).",
            severity="low" if score >= 60 else "medium", affected=len(tiny), obj="User",
        )


def excessive_permissions(ctx: Ctx) -> None:
    users = people(ctx)
    ids = {u["Id"] for u in users}
    try:
        rows = ctx.rows("SELECT AssigneeId FROM PermissionSetAssignment WHERE PermissionSet.PermissionsModifyAllData = true AND Assignee.IsActive = true", limit=5000)
    except SalesforceAuthExpired:
        raise
    except SalesforceError as exc:  # some editions can't read permission assignments
        raise Unavailable(f"Couldn’t read permission assignments ({exc}).") from None
    admins = sorted({r["AssigneeId"] for r in rows if r.get("AssigneeId") in ids})
    allowed = max(2, round(0.1 * len(users)))
    extra = max(0, len(admins) - allowed)
    score = 100 if not extra else max(0, 100 - 15 * extra)
    ctx.metric("Excessive permissions", len(admins), "count", "lower-better", score)
    names = [u["Name"] for u in users if u["Id"] in set(admins)]
    ctx.finding(
        name="Too many people can change all data",
        obj="User", records=("User", ctx.ids_in(admins)), recent=False,
        score=score, affected=len(admins),
        description=f"{len(admins)} of {len(users)} people have “Modify All Data” (full admin power): {_names(names)}. "
        f"For a team this size, {allowed} or fewer is normal.",
        why="Anyone with Modify All Data can delete or mass-change any record, bypassing sharing — mistakes and leaks are one click away.",
        impact="Higher risk of accidental mass changes, data leaks, and failed security audits.",
        action="Keep Modify All Data for a small admin group; give everyone else only what their job needs through permission sets.",
        fix=SETTING_FIX["Too many people can change all data"],
    )


def role_hierarchy(ctx: Ctx) -> None:
    users = people(ctx)
    reps = sales_reps(ctx)
    no_role = [u for u in users if u["Id"] in reps and "UserRoleId" in u and not u.get("UserRoleId")]
    issues = len(no_role)
    roles = ctx.rows("SELECT Id, Name, ParentRoleId FROM UserRole", limit=5000) if ctx.has_object("UserRole") else []
    parent = {r["Id"]: r.get("ParentRoleId") for r in roles}

    def depth(rid: str) -> int:
        d, seen = 0, set()
        while rid and rid not in seen:
            seen.add(rid)
            rid, d = parent.get(rid), d + 1
        return d

    deepest = max((depth(r) for r in parent), default=0)
    if deepest > 7:
        issues += 1
        _setting(
            ctx, "The role hierarchy is very deep",
            f"The role hierarchy is {deepest} levels deep.",
            "Deep hierarchies slow down sharing calculations and make it hard to see who can see what.",
            "Flatten the hierarchy to reflect reporting lines that matter for visibility (usually 4–6 levels) and use teams or sharing rules for exceptions.",
            severity="low",
        )
    score = rate_score(len(no_role) / len(reps), 0.3) if reps else 100
    if deepest > 7:
        score = min(score, 75)
    ctx.metric("Role hierarchy issues", issues, "count", "lower-better", score)
    ctx.finding(
        name="Sales users without a role",
        obj="User", records=("User", ctx.ids_in([u["Id"] for u in no_role])), recent=False,
        score=score, affected=len(no_role),
        description=f"{len(no_role)} of {len(reps)} reps have no role: {_names([u['Name'] for u in no_role])}.",
        why="Without a role, a rep’s deals don’t roll up to their manager — they’re missing from forecasts and from managers’ views.",
        impact="Incomplete forecasts and managers who can’t see their team’s pipeline.",
        action="Give every rep a role in the hierarchy under their manager, and add a check to your new-user checklist.",
        fix="/lightning/setup/ManageUsers/home",
    )


def permission_config(ctx: Ctx) -> None:
    concerns = 0
    org_fields = [f for f in ("DefaultOpportunityAccess", "DefaultLeadAccess") if ctx.has_field("Organization", f, None)]
    if org_fields:
        org = (ctx.sf.query(f"SELECT {', '.join(org_fields)} FROM Organization").get("records") or [{}])[0]
        open_values = ("Edit", "ReadEditTransfer", "All")
        if org.get("DefaultOpportunityAccess") in open_values:
            concerns += 1
            _setting(ctx, "Everyone can edit every deal",
                     "Opportunities are Public Read/Write: every user can change every deal, including other reps’ amounts and stages.",
                     "Open edit access means anyone can change the forecast, by accident or not, with no owner accountability.",
                     "Set Opportunity sharing to Private or Public Read Only, and use the role hierarchy and opportunity teams for access.",
                     severity="medium", obj="Opportunity")
        if org.get("DefaultLeadAccess") in open_values:
            concerns += 1
            _setting(ctx, "Everyone can edit every lead",
                     "Leads are Public Read/Write/Transfer: any user can change or take any lead.",
                     "Reps can poach or overwrite each other’s leads, and routing rules lose their meaning.",
                     "Use Private or Public Read Only for Leads, and share through queues and assignment rules.",
                     severity="low", obj="Lead")
    if ctx.has_object("PermissionSet") and ctx.has_object("PermissionSetAssignment"):
        sets = ctx.rows("SELECT Id, Label FROM PermissionSet WHERE IsOwnedByProfile = false AND NamespacePrefix = null AND IsCustom = true", limit=2000)
        used = {str(r.get("p")) for r in ctx.sf.query(
            "SELECT PermissionSetId p, COUNT(Id) c FROM PermissionSetAssignment WHERE PermissionSet.IsOwnedByProfile = false GROUP BY PermissionSetId LIMIT 2000"
        ).get("records", [])}
        unused = sorted(s.get("Label") or s["Id"] for s in sets if s["Id"] not in used)
        if len(unused) >= 3:
            concerns += 1
            _setting(ctx, "Permission sets nobody uses",
                     f"{len(unused)} custom permission sets aren’t assigned to anyone: {_names(unused)}.",
                     "Unused permission sets clutter setup and make access reviews slower and error-prone.",
                     "Delete the ones nobody needs, or bundle the useful ones into permission set groups by job role.",
                     severity="low", affected=len(unused))
    ctx.metric("Permission configuration concerns", concerns, "count", "lower-better", 100 - 25 * min(concerns, 4))


# ---------------------------------------------------------------- area 14: help text, home page, list views, navigation

def help_text(ctx: Ctx) -> None:
    missing: dict[str, int] = {}
    total = 0
    for obj in CORE:
        if not ctx.has_object(obj):
            continue
        custom = [f for f in ctx.fields(obj).values() if f.get("custom") and not f.get("calculated")]
        total += len(custom)
        n = sum(1 for f in custom if not (f.get("inlineHelpText") or "").strip())
        if n:
            missing[obj] = n
    if not total:
        ctx.metric("Missing field help text", 0, "%", "lower-better", 100)
        return
    share = pct(sum(missing.values()), total)
    score = rate_score(share / 100, 1.0)
    ctx.metric("Missing field help text", share, "%", "lower-better", score)
    if score < 80:
        _setting(
            ctx, "Custom fields without help text",
            f"{sum(missing.values())} of {total} custom fields ({share:.0f}%) have no help text: "
            + ", ".join(f"{o} {n}" for o, n in missing.items()) + ".",
            "Without help text people guess what a field means, so the same field gets filled in different ways.",
            "Add a one-line help text to each custom field (what it’s for and an example), starting with fields used in reports and required fields.",
            severity="low" if score >= 40 else "medium", affected=sum(missing.values()),
        )


def home_page(ctx: Ctx) -> None:
    pages = ctx.setup("SELECT Id, MasterLabel FROM FlexiPage WHERE Type = 'HomePage'")
    concerns = 0 if pages else 1
    ctx.metric("Home page improvement opportunities", concerns, "count", "lower-better", 100 if pages else 60)
    if not pages:
        _setting(
            ctx, "No custom home page for the sales team",
            "The org uses Salesforce’s default home page — no custom Lightning home page has been built.",
            "The home page is the first thing reps see; a focused one (my deals closing this month, my tasks, key dashboard) makes the daily routine obvious.",
            "Build a Lightning home page per role with the rep’s pipeline, today’s tasks and one key dashboard, and assign it by profile.",
            severity="low",
        )


def list_views(ctx: Ctx) -> None:
    if not ctx.has_object("ListView"):
        raise Unavailable("List views can’t be read in this org.")
    cols = "Id, Name, SobjectType" + (", LastViewedDate" if ctx.has_field("ListView", "LastViewedDate", None) else "")
    rows = ctx.rows(f"SELECT {cols} FROM ListView WHERE SobjectType IN ('Account', 'Contact', 'Lead', 'Opportunity')", limit=5000)
    per: dict[str, list[dict]] = {}
    for r in rows:
        per.setdefault(r.get("SobjectType") or "", []).append(r)
    concerns = []
    for obj, views in per.items():
        never = [v for v in views if "LastViewedDate" in v and not v.get("LastViewedDate")]
        if len(views) > 25:
            concerns.append(f"{obj} has {len(views)} list views")
        if len(views) >= 8 and len(never) / len(views) >= 0.5:
            concerns.append(f"{len(never)} of {len(views)} {obj} list views have never been opened")
    ctx.metric("List view usability", len(concerns), "count", "lower-better", 100 - 20 * min(len(concerns), 5))
    if concerns:
        _setting(
            ctx, "Cluttered or unused list views",
            "; ".join(concerns) + ".",
            "Long lists of stale views make it hard for reps to find the one that matters, so they fall back to exports and spreadsheets.",
            "Delete unused views, keep a small shared set per role (e.g. ‘My deals closing this month’), and name them consistently.",
            severity="low", affected=len(concerns),
        )


def navigation(ctx: Ctx) -> None:
    users = people(ctx)
    if not users or "UserPreferencesLightningExperiencePreferred" not in users[0]:
        raise Unavailable("Can’t tell which experience people use.")
    classic = [u for u in users if u.get("UserPreferencesLightningExperiencePreferred") is False]
    score = rate_score(len(classic) / len(users), 0.3)
    ctx.metric("Navigation improvement opportunities", len(classic), "count", "lower-better", score)
    ctx.finding(
        name="People still using Salesforce Classic",
        obj="User", records=("User", ctx.ids_in([u["Id"] for u in classic])), recent=False,
        score=score, affected=len(classic),
        description=f"{len(classic)} of {len(users)} people have Salesforce Classic as their default: {_names([u['Name'] for u in classic])}.",
        why="Classic misses Path, Dynamic Forms, Kanban, In-App Guidance and most new features, so these people get a worse, slower experience.",
        impact="Inconsistent processes between teams and lower productivity; Classic gets no new features.",
        action="Switch these users to Lightning (Setup → Lightning Experience Transition Assistant), and remove the ‘Switch to Classic’ option once they’re trained.",
        fix="/lightning/setup/EnableLightningExperience/home",
    )


AREAS = {
    "area-12": [inactive_users, login_activity, low_adoption, training_opportunities],
    "area-13": [permission_config, profile_complexity, role_hierarchy, excessive_permissions],
    "area-14": [help_text, home_page, list_views, navigation],
}

STEP_LABELS = {
    inactive_users: "Finding unused licences",
    login_activity: "Checking weekly logins",
    low_adoption: "Comparing each rep’s activity with their pipeline",
    training_opportunities: "Finding reps who need coaching",
    permission_config: "Checking sharing and permission sets",
    profile_complexity: "Reviewing profiles",
    role_hierarchy: "Checking the role hierarchy",
    excessive_permissions: "Checking admin-level access",
    help_text: "Checking field help text",
    home_page: "Checking the home page",
    list_views: "Reviewing list views",
    navigation: "Checking Lightning vs. Classic",
}
