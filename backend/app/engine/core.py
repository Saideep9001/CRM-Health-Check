"""Building blocks shared by all health checks: safe SOQL helpers, scoring, and findings.

Checks only use fixed SOQL written here. Object and field names come from this code
and are confirmed against the org's describe results before use, so a check simply
skips what an org doesn't have (e.g. no Leads, no Website field).
"""
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from urllib.parse import quote

from ..salesforce import explorer
from ..salesforce.client import SalesforceClient
from ..salesforce.errors import SalesforceAuthExpired, SalesforceError

Unit = Literal["count", "%"]
Direction = Literal["lower-better", "higher-better"]
Severity = Literal["critical", "high", "medium", "low"]

PRIORITY = {"critical": "P1", "high": "P2", "medium": "P3", "low": "P4"}


class Unavailable(Exception):
    """The org doesn't have (or the user can't read) what this check needs."""


class NotSelected(Exception):
    """None of the objects this check covers were chosen for this run."""


# Objects checked when the user doesn't pick any.
DEFAULT_OBJECTS = ("Account", "Contact", "Lead", "Opportunity")


@dataclass
class Metric:
    label: str  # must match an indicator label in src/config/categories.ts
    value: float
    unit: Unit
    direction: Direction
    score: float | None  # 0–100; None = shown but not scored (e.g. a summary)
    # Shown when someone opens the measure: what we count, and how that becomes the score (plain words).
    how: str | None = None
    rule: str | None = None
    # The records behind the number, per object: [{"object": "Contact", "where": "…", "columns": [...], "order": "Name"}].
    records: list[dict] | None = None
    # The exact rules as table rows: [["Compared on", "Account Name and Website"], ["Counted", "…"]].
    criteria: list[list[str]] | None = None


@dataclass
class FindingDraft:
    area_id: str
    name: str
    severity: Severity
    affected_records: int
    description: str
    why_it_matters: str
    business_impact: str
    recommended_action: str
    sample_records_url: str | None = None
    object_name: str | None = None  # None = org-wide (e.g. a setting)
    # The affected records: object + SOQL filter (built by the engine) so they can be listed and exported.
    records_object: str | None = None
    records_where: str | None = None
    value_at_risk: float | None = None
    fix_url: str | None = None


@dataclass
class Scope:
    lookback_days: int | None = None
    stale_lead_days: int = 30
    stuck_opportunity_days: int = 60
    objects: tuple[str, ...] = DEFAULT_OBJECTS


@dataclass
class ObjectStats:
    """Per-object summary shown as "Results by object"."""

    records: int | None = None
    completeness: float | None = None
    duplicates: int | None = None


