"""Category 5 — Quoting & Opportunity Product Management (areas 15 to 17).

Goes beyond configuration checks: it measures discount leakage on won deals (list
price vs. what was sold), finds big discounts that never went through approval, and
— for orgs on Salesforce CPQ, which is no longer sold to new customers — sizes the
move to Revenue Cloud. Works with standard Quotes and with CPQ (SBQQ) quotes.
Indicator labels match src/config/categories.ts exactly.
"""
from collections import defaultdict

from ..salesforce.errors import SalesforceAuthExpired, SalesforceError
from .core import Ctx, FindingDraft, Unavailable, pct, rate_score
from .workflows import _days_since

OPEN_OPPS = "IsClosed = false"
BIG_DISCOUNT = 0.20  # a line sold 20%+ below list price
APPROVAL_LATE_DAYS = 3

SETTING_FIX = {
    "No products set up": "/lightning/o/Product2/home",
    "The standard price book is turned off": "/lightning/o/Pricebook2/home",
    "Price books with no products": "/lightning/o/Pricebook2/home",
    "Products priced at zero": "/lightning/o/Pricebook2/home",
    "Quotes aren’t turned on": "/lightning/setup/QuotesSettings/home",
    "Salesforce CPQ is no longer sold — plan the move to Revenue Cloud": "/lightning/setup/ImportedPackage/home",
    "No approval process for discounts": "/lightning/setup/ApprovalProcesses/home",
}


def _setting(ctx: Ctx, name: str, description: str, why: str, action: str, severity: str = "medium", affected: int = 0, obj: str | None = None) -> None:
    ctx.findings.append(FindingDraft(
        area_id=ctx.area_id, name=name, severity=severity,  # type: ignore[arg-type]
        affected_records=affected, description=description, why_it_matters=why,
        business_impact="Inaccurate pricing, slower quotes, and revenue given away without anyone deciding to.",
        recommended_action=action, object_name=obj,
        fix_url=ctx.setup_url(SETTING_FIX[name]) if name in SETTING_FIX else None,
    ))


def _money(v: float | None) -> str:
    return f"{v:,.0f}" if v else "0"


def _safe_count(ctx: Ctx, obj: str, *conds: str) -> int | None:
    """COUNT() that returns None when the org rejects the query (e.g. a relationship it doesn't have)."""
    try:
        return ctx.count(obj, *conds, recent=False)
    except SalesforceAuthExpired:
        raise
    except (SalesforceError, Unavailable):
        return None


def _need_products(ctx: Ctx) -> None:
    if not ctx.has_object("Opportunity") or not ctx.has_field("Opportunity", "HasOpportunityLineItem"):
        raise Unavailable("Opportunity products aren’t available in this org.")


# ---------------------------------------------------------------- area 15: products and price books

def opps_without_products(ctx: Ctx) -> None:
    _need_products(ctx)
    total = ctx.count("Opportunity", OPEN_OPPS, recent=False)
    bare = ctx.count("Opportunity", OPEN_OPPS, "HasOpportunityLineItem = false", recent=False)
    share = pct(bare, total)
    score = rate_score(share / 100, 0.7)
    ctx.totals["Opportunity"] = total
    ctx.metric("Opportunities without products", share, "%", "lower-better", score)
    value = ctx.amount("Opportunity", OPEN_OPPS, "HasOpportunityLineItem = false")
    ctx.finding(
        name="Open deals with no products",
        obj="Opportunity", records=("Opportunity", OPEN_OPPS, "HasOpportunityLineItem = false"), recent=False,
        score=score, affected=bare, value=value,
        description=f"{bare} of {total} open deals ({share:.0f}%) have no products" + (f", worth {_money(value)} in total" if value else "") + ".",
        why="Without products you can’t forecast by product line, see what’s being sold, or quote consistently.",
        impact="No product-level pipeline or revenue reporting, and amounts typed in by hand that can’t be checked.",
        action="Add products when a deal reaches the proposal stage (a validation rule on stage can enforce it), and let the amount come from the products.",
    )


