"""API shapes. Field names are camelCase on the wire to match src/types/index.ts."""
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import model_validator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


Environment = Literal["production", "sandbox", "custom", "upload"]
ConnectionStatus = Literal["disconnected", "connected", "expired", "error"]


class ApiHealth(ApiModel):
    status: Literal["ok", "degraded"] = "ok"
    version: str
    executable_area_ids: list[str] = []


class SalesforceConnection(ApiModel):
    id: str | None = None
    status: ConnectionStatus = "disconnected"
    environment: Environment | None = None
    organization_name: str | None = None
    org_id: str | None = None
    instance_url: str | None = None
    edition: str | None = None
    api_version: str | None = None
    connected_by: str | None = None
    connected_at: datetime | None = None
    last_checked_at: datetime | None = None
    api_requests_remaining: int | None = None
    api_requests_max: int | None = None
    error_message: str | None = None


class SalesforceAppConfig(ApiModel):
    """Connected App status for the setup form. Never includes the secret."""

    configured: bool
    source: Literal["ui", "env"] | None = None
    client_id_preview: str | None = None
    callback_url: str
    updated_at: datetime | None = None


# Consumer keys/secrets are letters, digits, and . _ - (no spaces).
_KEY_PATTERN = r"^[A-Za-z0-9._\-]+$"


class SalesforceAppUpdate(ApiModel):
    # Pasted keys often carry stray spaces/newlines at either end; trim before validating.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, str_strip_whitespace=True)

    client_id: str = Field(min_length=20, max_length=256, pattern=_KEY_PATTERN)
    client_secret: str = Field(min_length=8, max_length=256, pattern=_KEY_PATTERN)


class OAuthStartRequest(ApiModel):
    environment: Literal["production", "sandbox", "custom"]  # an upload isn't signed in to
    my_domain: str | None = None
    redirect_uri: str


class OAuthStartResponse(ApiModel):
    authorization_url: str
    state: str


class OAuthCallbackRequest(ApiModel):
    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=128)
    redirect_uri: str


class CrmQueryRequest(ApiModel):
    query_id: str = Field(min_length=1, max_length=64)


class CrmRow(ApiModel):
    label: str
    detail: str | None = None
    url: str | None = None


class CrmAnswer(ApiModel):
    id: str
    title: str
    summary: str
    total: int | None
    rows: list[CrmRow]
    salesforce_url: str | None
    as_of: datetime
    app_url: str | None = None  # where to see the full list inside the platform


class DataObject(ApiModel):
    name: str
    label: str
    label_plural: str
    custom: bool
    common: bool
    system: bool
    approx_count: int | None = None


class DataField(ApiModel):
    name: str
    label: str
    type: str
    custom: bool
    required: bool
    sortable: bool
    filterable: bool
    column: bool
    reference_to: list[str] = []
    help_text: str | None = None
    picklist_values: list[str] = []
    groupable: bool = False  # its values can be listed (column filter)


class FieldValue(ApiModel):
    value: str | float | int | bool
    label: str  # what to show (a name for owner/lookup ids)
    count: int


class FieldValues(ApiModel):
    field: str
    values: list[FieldValue]
    blanks: int  # records with no value
    truncated: bool  # more than 2,000 different values


class DataChildRelationship(ApiModel):
    name: str  # Salesforce relationship name, e.g. "Contacts"
    object: str  # child object, e.g. "Contact"
    field: str  # field on the child that points back, e.g. "AccountId"
    label: str
    primary: bool = False  # the standard link (e.g. Contact.AccountId), not an extra lookup


class DataObjectDetail(ApiModel):
    name: str
    label: str
    label_plural: str
    custom: bool
    name_field: str | None
    searchable: bool
    default_columns: list[str]
    child_relationships: list[DataChildRelationship] = []
    approx_count: int | None = None
    salesforce_url: str | None = None
    fields: list[DataField]


class DataRow(ApiModel):
    id: str | None
    values: dict[str, Any]
    ref_names: dict[str, str] = {}


class DataRecordPage(ApiModel):
    columns: list[str]
    records: list[DataRow]
    total_size: int | None
    next_cursor: str | None