@dataclass
class Ctx:
    sf: SalesforceClient
    scope: Scope
    area_id: str = ""
    findings: list[FindingDraft] = field(default_factory=list)
    metrics: dict[str, list[Metric]] = field(default_factory=dict)  # by area
    totals: dict[str, int] = field(default_factory=dict)  # records counted per object (for "records assessed")
    stats: dict[str, ObjectStats] = field(default_factory=dict)
    _count_cache: dict[str, int] = field(default_factory=dict)
    _setup_cache: dict[str, list[dict]] = field(default_factory=dict)
    memo: dict[str, Any] = field(default_factory=dict)  # values shared between checks in one run

    # ---------------- objects in scope ----------------

    def wants(self, obj: str) -> bool:
        return obj in self.scope.objects

    def selected(self, *objs: str) -> list[str]:
        """The given objects that were chosen for this run; raises NotSelected if none."""
        out = [o for o in objs if self.wants(o)]
        if not out:
            raise NotSelected()
        return out

    def others(self) -> list[str]:
        """Chosen objects beyond Account/Contact/Lead/Opportunity (checked with generic rules)."""
        return [o for o in self.scope.objects if o not in DEFAULT_OBJECTS]

    def label(self, obj: str, plural: bool = True) -> str:
        g = explorer._global(self.sf).get(obj, {})
        return (g.get("labelPlural") if plural else g.get("label")) or obj

    def stat(self, obj: str) -> ObjectStats:
        return self.stats.setdefault(obj, ObjectStats())

    # ---------------- describe ----------------

    def fields(self, obj: str) -> dict[str, dict]:
        try:
            desc = explorer._describe(self.sf, obj)
        except explorer.NotFound:
            raise Unavailable(f"{obj} isn’t available in this org.")
        return {f["name"]: f for f in desc.get("fields", [])}

    def has_object(self, obj: str) -> bool:
        try:
            self.fields(obj)
            return True
        except Unavailable:
            return False

    def has_field(self, obj: str, name: str, need: str | None = "filterable") -> bool:
        try:
            f = self.fields(obj).get(name)
        except Unavailable:
            return False
        return bool(f) and (need is None or bool(f.get(need)))

    # ---------------- SOQL ----------------

    def _where(self, obj: str, conds: tuple[str, ...], recent: bool) -> str:
        parts = list(conds)
        if recent and self.scope.lookback_days and self.has_field(obj, "LastModifiedDate"):
            parts.append(f"LastModifiedDate = LAST_N_DAYS:{int(self.scope.lookback_days)}")
        return f" WHERE {' AND '.join(parts)}" if parts else ""

    def count(self, obj: str, *conds: str, recent: bool = True) -> int:
        self.fields(obj)  # raises Unavailable for unknown objects
        soql = f"SELECT COUNT() FROM {obj}{self._where(obj, conds, recent)}"
        if soql not in self._count_cache:
            self._count_cache[soql] = int(self.sf.query(soql).get("totalSize") or 0)
        return self._count_cache[soql]

    def total(self, obj: str, *conds: str, recent: bool = True) -> int:
        """Record count used as the denominator for rates; also feeds "records assessed"."""
        n = self.count(obj, *conds, recent=recent)
        if not conds and recent:
            self.totals[obj] = n
            self.stat(obj).records = n
        return n

    def filled_counts(self, obj: str, fields: list[str], *conds: str, recent: bool = True) -> dict[str, int]:
        """How many records have each field filled in — many fields in one query (COUNT(field) skips nulls)."""
        out: dict[str, int] = {}
        where = self._where(obj, conds, recent)
        for i in range(0, len(fields), 50):
            chunk = fields[i:i + 50]
            soql = f"SELECT {', '.join(f'COUNT({f}) f{n}' for n, f in enumerate(chunk))} FROM {obj}{where}"
            try:
                rec = (self.sf.query(soql).get("records") or [{}])[0]
                out.update({f: int(rec.get(f"f{n}") or 0) for n, f in enumerate(chunk)})
            except SalesforceAuthExpired:
                raise
            except SalesforceError:
                # Some field types can't be counted this way: fall back to one query per field.
                total = self.count(obj, *conds, recent=recent)
                for f in chunk:
                    try:
                        out[f] = total - self.count(obj, *conds, f"{f} = null", recent=recent)
                    except SalesforceError:
                        continue
        return out

    def groups(self, obj: str, fld: str, *conds: str, limit: int = 2000) -> list[tuple[Any, int]]:
        """Values of `fld` and how many records share each, most common first."""
        where = self._where(obj, (f"{fld} != null", *conds), True)
        soql = f"SELECT {fld} v, COUNT(Id) c FROM {obj}{where} GROUP BY {fld} ORDER BY COUNT(Id) DESC LIMIT {limit}"
        return [(r.get("v"), int(r.get("c") or 0)) for r in self.sf.query(soql).get("records", [])]

    def duplicate_groups(self, obj: str, fld: str, *conds: str) -> list[tuple[Any, int]]:
        where = self._where(obj, (f"{fld} != null", *conds), True)
        soql = f"SELECT {fld} v, COUNT(Id) c FROM {obj}{where} GROUP BY {fld} HAVING COUNT(Id) > 1 ORDER BY COUNT(Id) DESC LIMIT 2000"
        return [(r.get("v"), int(r.get("c") or 0)) for r in self.sf.query(soql).get("records", [])]

    def rows(self, soql: str, limit: int = 2000) -> list[dict]:
        """Records for a fixed query, following Salesforce's pages up to `limit` rows."""
        body = self.sf.query(soql)
        out = list(body.get("records", []))
        while not body.get("done", True) and body.get("nextRecordsUrl") and len(out) < limit:
            body = self.sf.get(body["nextRecordsUrl"])
            out += body.get("records", [])
        return out[:limit]

    def by_owner(self, obj: str, *conds: str, amount: bool = False, limit: int = 5) -> list[tuple[str, int, float]]:
        """(owner name, records, total Amount) for the biggest owners; empty if the org can't group this way."""
        where = self._where(obj, conds, True)
        total = ", SUM(Amount) a" if amount and self.has_field(obj, "Amount") else ""
        soql = f"SELECT Owner.Name o, COUNT(Id) c{total} FROM {obj}{where} GROUP BY Owner.Name ORDER BY COUNT(Id) DESC LIMIT {limit}"
        try:
            recs = self.sf.query(soql).get("records", [])
        except SalesforceAuthExpired:
            raise
        except SalesforceError:
            return []
        return [(r.get("o") or "Unknown", int(r.get("c") or 0), float(r.get("a") or 0)) for r in recs]

    def amount(self, obj: str, *conds: str) -> float | None:
        """Total Amount of matching records (Opportunity), or None if there's no Amount field."""
        if not self.has_field(obj, "Amount"):
            return None
        recs = self.sf.query(f"SELECT SUM(Amount) a FROM {obj}{self._where(obj, conds, True)}").get("records", [])
        return float((recs[0] if recs else {}).get("a") or 0)

    def setup(self, soql: str, tooling: bool = True) -> list[dict]:
        """Read setup/config (validation rules, Path, flows…). Needs "View Setup"; otherwise the check is skipped."""
        key = f"{'T' if tooling else 'S'}:{soql}"
        if key not in self._setup_cache:
            path = f"/services/data/{self.sf.settings.sf_api_version}/{'tooling/' if tooling else ''}query?q={quote(soql)}"
            try:
                self._setup_cache[key] = self.sf.get(path).get("records", [])
            except SalesforceAuthExpired:
                raise
            except SalesforceError as exc:
                raise Unavailable(f"Couldn’t read Salesforce setup ({exc}). The connected user may need “View Setup and Configuration”.") from None
        return self._setup_cache[key]

    def list_url(self, obj: str) -> str:
        return f"{self.sf.base}/lightning/o/{obj}/list"

    # ---------------- results ----------------

    def metric(self, label: str, value: float, unit: Unit, direction: Direction, score: float | None, *,
               how: str | None = None, rule: str | None = None,
               records: tuple[str, ...] | list[tuple[str, ...]] | None = None, recent: bool = True,
               criteria: list[tuple[str, str]] | None = None, columns: list[str] | None = None, order: str | None = None) -> Metric:
        """Record a measure.

        `how` = what we count; `rule` = how it's scored; `criteria` = the exact rules as (name, detail) table rows.
        `records` = (object, *conditions), or a list of them, selecting exactly the records counted, so people can open
        and export them; `columns` = fields that show why each record was flagged (shown first, when the object has them);
        `order` = field to sort by (ascending; "-Amount" = descending), e.g. "Name" so duplicates sit next to each other.
        """
        recs = None
        if records:
            recs = [{"object": r[0], "where": self._where(r[0], tuple(r[1:]), recent).removeprefix(" WHERE ") or None,
                     "columns": list(columns or []), "order": order}
                    for r in ([records] if isinstance(records, tuple) else records) if r]
        crit = [[str(k), str(v)] for k, v in (criteria or []) if k and v] or None
        m = Metric(label, round(value, 1), unit, direction, None if score is None else round(score, 1), how, rule, recs or None, crit)
        self.metrics.setdefault(self.area_id, []).append(m)
        return m

    def finding(self, *, name: str, score: float, affected: int, description: str, why: str, impact: str, action: str,
                obj: str | None, url: str | None = None, min_score: float = 95,
                records: tuple[str, ...] | None = None, recent: bool = True, value: float | None = None, fix: str | None = None) -> None:
        """Record a problem when it's big enough to matter (score below `min_score`).

        `records` = (object, *conditions) selecting exactly the affected records, so people can see and export them.
        """
        if affected <= 0 or score >= min_score:
            return
        rec_obj = rec_where = None
        if records:
            rec_obj = records[0]
            rec_where = self._where(rec_obj, tuple(records[1:]), recent).removeprefix(" WHERE ") or None
        self.findings.append(FindingDraft(
            self.area_id, name, severity_for(score), affected, description, why, impact, action, url, obj,
            records_object=rec_obj, records_where=rec_where, value_at_risk=value, fix_url=self.setup_url(fix) if fix else None,
        ))

    def setup_url(self, path: str) -> str:
        """Link into this org's Salesforce (e.g. "/lightning/setup/LeadRules/home")."""
        return f"{self.sf.base}{path}"

    def ids_in(self, ids: list[str], limit: int = 200) -> str:
        """`Id IN (…)` for record ids Salesforce gave us (checked, capped)."""
        safe = [i for i in ids if re.fullmatch(r"[A-Za-z0-9]{15,18}", i or "")][:limit]
        return f"Id IN ({', '.join(repr(i) for i in safe)})" if safe else "Id = null"


def soql_str(value: object) -> str:
    """A text value as a safe SOQL string literal."""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def in_list(field: str, values: list[object], limit: int = 100) -> str:
    """`field IN ('a', 'b', …)` for values Salesforce returned (escaped, capped)."""
    vals = [v for v in values if v is not None][:limit]
    return f"{field} IN ({', '.join(soql_str(v) for v in vals)})" if vals else f"{field} = null"


def clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def rate_score(rate: float, bad: float) -> float:
    """100 when nothing is wrong, falling linearly to 0 when `rate` reaches `bad`."""
    return clamp(100 * (1 - rate / bad)) if bad > 0 else 100.0


def range_score(value: float, worst: float, best: float) -> float:
    """Linear score between a worst value (0) and best value (100)."""
    return clamp(100 * (value - worst) / (best - worst))


def severity_for(score: float) -> Severity:
    if score < 40:
        return "critical"
    if score < 60:
        return "high"
    if score < 80:
        return "medium"
    return "low"


def pct(part: int, whole: int) -> float:
    return 100.0 * part / whole if whole else 0.0


Check = Callable[[Ctx], None]