def product_config(ctx: Ctx) -> None:
    if not ctx.has_object("Product2"):
        raise Unavailable("Products aren’t available in this org.")
    active = ctx.count("Product2", "IsActive = true", recent=False)
    ctx.totals["Product2"] = active
    if not active:
        ctx.metric("Product configuration concerns", 1, "count", "lower-better", 50)
        _setting(ctx, "No products set up", "There are no active products.",
                 "Products are how you track what you sell and quote consistently.",
                 "Create your product catalogue (with product codes and families) and a standard price for each product.",
                 severity="medium", obj="Product2")
        return
    concerns = 0
    no_price = None
    std = ctx.rows("SELECT Id, IsActive FROM Pricebook2 WHERE IsStandard = true", limit=1) if ctx.has_object("Pricebook2") else []
    if std and ctx.has_object("PricebookEntry"):
        no_price = _safe_count(ctx, "Product2", "IsActive = true",
                               f"Id NOT IN (SELECT Product2Id FROM PricebookEntry WHERE Pricebook2Id = '{std[0]['Id']}' AND IsActive = true)")
    no_code = ctx.count("Product2", "IsActive = true", "ProductCode = null", recent=False) if ctx.has_field("Product2", "ProductCode") else 0
    concerns += (no_price or 0) + no_code
    score = rate_score(concerns / active, 0.5)
    ctx.metric("Product configuration concerns", concerns, "count", "lower-better", score)
    if no_price:
        ctx.finding(
            name="Active products missing a price",
            obj="Product2", records=("Product2", "IsActive = true", f"Id NOT IN (SELECT Product2Id FROM PricebookEntry WHERE Pricebook2Id = '{std[0]['Id']}' AND IsActive = true)"),
            recent=False, score=rate_score(no_price / active, 0.3), affected=no_price,
            description=f"{no_price} of {active} active products have no active standard price, so they can’t be added to deals or quotes.",
            why="Reps either can’t sell these products or work around it with a ‘misc’ product and a typed-in price.",
            impact="Slower quotes and pricing that doesn’t match the catalogue.",
            action="Add a standard price for each active product, or deactivate products you no longer sell.",
            fix=SETTING_FIX["No products set up"],
        )
    retired = _safe_count(ctx, "Opportunity", OPEN_OPPS, "Id IN (SELECT OpportunityId FROM OpportunityLineItem WHERE Product2.IsActive = false)")
    if retired:
        value = ctx.amount("Opportunity", OPEN_OPPS, "Id IN (SELECT OpportunityId FROM OpportunityLineItem WHERE Product2.IsActive = false)")
        ctx.finding(
            name="Open deals with retired products",
            obj="Opportunity", records=("Opportunity", OPEN_OPPS, "Id IN (SELECT OpportunityId FROM OpportunityLineItem WHERE Product2.IsActive = false)"),
            recent=False, score=60, affected=retired, value=value,
            description=f"{retired} open deals include products that have been deactivated" + (f", worth {_money(value)}" if value else "") + ".",
            why="Deals with retired products may be priced on old terms or promise things you no longer sell.",
            impact="Pricing disputes and rework when the deal is closed or invoiced.",
            action="Review these deals and swap retired products for current ones before quoting.",
        )


def pricebook_config(ctx: Ctx) -> None:
    if not ctx.has_object("Pricebook2"):
        raise Unavailable("Price books aren’t available in this org.")
    books = ctx.rows("SELECT Id, Name, IsActive, IsStandard FROM Pricebook2", limit=500)
    entries = {}
    if ctx.has_object("PricebookEntry"):
        entries = {str(r.get("p")): int(r.get("c") or 0) for r in ctx.sf.query(
            "SELECT Pricebook2Id p, COUNT(Id) c FROM PricebookEntry WHERE IsActive = true GROUP BY Pricebook2Id LIMIT 500").get("records", [])}
    concerns = 0
    std = next((b for b in books if b.get("IsStandard")), None)
    if std and not std.get("IsActive"):
        concerns += 1
        _setting(ctx, "The standard price book is turned off", "The Standard Price Book is inactive.",
                 "Every product needs a standard price before it can go into other price books or onto deals.",
                 "Activate the Standard Price Book (it can stay hidden from reps if you sell from custom price books).", severity="medium", obj="Pricebook2")
    empty = [b.get("Name") or b["Id"] for b in books if b.get("IsActive") and not b.get("IsStandard") and not entries.get(b["Id"])]
    if empty:
        concerns += 1
        _setting(ctx, "Price books with no products", f"{len(empty)} active price books have no active prices: {', '.join(empty[:6])}.",
                 "Reps who pick an empty price book can’t add products, so they create deals without them.",
                 "Fill these price books or deactivate them.", severity="low", affected=len(empty), obj="Pricebook2")
    zero = _safe_count(ctx, "PricebookEntry", "IsActive = true", "UnitPrice = 0", "Product2.IsActive = true") if ctx.has_object("PricebookEntry") else None
    if zero:
        concerns += 1
        _setting(ctx, "Products priced at zero", f"{zero} active price book entries have a price of 0.",
                 "Zero prices let products go onto deals for free unless someone notices.",
                 "Set real prices, or mark free items clearly (e.g. a ‘Free of charge’ product family).", severity="low", affected=zero, obj="PricebookEntry")
    ctx.metric("Pricebook configuration", concerns, "count", "lower-better", 100 - 25 * min(concerns, 4))