class DataColumn(ApiModel):
    name: str
    label: str
    type: str


class DataRelatedPage(ApiModel):
    relationship: str
    object: str
    label: str
    name_field: str | None
    columns: list[DataColumn]
    records: list[DataRow]
    total_size: int | None
    salesforce_url: str | None


class DataRecord(DataRow):
    salesforce_url: str


class DataSearchHit(ApiModel):
    id: str
    name: str
    detail: str | None = None


class DataSearchGroup(ApiModel):
    object: str
    label: str
    label_plural: str
    records: list[DataSearchHit]


class DataAskRequest(ApiModel):
    question: str = Field(min_length=1, max_length=300)
    objects: list[str] = Field(default_factory=list, max_length=200)
    context: str | None = Field(None, max_length=120)


class DataFilter(ApiModel):
    field: str
    op: str
    value: Any = None
    label: str | None = None


class DataAnswer(ApiModel):
    question: str
    object: str
    label: str
    label_plural: str
    filters: list[DataFilter]
    sort: str | None = None
    dir: Literal["asc", "desc"] | None = None
    count_only: bool = False
    ignored: list[str] = []
    total: int | None = None


class AssistantStatus(ApiModel):
    mode: Literal["ai", "guide"] = "guide"
    model: str | None = None


class UserProfile(ApiModel):
    id: str
    name: str
    email: str
    title: str | None = None
    role: str | None = None
    must_change_password: bool = False
    company_id: str | None = None
    company_name: str | None = None
    platform_admin: bool = False


class UserProfileUpdate(ApiModel):
    name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=254)
    title: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, max_length=120)


class NotificationPreferences(ApiModel):
    assessment_completed: bool = True
    critical_findings: bool = True
    weekly_digest: bool = False
    product_updates: bool = False


class ReportBranding(ApiModel):
    """White-label settings for printed and shared reports."""

    company_name: str | None = Field(None, max_length=120)
    logo_data_url: str | None = Field(None, max_length=400_000, pattern=r"^data:image/(png|jpeg|webp|svg\+xml);base64,[A-Za-z0-9+/=]+$")
    accent_color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    prepared_by: str | None = Field(None, max_length=120)
    footer_note: str | None = Field(None, max_length=300)
    show_aquarient: bool = True


class AppSettings(ApiModel):
    default_landing_page: Literal["dashboard", "results", "reports"] = "dashboard"
    date_format: Literal["mdy", "dmy", "iso"] = "mdy"
    notifications: NotificationPreferences = NotificationPreferences()
    branding: ReportBranding = ReportBranding()
    hourly_rate: float = Field(150, ge=0, le=5000)
    currency: str = Field("USD", min_length=3, max_length=3)


# ---------------- Health checks (assessments) ----------------

AssessmentStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
Severity = Literal["critical", "high", "medium", "low"]
FindingStatus = Literal["open", "in-review", "resolved", "accepted-risk"]


_OBJECT_NAME = r"^[A-Za-z][A-Za-z0-9_]{0,79}$"


class AssessmentScope(ApiModel):
    category_ids: list[str] = Field(default_factory=list, max_length=10)
    area_ids: list[str] = Field(min_length=1, max_length=21)
    # Salesforce objects to check (API names). Empty/None = Account, Contact, Lead, Opportunity.
    objects: list[Annotated[str, Field(pattern=_OBJECT_NAME)]] | None = Field(default=None, max_length=15)
    lookback_days: int | None = Field(default=None, ge=1, le=3650)
    stale_lead_days: int = Field(default=30, ge=1, le=730)
    stuck_opportunity_days: int = Field(default=60, ge=1, le=730)