def product_reporting(ctx: Ctx) -> None:
    _need_products(ctx)
    won = ctx.count("Opportunity", "IsWon = true", "CloseDate = LAST_N_DAYS:365", recent=False)
    bare = ctx.count("Opportunity", "IsWon = true", "CloseDate = LAST_N_DAYS:365", "HasOpportunityLineItem = false", recent=False)
    share = pct(bare, won)
    score = rate_score(share / 100, 0.7)
    ctx.metric("Product reporting gaps", share, "%", "lower-better", score)
    value = ctx.amount("Opportunity", "IsWon = true", "CloseDate = LAST_N_DAYS:365", "HasOpportunityLineItem = false")
    no_family = ""
    if ctx.has_object("Product2") and ctx.has_field("Product2", "Family"):
        nf = ctx.count("Product2", "IsActive = true", "Family = null", recent=False)
        if nf:
            no_family = f" Also, {nf} active products have no product family, so revenue can’t be grouped by product line."
    ctx.finding(
        name="Won deals with no products recorded",
        obj="Opportunity", records=("Opportunity", "IsWon = true", "CloseDate = LAST_N_DAYS:365", "HasOpportunityLineItem = false"), recent=False,
        score=score, affected=bare, value=value,
        description=f"{bare} of {won} deals won in the last 12 months ({share:.0f}%) have no products" + (f" — {_money(value)} of revenue you can’t break down by product." if value else ".") + no_family,
        why="Leaders can’t see which products drive revenue, attach rates, or upsell potential.",
        impact="Product strategy, commissions and upsell campaigns built on guesswork.",
        action="Require products before a deal can be Closed Won, and backfill products on the largest won deals.",
    )


# ---------------------------------------------------------------- area 16: quotes and CPQ

CPQ_PARTS = [
    ("SBQQ__PriceRule__c", "price rule", 3),
    ("SBQQ__ProductRule__c", "product rule", 3),
    ("SBQQ__CustomScript__c", "custom script (QCP)", 10),
    ("SBQQ__DiscountSchedule__c", "discount schedule", 2),
    ("sbaa__ApprovalRule__c", "advanced approval rule", 2),
    ("SBQQ__Quote__c", "quote", 0),
    ("SBQQ__QuoteLine__c", "quote line", 0),
]


def _plural(n: int, word: str) -> str:
    if n == 1:
        return f"1 {word}"
    head, _, tail = word.partition(" (")
    return f"{n:,} {head}s" + (f" ({tail}" if tail else "")


def _quotes(ctx: Ctx) -> tuple[str, str] | None:
    """(quote object, field linking it to the Opportunity) — CPQ quotes when CPQ is in use, else standard Quotes."""
    if ctx.has_object("SBQQ__Quote__c") and ctx.has_field("SBQQ__Quote__c", "SBQQ__Opportunity2__c"):
        cpq = _safe_count(ctx, "SBQQ__Quote__c") or 0
        std = _safe_count(ctx, "Quote") if ctx.has_object("Quote") else 0
        if cpq and cpq >= (std or 0):
            return "SBQQ__Quote__c", "SBQQ__Opportunity2__c"
    if ctx.has_object("Quote"):
        return "Quote", "OpportunityId"
    return None


def quote_config(ctx: Ctx) -> None:
    concerns = 0
    if ctx.has_object("SBQQ__Quote__c"):
        counts = {label: (_safe_count(ctx, obj) or 0, weight) for obj, label, weight in CPQ_PARTS if ctx.has_object(obj)}
        points = sum(min(n, 30) * w for n, w in counts.values())
        tier = "High" if points >= 80 else "Medium" if points >= 25 else "Low"
        concerns += 1
        inventory = ", ".join(_plural(n, label) for label, (n, _) in counts.items() if n)
        _setting(
            ctx, "Salesforce CPQ is no longer sold — plan the move to Revenue Cloud",
            f"This org runs Salesforce CPQ, which Salesforce stopped selling to new customers in 2025 in favour of Revenue Cloud. "
            f"Migration complexity: {tier}. What would have to move: {inventory or 'very little'}.",
            "CPQ will get fewer improvements over time, and moving to Revenue Cloud is a re-implementation, not an upgrade — it needs planning and budget.",
            "Inventory the CPQ rules and scripts you still use, retire the unused ones now, and build a migration plan and budget before your next renewal.",
            severity={"High": "high", "Medium": "medium", "Low": "low"}[tier],
            affected=sum(n for n, _ in counts.values()),
        )
    elif not ctx.has_object("Quote"):
        concerns += 1
        _setting(ctx, "Quotes aren’t turned on",
                 "Salesforce Quotes are switched off, so quotes are built outside Salesforce (documents or spreadsheets).",
                 "Quotes made outside Salesforce can’t be tracked, synced to the deal, or approved, and pricing drifts.",
                 "Turn on Quotes, add a quote template with your branding, and create quotes from the Opportunity.", severity="medium")
    ctx.metric("Quote configuration", concerns, "count", "lower-better", 100 - 30 * min(concerns, 3))


def quote_sync(ctx: Ctx) -> None:
    src = _quotes(ctx)
    if not src:
        raise Unavailable("Quotes aren’t turned on in this org.")
    obj, link = src
    if obj == "Quote":
        if not ctx.has_field("Opportunity", "SyncedQuoteId"):
            raise Unavailable("Quote syncing isn’t available.")
        cond = ("SyncedQuoteId = null", "Id IN (SELECT OpportunityId FROM Quote)")
        what = "have quotes but none is synced, so the deal’s products and amount don’t match what the customer was sent"
    else:
        if not ctx.has_field("Opportunity", "SBQQ__PrimaryQuote__c"):
            raise Unavailable("CPQ primary quotes aren’t available.")
        cond = ("SBQQ__PrimaryQuote__c = null", f"Id IN (SELECT {link} FROM {obj})")
        what = "have CPQ quotes but no primary quote, so the deal’s products and amount don’t come from the quote"
    bad = _safe_count(ctx, "Opportunity", OPEN_OPPS, *cond) or 0
    with_quotes = _safe_count(ctx, "Opportunity", OPEN_OPPS, f"Id IN (SELECT {link} FROM {obj})") or 0
    score = rate_score(bad / with_quotes, 0.5) if with_quotes else 100
    ctx.metric("Quote synchronization concerns", bad, "count", "lower-better", score)
    value = ctx.amount("Opportunity", OPEN_OPPS, *cond)
    ctx.finding(
        name="Deals out of sync with their quotes",
        obj="Opportunity", records=("Opportunity", OPEN_OPPS, *cond), recent=False,
        score=score, affected=bad, value=value,
        description=f"{bad} of {with_quotes} open deals with quotes {what}.",
        why="The forecast uses the deal amount; if it doesn’t match the quote, the forecast is wrong.",
        impact="Forecast errors and invoices that don’t match what was agreed.",
        action="Start sync (or mark a primary quote) on the quote you sent, and make syncing part of ‘send quote’.",
    )


def quote_visibility(ctx: Ctx) -> None:
    src = _quotes(ctx)
    if not src or not ctx.has_field("Opportunity", "Probability"):
        raise Unavailable("Quotes aren’t turned on in this org.")
    obj, link = src
    late = ctx.count("Opportunity", OPEN_OPPS, "Probability >= 50", recent=False)
    bare = _safe_count(ctx, "Opportunity", OPEN_OPPS, "Probability >= 50", f"Id NOT IN (SELECT {link} FROM {obj})") or 0
    share = pct(bare, late)
    score = rate_score(share / 100, 0.8)
    ctx.metric("Missing Quote visibility", share, "%", "lower-better", score)
    value = ctx.amount("Opportunity", OPEN_OPPS, "Probability >= 50", f"Id NOT IN (SELECT {link} FROM {obj})")
    ctx.finding(
        name="Late-stage deals with no quote",
        obj="Opportunity", records=("Opportunity", OPEN_OPPS, "Probability >= 50", f"Id NOT IN (SELECT {link} FROM {obj})"), recent=False,
        score=score, affected=bare, value=value,
        description=f"{bare} of {late} open deals at 50%+ probability ({share:.0f}%) have no quote in Salesforce"
        + (f", worth {_money(value)}" if value else "") + ".",
        why="If quotes are sent from outside Salesforce, nobody can see what was offered, at what price, or when it expires.",
        impact="Pricing inconsistencies, unapproved discounts and no record of what the customer agreed to.",
        action="Create quotes from the Opportunity in Salesforce, and require one before moving past the proposal stage.",
    )