class CreateAssessmentRequest(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    connection_id: str = Field(min_length=1, max_length=64)
    scope: AssessmentScope
    notes: str | None = Field(default=None, max_length=2000)


class Assessment(ApiModel):
    id: str
    name: str
    connection_id: str
    organization_name: str
    org_id: str
    status: AssessmentStatus
    scope: AssessmentScope
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_by: str | None = None
    progress: int | None = None
    current_step: str | None = None
    records_assessed: int | None = None
    findings_count: int | None = None
    overall_score: int | None = None
    error_message: str | None = None


class FieldScore(ApiModel):
    """One field's number for a card: `count` of `of` records are duplicated / empty / odd."""
    field: str
    label: str
    count: int
    of: int
    pct: float


class FieldListItem(ApiModel):
    """A field listed under a card about fields (unused, outdated, look-alike…)."""
    name: str
    label: str
    type: str = ""
    custom: bool = False
    filled: int | None = None  # records with it filled in (None: Salesforce can't count this field)
    of: int | None = None
    pct: float | None = None
    note: str = ""  # why it's listed, e.g. "Looks like Phone (Phone)"


class IndicatorValue(ApiModel):
    label: str
    value: float
    unit: Literal["count", "%"]
    direction: Literal["lower-better", "higher-better"]
    score: float | None = None
    how: str | None = None  # what we count
    rule: str | None = None  # how it becomes the score
    criteria: list[list[str]] = []  # the exact rules, as [name, detail] rows
    field_scores: list[FieldScore] | None = None  # per field: this card's count (duplicated, empty or odd)
    field_list: list[FieldListItem] | None = None  # cards about fields: the fields themselves
    out_of: int | None = None  # what the number is out of, when not the object's records (e.g. 225 custom fields)
    out_of_label: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_null_criteria(cls, data):
        if not isinstance(data, dict):
            return data
        data = {**data, "criteria": data.get("criteria") or []}
        scores = data.get("fieldScores")
        if scores and not all(isinstance(f, dict) and {"count", "of", "pct"} <= f.keys() for f in scores):
            data["fieldScores"] = None  # saved in an older shape: no chart until the next check, rather than an error
        return data
    # Objects whose records can be listed for this measure (the filters themselves stay on the server).
    record_objects: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _record_objects(cls, data):
        if isinstance(data, dict) and data.get("records") and not data.get("recordObjects"):
            data = {**data, "recordObjects": [r["object"] for r in data["records"] if r.get("object")]}
        return data


class AreaResult(ApiModel):
    area_id: str
    score: int | None
    status: Literal["assessed", "skipped", "failed"]
    indicators: list[IndicatorValue]
    records_evaluated: int | None = None
    message: str | None = None
    # When this area was last checked, and by which health check (it may come from an earlier one).
    checked_at: datetime | None = None
    source_assessment_id: str | None = None


class CategoryResult(ApiModel):
    category_id: str
    score: int | None


class ObjectResult(ApiModel):
    name: str
    label: str
    records: int | None = None
    completeness: float | None = None
    duplicates: int | None = None
    problems: int = 0


class AssessmentResults(ApiModel):
    assessment_id: str
    overall_score: int | None
    data_quality_score: int | None
    sales_process_score: int | None
    records_assessed: int
    categories: list[CategoryResult]
    areas: list[AreaResult]
    objects: list[ObjectResult] = []
    resolved: list["ResolvedFinding"] = []


class Finding(ApiModel):
    id: str
    assessment_id: str
    name: str
    category_id: str
    area_id: str
    severity: Severity
    affected_records: int
    business_impact: str
    recommended_action: str
    status: FindingStatus
    description: str
    why_it_matters: str
    priority: Literal["P1", "P2", "P3", "P4"]
    detected_at: datetime
    sample_records_url: str | None = None
    object_name: str | None = None
    notes: str | None = None
    # Accuracy and follow-up
    records_available: bool = False  # the affected records can be listed / exported
    value_at_risk: float | None = None
    fix_url: str | None = None
    measure: str | None = None  # the "What we measure" item that raised it
    previous_affected: int | None = None  # in the previous check; None = new problem
    change: Literal["new", "worse", "better", "same"] = "new"


class ResolvedFinding(ApiModel):
    """A problem from the previous check that's gone now."""

    name: str
    area_id: str
    category_id: str
    object_name: str | None = None
    severity: Severity
    previous_affected: int


class FindingRecordsPage(ApiModel):
    object: str
    columns: list["DataColumn"]
    records: list["DataRow"]
    total_size: int | None
    next_cursor: str | None
    record_url_prefix: str  # + record id = link to the record in Salesforce
    sorted_by: str | None = None  # field the rows are sorted by (e.g. the field duplicates were matched on)
    cell_notes: dict[str, dict[str, str]] = {}  # record id -> field -> why that value was flagged


class UpdateFindingRequest(ApiModel):
    status: FindingStatus | None = None
    notes: str | None = Field(default=None, max_length=4000)


class Paginated(ApiModel):
    items: list = []
    total: int = 0
    page: int = 1
    page_size: int = 100


# Models above that refer to classes defined later in this file.
AssessmentResults.model_rebuild()
FindingRecordsPage.model_rebuild()


# ---------------- Consultant features (portfolio, schedules, proposals, benchmarks, fix plans)


class AppNotification(ApiModel):
    id: str
    title: str
    body: str
    created_at: datetime | None
    read: bool
    link: str | None = None
    kind: str = "info"


class MarkReadRequest(ApiModel):
    ids: list[str] = []


class ScanSchedule(ApiModel):
    org_id: str
    organization_name: str | None = None
    frequency: Literal["daily", "weekly", "monthly"]
    enabled: bool
    area_ids: list[str] | None = None
    next_run_at: datetime | None
    last_run_at: datetime | None = None
    last_assessment_id: str | None = None
    alert_email: str | None = None
    score_drop: int = 5
    alert_new_critical: bool = True


class ScanScheduleUpdate(ApiModel):
    frequency: str
    enabled: bool = True
    area_ids: list[str] | None = None
    next_run_at: datetime | None = None
    alert_email: str | None = Field(None, max_length=255)
    score_drop: int = Field(5, ge=1, le=100)
    alert_new_critical: bool = True


class PortfolioOrg(ApiModel):
    org_id: str
    organization_name: str
    edition: str | None = None
    environment: str | None = None
    connection_status: str
    active: bool
    instance_url: str | None = None
    latest_assessment_id: str | None = None
    score: int | None = None
    previous_score: int | None = None
    last_checked_at: datetime | None = None
    trend: list[int] = []
    open_problems: int = 0
    critical_problems: int = 0
    value_at_risk: float | None = None
    running: bool = False
    hidden: bool = False  # taken off your own list ("Remove from my list"); open it to add it back
    schedule: ScanSchedule | None = None
    high_problems: int = 0
    category_scores: list["PortfolioCategoryScore"] = []
    top_problems: list["PortfolioProblem"] = []


class PortfolioCategoryScore(ApiModel):
    category_id: str
    score: int | None = None


class PortfolioProblem(ApiModel):
    finding_id: str
    assessment_id: str
    name: str
    severity: str
    affected_records: int
    value_at_risk: float | None = None


class ProposalLine(ApiModel):
    finding_id: str
    name: str
    category_id: str
    area_id: str
    severity: str
    phase: str
    affected_records: int
    value_at_risk: float | None = None
    hours: float
    action: str


class ProposalPhase(ApiModel):
    id: str
    name: str
    description: str
    hours: float
    cost: float
    value_at_risk: float | None = None
    problems: int


class Proposal(ApiModel):
    assessment_id: str
    organization_name: str
    overall_score: int | None = None
    rate: float
    currency: str
    hours: float
    cost: float
    weeks: int
    value_at_risk: float | None = None
    summary: str
    phases: list[ProposalPhase]
    lines: list[ProposalLine]


class BenchmarkLine(ApiModel):
    key: str
    label: str
    score: float | None = None
    peers: int
    median: float | None = None
    percentile: int | None = None


class Benchmarks(ApiModel):
    assessment_id: str
    peers: int
    min_peers: int
    ready: bool
    lines: list[BenchmarkLine]


class FixPlanStep(ApiModel):
    title: str
    detail: str


class FixPlan(ApiModel):
    summary: str
    steps: list[FixPlanStep]
    risks: str
    effort_hours: float | None = None

PortfolioOrg.model_rebuild()


class OrgLimit(ApiModel):
    key: str
    label: str
    unit: str
    used: int
    max: int


class OrgRecordCount(ApiModel):
    name: str
    label: str
    count: int


class ConnectionSnapshot(ApiModel):
    """Live facts about the connected org (read-only)."""
    as_of: datetime
    response_ms: int
    is_sandbox: bool = False
    instance_name: str | None = None
    org_created: str | None = None
    time_zone: str | None = None
    locale: str | None = None
    active_users: int | None = None
    limits: list[OrgLimit] = []
    records: list[OrgRecordCount] = []
    total_records: int | None = None
    object_count: int | None = None


# ---- Duplicate finder ----

class DuplicateField(ApiModel):
    name: str
    label: str
    kind: str  # how it's compared (company, first, last, email, phone, street, zip, city, website, title, exact)
    method: str  # the comparison in plain words


class DuplicateOptions(ApiModel):
    object: str
    fields: list[DuplicateField]
    standard_rule: str | None = None  # name of Salesforce's standard rule for this object, if any
    standard_groups: list[list[str]] = []  # its equation: any group whose fields all match


class DuplicateRequest(ApiModel):
    object: str = Field(max_length=80)
    standard: bool = False
    fields: list[str] = Field(default_factory=list, max_length=6)


class DuplicateRecord(ApiModel):
    id: str | None = None
    values: dict[str, object | None]


class DuplicateGroup(ApiModel):
    size: int
    matched_on: str
    records: list[DuplicateRecord]


class DuplicateColumn(ApiModel):
    name: str
    label: str


class DuplicateMethod(ApiModel):
    field: str
    method: str


class DuplicateResult(ApiModel):
    object: str
    standard: bool
    rule_name: str | None = None
    rules: list[list[str]]
    methods: list[DuplicateMethod]
    columns: list[DuplicateColumn]
    scanned: int
    truncated: bool
    total_groups: int
    extra_copies: int
    groups: list[DuplicateGroup]
    record_url_prefix: str


# ---- Empty fields ----

class EmptyField(ApiModel):
    name: str
    label: str
    type: str


class EmptyRequest(ApiModel):
    object: str = Field(max_length=80)
    fields: list[str] = Field(default_factory=list, max_length=10)
    match: Literal["any", "all"] = "any"
    cursor: str | None = Field(None, max_length=200)


class FieldCheckRequest(ApiModel):
    object: str = Field(max_length=80)
    fields: list[str] = Field(default_factory=list, max_length=10)


class SpellingCount(ApiModel):
    value: str
    count: int


class SpellingVariant(ApiModel):
    usual: str  # the most common spelling
    spellings: list[SpellingCount]
    odd_records: int


class OddReason(ApiModel):
    reason: str  # e.g. "no country code (write it like +1 408 555 0101)"
    count: int


class OddRecord(DuplicateRecord):
    note: str | None = None  # why its value is odd


class FieldStandardization(ApiModel):
    odd_records: int  # records with a value the Data Standardization rules call odd
    values_with_variants: int  # distinct odd values
    variants: list[SpellingVariant]
    reasons: list[OddReason] = []  # why the values are odd, most common first
    rule: str = ""  # what counts as odd for this kind of field
    columns: list[DuplicateColumn]
    records: list[OddRecord]


class FieldCheckField(ApiModel):
    name: str
    label: str
    type: str
    filled: int
    empty: int
    duplicates: DuplicateResult | None = None  # None = not checked for duplicates on its own (picklists, dates, numbers)
    standardization: FieldStandardization | None = None  # None = not a text field


class FieldCheckResult(ApiModel):
    object: str
    scanned: int
    truncated: bool
    any_empty: int | None = None  # records missing at least one chosen field (each counted once)
    any_odd: int | None = None  # records with an odd spelling in at least one checked text field
    any_value: int | None = None  # records with a value in at least one checked text field
    fields: list[FieldCheckField]
    combined: DuplicateResult | None = None  # duplicates on all chosen fields together
    record_url_prefix: str


class EmptyResult(FindingRecordsPage):
    object_total: int | None = None  # all records of the object (first page only)
    fields: list[str] = []
    field_labels: list[str] = []
    match: str = "any"