def quote_process(ctx: Ctx) -> None:
    src = _quotes(ctx)
    if not src:
        raise Unavailable("Quotes aren’t turned on in this org.")
    obj, link = src
    gaps = 0
    parts = []
    if obj == "Quote" and ctx.has_field("Opportunity", "SyncedQuoteId"):
        expired = _safe_count(ctx, "Opportunity", OPEN_OPPS, "SyncedQuote.ExpirationDate < TODAY") or 0
        if expired:
            gaps += expired
            parts.append(f"{expired} open deals are synced to a quote that has expired")
    if obj == "Quote" and ctx.has_field("Quote", "Status"):
        drafts = _safe_count(ctx, "Quote", "Status = 'Draft'", "CreatedDate < LAST_N_DAYS:30", "Opportunity.IsClosed = false") or 0
        if drafts:
            gaps += drafts
            parts.append(f"{drafts} quotes on open deals have sat in Draft for over 30 days")
    elif obj == "SBQQ__Quote__c" and ctx.has_field(obj, "SBQQ__ExpirationDate__c"):
        expired = _safe_count(ctx, obj, "SBQQ__Primary__c = true", "SBQQ__ExpirationDate__c < TODAY", "SBQQ__Opportunity2__r.IsClosed = false") or 0
        if expired:
            gaps += expired
            parts.append(f"{expired} primary CPQ quotes on open deals have expired")
    ctx.metric("Quote process gaps", gaps, "count", "lower-better", rate_score(min(gaps, 50) / 50, 1.0))
    if parts:
        _setting(ctx, "Expired or forgotten quotes", "; ".join(parts) + ".",
                 "Customers holding an expired quote may buy at old prices — or stall because nobody followed up.",
                 "Re-issue expired quotes, follow up on old drafts, and add a reminder task a few days before a quote expires.",
                 severity="medium" if gaps >= 10 else "low", affected=gaps, obj=obj)


# ---------------------------------------------------------------- area 17: approvals and discounts

def _approved_targets(ctx: Ctx, ids: list[str]) -> set[str]:
    out: set[str] = set()
    for i in range(0, len(ids), 200):
        chunk = ", ".join(f"'{x}'" for x in ids[i:i + 200])
        for r in ctx.rows(f"SELECT TargetObjectId FROM ProcessInstance WHERE Status = 'Approved' AND TargetObjectId IN ({chunk})", limit=2000):
            out.add(r.get("TargetObjectId"))
    return out


def _approved_by_quote(ctx: Ctx, opp_ids: list[str]) -> set[str]:
    """Deals with an approved quote: an approved approval request on a quote, or a quote whose status says Approved
    (standard Quotes, CPQ quotes and CPQ Advanced Approvals all record approval on the quote)."""
    out: set[str] = set()
    sources = [("Quote", "OpportunityId", "Status")]
    if ctx.has_object("SBQQ__Quote__c"):
        status = next((f for f in ("ApprovalStatus__c", "SBQQ__Status__c") if ctx.has_field("SBQQ__Quote__c", f)), None)
        sources.append(("SBQQ__Quote__c", "SBQQ__Opportunity2__c", status))
    for obj, link, status in sources:
        if not ctx.has_object(obj) or not ctx.has_field(obj, link):
            continue
        cols = f"Id, {link}" + (f", {status}" if status and ctx.has_field(obj, status, None) else "")
        quotes: dict[str, str] = {}
        for i in range(0, len(opp_ids), 200):
            chunk = ", ".join(f"'{x}'" for x in opp_ids[i:i + 200])
            for q in ctx.rows(f"SELECT {cols} FROM {obj} WHERE {link} IN ({chunk})", limit=5000):
                quotes[q["Id"]] = q.get(link)
                if status and str(q.get(status) or "").lower() == "approved":
                    out.add(q.get(link))
        if quotes and ctx.has_object("ProcessInstance"):
            out |= {quotes[q] for q in _approved_targets(ctx, list(quotes)) if q in quotes}
    return out


def _won_lines(ctx: Ctx) -> list[dict]:
    """Product lines on deals won in the last 12 months (shared by the discount checks)."""
    if "won_lines" not in ctx.memo:
        if not ctx.has_object("OpportunityLineItem"):
            raise Unavailable("Opportunity products aren’t available in this org.")
        ctx.memo["won_lines"] = ctx.rows(
            "SELECT OpportunityId, Quantity, ListPrice, UnitPrice, TotalPrice, Opportunity.Name, Opportunity.Owner.Name, Product2.Name "
            "FROM OpportunityLineItem WHERE Opportunity.IsWon = true AND Opportunity.CloseDate = LAST_N_DAYS:365", limit=10000)
    return ctx.memo["won_lines"]


def _given_away(line: dict) -> tuple[float, float]:
    """(list value, amount below list) for one product line."""
    qty = float(line.get("Quantity") or 0)
    list_value = float(line.get("ListPrice") or 0) * qty
    sold = line.get("TotalPrice")
    sold = float(sold) if sold is not None else float(line.get("UnitPrice") or 0) * qty
    return list_value, max(0.0, list_value - sold)


def pending_approvals(ctx: Ctx) -> None:
    if not ctx.has_object("ProcessInstance"):
        raise Unavailable("Approvals can’t be read in this org.")
    rows = ctx.rows("SELECT Id, TargetObject.Name, TargetObject.Type, CreatedDate FROM ProcessInstance WHERE Status = 'Pending' ORDER BY CreatedDate", limit=2000)
    late = [(r, d) for r in rows if (d := _days_since(r.get("CreatedDate"))) is not None and d > APPROVAL_LATE_DAYS]
    ctx.metric("Pending approvals", len(rows), "count", "lower-better", None)
    score = rate_score(len(late) / len(rows), 0.6) if rows else 100
    ctx.metric("Delayed approvals", len(late), "count", "lower-better", score)
    oldest = ", ".join(f"{(r.get('TargetObject') or {}).get('Name') or 'record'} ({d} days)" for r, d in late[:5])
    ctx.finding(
        name="Approvals waiting more than 3 days",
        obj=None, records=("ProcessInstance", "Status = 'Pending'", f"CreatedDate < LAST_N_DAYS:{APPROVAL_LATE_DAYS}"), recent=False,
        score=score, affected=len(late),
        description=f"{len(late)} of {len(rows)} pending approvals have waited more than {APPROVAL_LATE_DAYS} days. Oldest: {oldest}.",
        why="Every day a quote or discount waits for approval is a day the customer can cool off or a competitor can step in.",
        impact="Slower deal cycles and deals lost while waiting on internal sign-off.",
        action="Add delegated approvers and email/Slack reminders, approve from mobile, and review whether low-risk discounts need approval at all.",
        fix="/lightning/setup/ApprovalProcesses/home",
    )


def discount_config(ctx: Ctx) -> None:
    lines = _won_lines(ctx)
    discounted = [ln for ln in lines if _given_away(ln)[1] > 0]
    concerns = 0
    active = []
    if ctx.has_object("ProcessDefinition"):
        active = ctx.rows("SELECT Id, Name, TableEnumOrId FROM ProcessDefinition WHERE State = 'Active' AND Type = 'Approval'", limit=500)
    on_deals = [p for p in active if p.get("TableEnumOrId") in ("Opportunity", "Quote", "SBQQ__Quote__c")]
    if discounted and not on_deals and not ctx.has_object("sbaa__ApprovalRule__c"):
        concerns += 1
        _setting(ctx, "No approval process for discounts",
                 f"Discounts were given on {len({ln.get('OpportunityId') for ln in discounted})} won deals in the last year, "
                 "but there’s no active approval process on Opportunities or Quotes.",
                 "Without approvals, any rep can give any discount — margin depends on individual judgement.",
                 "Add an approval process for discounts above a threshold (e.g. 15%), with a higher level for bigger discounts.",
                 severity="high")
    list_total = sum(_given_away(ln)[0] for ln in lines)
    given = sum(_given_away(ln)[1] for ln in lines)
    leak = given / list_total if list_total else 0
    score = min(100 - 40 * concerns, rate_score(leak, 0.3))
    ctx.metric("Discount approval configuration", concerns, "count", "lower-better", score)
    if given <= 0:
        return
    by_rep: dict[str, float] = defaultdict(float)
    by_product: dict[str, float] = defaultdict(float)
    for ln in lines:
        _, g = _given_away(ln)
        if g:
            by_rep[((ln.get("Opportunity") or {}).get("Owner") or {}).get("Name") or "Unknown"] += g
            by_product[(ln.get("Product2") or {}).get("Name") or "Unknown"] += g
    top = lambda d: ", ".join(f"{k} ({_money(v)})" for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:3])  # noqa: E731
    deals = sorted({ln.get("OpportunityId") for ln in lines if _given_away(ln)[1] > 0})
    ctx.finding(
        name="Revenue given away in discounts",
        obj="Opportunity", records=("Opportunity", ctx.ids_in(deals)), recent=False,
        score=rate_score(leak, 0.3), affected=len(deals), value=given,
        description=f"Deals won in the last 12 months were sold {leak:.0%} below list price — {_money(given)} given away across {len(deals)} deals. "
        f"Most by rep: {top(by_rep)}. Most by product: {top(by_product)}.",
        why="Small discounts add up; without seeing them by rep and product, nobody can tell which ones bought the deal and which were just habit.",
        impact=f"{_money(given)} of revenue a year, and price expectations that carry into renewals.",
        action="Set discount guidelines by product and deal size, require approval above them, and review discounting by rep monthly.",
    )


def approval_gaps(ctx: Ctx) -> None:
    lines = _won_lines(ctx)
    per_deal: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    names: dict[str, str] = {}
    for ln in lines:
        lv, g = _given_away(ln)
        d = per_deal[ln.get("OpportunityId")]
        d[0] += lv
        d[1] += g
        names[ln.get("OpportunityId")] = (ln.get("Opportunity") or {}).get("Name") or ln.get("OpportunityId")
    big = [oid for oid, (lv, g) in per_deal.items() if lv and g / lv >= BIG_DISCOUNT]
    if not big:
        ctx.metric("Approval workflow gaps", 0, "count", "lower-better", 100)
        return
    approved = _approved_targets(ctx, big) if ctx.has_object("ProcessInstance") else set()
    approved |= _approved_by_quote(ctx, big)
    skipped = [oid for oid in big if oid not in approved]
    given = sum(per_deal[o][1] for o in skipped)
    score = rate_score(len(skipped) / len(big), 0.5)
    ctx.metric("Approval workflow gaps", len(skipped), "count", "lower-better", score)
    ctx.finding(
        name="Big discounts that skipped approval",
        obj="Opportunity", records=("Opportunity", ctx.ids_in(skipped)), recent=False,
        score=score, affected=len(skipped), value=given,
        description=f"{len(skipped)} of {len(big)} deals won with {BIG_DISCOUNT:.0%}+ off list price had no approval on record "
        "(no approved approval request on the deal or its quotes, and no quote marked Approved), "
        f"giving away {_money(given)}: " + ", ".join(names[o] for o in skipped[:5]) + (" …" if len(skipped) > 5 else "") + ".",
        why="If big discounts don’t need sign-off, the approval process exists on paper only.",
        impact="Margin decided deal by deal without oversight, and no audit trail for pricing exceptions.",
        action="Add an approval step for discounts at or above 20%, lock the price fields once approved, and report on discounts without approval each month.",
        fix="/lightning/setup/ApprovalProcesses/home",
    )


AREAS = {
    "area-15": [opps_without_products, product_config, pricebook_config, product_reporting],
    "area-16": [quote_config, quote_sync, quote_visibility, quote_process],
    "area-17": [pending_approvals, discount_config, approval_gaps],
}

STEP_LABELS = {
    opps_without_products: "Finding deals without products",
    product_config: "Checking products and prices",
    pricebook_config: "Checking price books",
    product_reporting: "Checking product data on won deals",
    quote_config: "Checking quote setup (and CPQ)",
    quote_sync: "Checking quote sync",
    quote_visibility: "Finding late-stage deals without quotes",
    quote_process: "Finding expired and forgotten quotes",
    pending_approvals: "Checking pending approvals",
    discount_config: "Measuring discount leakage",
    approval_gaps: "Finding discounts that skipped approval",
}
