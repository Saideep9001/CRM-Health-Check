/**
 * Domain types for the Aquarient CRM Health platform.
 *
 * Everything below `// ---- API contract ----` mirrors the JSON returned by the
 * FastAPI backend (see docs/API_CONTRACT.md). Field names are camelCase on the
 * wire; the backend should serialize with an alias generator.
 */

// ---------------------------------------------------------------------------
// Static product definitions (frontend configuration)
// ---------------------------------------------------------------------------

export type CategoryId =
  | 'data-quality'
  | 'workflows'
  | 'reporting'
  | 'user-adoption'
  | 'quoting'
  | 'integrations';

/** Release stage of a category's diagnostic execution. */
export type ReleaseStage = 'mvp' | 'coming-soon';

export interface DiagnosticArea {
  id: string; // "area-1" … "area-21" — stable key shared with the backend
  number: number;
  categoryId: CategoryId;
  name: string;
  description: string;
  indicators: string[];
}

export interface Category {
  id: CategoryId;
  order: number;
  name: string;
  shortName: string;
  purpose: string;
  release: ReleaseStage;
  areaIds: string[];
}

// ---------------------------------------------------------------------------
// ---- API contract ----
// ---------------------------------------------------------------------------

export type Severity = 'critical' | 'high' | 'medium' | 'low';
export type FindingStatus = 'open' | 'in-review' | 'resolved' | 'accepted-risk';
export type AssessmentStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
export type Priority = 'P1' | 'P2' | 'P3' | 'P4';

export interface ApiHealth {
  status: 'ok' | 'degraded';
  version: string;
  /** Area ids the diagnostic engine can currently execute. */
  executableAreaIds: string[];
}

export type ConnectionStatus = 'disconnected' | 'connected' | 'expired' | 'error';
export type SalesforceEnvironment = 'production' | 'sandbox' | 'custom' | 'upload';

// ---- Uploaded CSV / Excel data (checked like an org) ----

export interface UploadColumn {
  header: string;
  /** The Salesforce field it matches; null = kept as a custom field. */
  field: string | null;
  type: string;
  filled: number;
  sample: string;
}

export interface UploadPreview {
  token: string;
  filename: string;
  object: string;
  rows: number;
  columns: UploadColumn[];
  preview: Record<string, string>[];
  standardFields: { name: string; label: string; type: string }[];
}

export interface UploadedObject {
  name: string;
  label: string;
  plural: string;
  filename: string | null;
  rows: number;
  loadedAt: string | null;
}

export interface UploadResult {
  orgId: string;
  name: string;
  object: string;
  rows: number;
  objects: UploadedObject[];
}

export interface SalesforceConnection {
  id: string | null;
  status: ConnectionStatus;
  environment: SalesforceEnvironment | null;
  organizationName: string | null;
  orgId: string | null;
  instanceUrl: string | null;
  edition: string | null;
  apiVersion: string | null;
  connectedBy: string | null;
  connectedAt: string | null;
  lastCheckedAt: string | null;
  /** Remaining daily API requests, if the backend reports limits. */
  apiRequestsRemaining: number | null;
  apiRequestsMax: number | null;
  errorMessage: string | null;
}

/** Live, read-only facts about the connected org. */
// ---- Duplicate finder ----

export interface DuplicateField {
  name: string;
  label: string;
  kind: string;
  /** How it's compared, in plain words. */
  method: string;
}

export interface DuplicateOptions {
  object: string;
  fields: DuplicateField[];
  standardRule: string | null;
  /** Salesforce's equation: records match when every field in any one group matches. */
  standardGroups: string[][];
}

export interface DuplicateResult {
  object: string;
  standard: boolean;
  ruleName: string | null;
  rules: string[][];
  methods: { field: string; method: string }[];
  columns: { name: string; label: string }[];
  scanned: number;
  truncated: boolean;
  totalGroups: number;
  extraCopies: number;
  /** Records to keep, when groups were merged across fields (linked groups count once); else one per group. */
  kept?: number;
  groups: { size: number; matchedOn: string; records: { id: string | null; values: Record<string, unknown> }[] }[];
  recordUrlPrefix: string;
}

/** One chosen field checked for empty values, duplicates and inconsistent spellings. */
export interface FieldCheckField {
  name: string;
  label: string;
  type: string;
  filled: number;
  empty: number;
  /** Null = not checked for duplicates on its own (picklists, dates, numbers). */
  duplicates: DuplicateResult | null;
  /** Null = not a text field. */
  standardization: {
    oddRecords: number;
    valuesWithVariants: number;
    variants: { usual: string; spellings: { value: string; count: number }[]; oddRecords: number }[];
    /** Why the values are odd (the health check's Data Standardization rules), most common first. */
    reasons?: { reason: string; count: number }[];
    /** What counts as odd for this kind of field. */
    rule?: string;
    columns: { name: string; label: string }[];
    records: { id: string | null; values: Record<string, unknown>; note?: string | null }[];
  } | null;
}

export interface FieldCheckResult {
  object: string;
  scanned: number;
  truncated: boolean;
  /** Records missing at least one chosen field (each counted once). */
  anyEmpty?: number | null;
  /** Records with invalid data in at least one checked field (each counted once). */
  anyOdd?: number | null;
  fields: FieldCheckField[];
  /** Duplicates on all chosen fields together (when more than one was chosen). */
  combined: DuplicateResult | null;
  recordUrlPrefix: string;
  /** Set in the browser: how the fields were combined for this run (AND / Custom = only the rule's duplicates, OR = each field's). */
  matchMode?: 'AND' | 'OR' | 'CUSTOM';
}

/** Records whose chosen fields are empty. */
export interface EmptyResult extends FindingRecordsPage {
  /** All records of the object (first page only). */
  objectTotal: number | null;
  fields: string[];
  fieldLabels: string[];
  match: 'any' | 'all';
}

export interface ConnectionSnapshot {
  asOf: string;
  /** How long one small Salesforce query took, in milliseconds. */
  responseMs: number;
  isSandbox: boolean;
  instanceName: string | null;
  orgCreated: string | null;
  timeZone: string | null;
  locale: string | null;
  activeUsers: number | null;
  limits: { key: string; label: string; unit: string; used: number; max: number }[];
  records: { name: string; label: string; count: number }[];
  totalRecords: number | null;
  objectCount: number | null;
}

/** Salesforce Connected App setup status. The secret is never sent back. */
export interface SalesforceAppConfig {
  configured: boolean;
  /** Where the keys come from: entered on the page, or the server's .env file. */
  source: 'ui' | 'env' | null;
  clientIdPreview: string | null;
  callbackUrl: string;
  updatedAt: string | null;
}

export interface SalesforceAppUpdate {
  clientId: string;
  clientSecret: string;
}

export interface OAuthStartRequest {
  environment: SalesforceEnvironment;
  /** Required when environment === 'custom', e.g. "acme.my.salesforce.com". */
  myDomain?: string;
  redirectUri: string;
}

export interface OAuthStartResponse {
  authorizationUrl: string;
  state: string;
}

export interface OAuthCallbackRequest {
  code: string;
  state: string;
  redirectUri: string;
}

export interface AssessmentScope {
  categoryIds: CategoryId[];
  areaIds: string[];
  /** Only consider records modified within N days; null = all records. */
  lookbackDays: number | null;
  /** Thresholds the engine uses (e.g. stale-lead days). */
  staleLeadDays: number;
  stuckOpportunityDays: number;
  /** Salesforce objects to check (API names). Omitted = Account, Contact, Lead, Opportunity. */
  objects?: string[] | null;
}

export interface Assessment {
  id: string;
  name: string;
  connectionId: string;
  organizationName: string;
  orgId: string;
  status: AssessmentStatus;
  scope: AssessmentScope;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  createdBy: string | null;
  /** 0–100 while running. */
  progress: number | null;
  currentStep: string | null;
  recordsAssessed: number | null;
  findingsCount: number | null;
  overallScore: number | null;
  errorMessage: string | null;
}

export interface CreateAssessmentRequest {
  name: string;
  connectionId: string;
  scope: AssessmentScope;
  notes?: string;
}

/** One field's number for a card: `count` of `of` records are duplicated / empty / odd. */
export interface FieldScore {
  field: string;
  label: string;
  count: number;
  of: number;
  pct: number;
}

/** A field listed under a card about fields (unused, outdated, look-alike…). */
/** A Lead Assignment Rule listed under a card about the rules, with its entries in words. */
export interface RuleListItem {
  name: string;
  active: boolean;
  /** The rule in Salesforce Setup. */
  url: string | null;
  /** Open Leads it would potentially match (inactive rules). */
  matches: number | null;
  entries: { order: number; criteria: string; assignedTo: string; matches: number | null }[];
}

/** A page layout listed under Layout usability concerns. */
export interface LayoutListItem {
  object: string;
  name: string;
  /** Fields placed on the layout. */
  fields: number;
  /** Fields marked Required on the layout. */
  required?: number | null;
  /** Related lists on the layout. */
  relatedLists?: number | null;
  /** Layout usability concerns: why it's hard to use, in words (empty = none). */
  concerns?: string[];
  /** Each profile it's assigned to, with its active users (most first) and the record types it gets this layout for. */
  profileList?: { name: string; users: number; recordTypes: string[] }[] | null;
  /** The record types it's used for (any profile). */
  recordTypes?: string[] | null;
  /** Assigned to a profile with active users; null = the assignments couldn't be read. */
  active: boolean | null;
  /** "Sales User (Partner, Customer)": the profile, and the record types it gets this layout for. */
  profiles: string[] | null;
  /** Active users who get it. */
  users: number | null;
  /** % of the active users in the profiles assigned this object's layouts. */
  usage: number | null;
  url: string | null;
}

/** A rule that stops a save, listed under the validation rules card. */
export interface RuleAuditItem {
  object: string;
  /** Validation Rule, Trigger, Page Layout or System Rule. */
  area: string;
  name: string;
  description: string;
  active: boolean;
  /** The rule's own error message; null = N/A (Salesforce's standard message, or not written in the code). */
  message: string | null;
  /** Why the message is unclear (active rules). */
  issue: string | null;
  /** The message's quality can be judged. */
  assessed: boolean;
  /** The rule in Salesforce Setup. */
  url: string | null;
  /** System rules: the field's label, data type and how it's required. */
  label?: string | null;
  type?: string | null;
  required?: string | null;
  /** Triggers: before insert, after update… */
  events?: string | null;
}

export interface FieldListItem {
  name: string;
  label: string;
  type: string;
  custom: boolean;
  /** Records with it filled in (null: Salesforce can't count this field). */
  filled: number | null;
  of: number | null;
  pct: number | null;
  /** Why it's listed, e.g. "Looks like Phone (Phone)". */
  note: string;
}

export interface IndicatorValue {
  label: string; // matches DiagnosticArea.indicators
  value: number;
  unit: 'count' | '%';
  direction: 'lower-better' | 'higher-better';
  /** 0–100 for this measure; null = shown for information only. */
  score?: number | null;
  /** What we count. */
  how?: string | null;
  /** How the number becomes the score. */
  rule?: string | null;
  /** The exact rules, as [name, detail] rows. */
  criteria?: [string, string][];
  /** Per field: this card's count (duplicated, empty or odd). */
  fieldScores?: FieldScore[] | null;
  /** Cards about fields: the fields themselves. */
  fieldList?: FieldListItem[] | null;
  /** Cards about Lead Assignment Rules: the rules, with their entries and a link to each in Setup. */
  ruleList?: RuleListItem[] | null;
  /** The validation rules card: every rule that stops a save, with its status and error message judged. */
  ruleAudit?: RuleAuditItem[] | null;
  /** Layout usability concerns: every page layout with its fields, profiles and usage. */
  layoutList?: LayoutListItem[] | null;
  /** What the number is out of, when not the object's records (e.g. 225 "custom fields"). */
  outOf?: number | null;
  outOfLabel?: string | null;
  /** The main cause in a few words, e.g. "Least filled: Zip Code (2% filled)". */
  cause?: string | null;
  /** Objects whose records can be listed for this measure. */
  recordObjects?: string[];
}

export interface AreaResult {
  areaId: string;
  score: number | null;
  status: 'assessed' | 'skipped' | 'failed';
  indicators: IndicatorValue[];
  recordsEvaluated: number | null;
  message: string | null;
  /** When this area was last checked. May be earlier than the health check itself, when a later check skipped it. */
  checkedAt?: string | null;
  /** Health check this area's result comes from. */
  sourceAssessmentId?: string | null;
}

export interface CategoryResult {
  categoryId: CategoryId;
  score: number | null;
}

/** Per-object summary of a health check ("Results by object"). */
export interface ObjectResult {
  name: string;
  label: string;
  records: number | null;
  /** % of key fields filled in. */
  completeness: number | null;
  /** Extra records that duplicate another one. */
  duplicates: number | null;
  problems: number;
}

export interface AssessmentResults {
  assessmentId: string;
  overallScore: number | null;
  dataQualityScore: number | null;
  salesProcessScore: number | null;
  recordsAssessed: number;
  categories: CategoryResult[];
  areas: AreaResult[];
  objects?: ObjectResult[];
  /** Problems from the previous check that are gone now. */
  resolved?: ResolvedFinding[];
}

export interface Finding {
  id: string;
  assessmentId: string;
  name: string;
  categoryId: CategoryId;
  areaId: string;
  severity: Severity;
  affectedRecords: number;
  businessImpact: string;
  recommendedAction: string;
  status: FindingStatus;
  description: string;
  whyItMatters: string;
  priority: Priority;
  detectedAt: string;
  /** Optional Salesforce report/list-view URL listing affected records. */
  sampleRecordsUrl: string | null;
  /** Salesforce object the problem is about (null for org-wide settings). */
  objectName?: string | null;
  notes: string | null;
  /** The affected records can be listed and downloaded. */
  recordsAvailable?: boolean;
  /** Money involved, e.g. the total Amount of the deals affected. */
  valueAtRisk?: number | null;
  /** The "What we measure" item that raised this problem. */
  measure?: string | null;
  /** Salesforce page where this can be fixed. */
  fixUrl?: string | null;
  /** Affected records in the previous check (null = new problem). */
  previousAffected?: number | null;
  change?: FindingChange;
}

export type FindingChange = 'new' | 'worse' | 'better' | 'same';

/** A problem from the previous check that's gone now. */
export interface ResolvedFinding {
  name: string;
  areaId: string;
  categoryId: CategoryId;
  objectName: string | null;
  severity: Severity;
  previousAffected: number;
}

/** A group's totals in a records table: how many records, each summed field's total, and per field how many have each value
 *  (e.g. counts.StageName.Proposal = 2). */
export type GroupTotals = { count: number; counts?: Record<string, Record<string, number>> } & Record<string, unknown>;

export interface FindingRecordsPage {
  object: string;
  /** frozen: kept last and in view while the table scrolls sideways. */
  /** hidden: not shown as a column (it's another column's note; still in the CSV). note: a value shown under this one. */
  columns: { name: string; label: string; type: string; frozen?: boolean; pinned?: boolean; hidden?: boolean; note?: string | null }[];
  records: DataRow[];
  totalSize: number | null;
  nextCursor: string | null;
  /** + record id = link to the record in Salesforce. */
  recordUrlPrefix: string;
  /** Field the rows are sorted by (e.g. the one duplicates were matched on). */
  sortedBy?: string | null;
  /** Record id → field → why that value was flagged (e.g. "no country code"). */
  cellNotes?: Record<string, Record<string, string>>;
  /** Per group (e.g. owner id): how many records, and each summed field's total, over every record listed. */
  groupTotals?: Record<string, GroupTotals>;
}

export interface UpdateFindingRequest {
  status?: FindingStatus;
  notes?: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export interface HealthMetric {
  key: string;
  label: string;
  value: number | null;
  unit: 'score' | 'count';
  /** Delta vs the previous completed assessment, if one exists. */
  trend: number | null;
}

export interface UserProfile {
  id: string;
  name: string;
  email: string;
  title: string | null;
  role: string | null;
  /** Signed in with a default/temporary password: must choose their own before anything else. */
  mustChangePassword?: boolean;
  /** The company (workspace) they belong to: they only see its people, orgs and results. */
  companyId?: string | null;
  companyName?: string | null;
  /** Runs the platform: sees every company and can create companies. */
  platformAdmin?: boolean;
}

export interface NotificationPreferences {
  assessmentCompleted: boolean;
  criticalFindings: boolean;
  weeklyDigest: boolean;
  productUpdates: boolean;
}

/** White-label settings for printed and shared reports. */
export interface ReportBranding {
  companyName: string | null;
  /** data:image/...;base64 URL (max ~300 KB). */
  logoDataUrl: string | null;
  accentColor: string | null;
  preparedBy: string | null;
  footerNote: string | null;
  showAquarient: boolean;
}

export interface AppSettings {
  defaultLandingPage: 'dashboard' | 'results' | 'reports';
  dateFormat: 'mdy' | 'dmy' | 'iso';
  notifications: NotificationPreferences;
  branding: ReportBranding;
  /** Default consultant rate for proposals. */
  hourlyRate: number;
  currency: string;
}

export interface AppNotification {
  id: string;
  title: string;
  body: string;
  createdAt: string;
  read: boolean;
  link: string | null;
  kind?: 'alert' | 'info';
}

export interface LoginRequest {
  email: string;
  password: string;
  rememberMe: boolean;
}

export type UserRole = 'admin' | 'consultant' | 'viewer';

/** Whether this server requires sign-in, and whether the first admin still has to be created. */
export interface AuthStatus {
  needsSetup: boolean;
  authRequired: boolean;
}

export interface SetupRequest {
  name: string;
  email: string;
  password: string;
}

/** A person on the team (admin view). */
export interface TeamMember {
  id: string;
  name: string;
  email: string;
  title: string | null;
  role: UserRole;
  allOrgs: boolean;
  orgIds: string[];
  isActive: boolean;
  mustChangePassword?: boolean;
  locked?: boolean;
  createdAt: string | null;
  lastLoginAt: string | null;
  companyId: string;
  companyName: string | null;
  platformAdmin: boolean;
}

/** A company (workspace): its people, orgs and results are only visible inside it. */
export interface Company {
  id: string;
  name: string;
  users: number;
  admins: number;
  orgs: number;
  createdAt: string | null;
}

// ---- Admin Panel ----

export interface AdminOverview {
  users: number;
  admins: number;
  consultants: number;
  viewers: number;
  deactivated: number;
  locked: number;
  neverSignedIn: number;
  mustChangePassword: number;
  pendingRequests: number;
  orgsConnected: number;
  activeSessions: number;
}

export type AccessRequestStatus = 'pending' | 'approved' | 'rejected' | 'cancelled';

export interface AccessRequest {
  id: string;
  userId: string;
  userName: string;
  userEmail: string;
  userRole: string;
  kind: 'org' | 'role';
  requestedRole: UserRole | null;
  orgNote: string | null;
  message: string | null;
  status: AccessRequestStatus;
  decidedBy: string | null;
  decisionNote: string | null;
  createdAt: string | null;
  decidedAt: string | null;
}

export interface AuditEvent {
  id: string;
  at: string | null;
  actor: string;
  action: string;
  target: string | null;
  detail: string | null;
}

export interface TeamMemberCreate {
  name: string;
  email: string;
  role: UserRole;
  allOrgs: boolean;
  orgIds: string[];
  password: string;
  /** Platform admins only: the company they join (others add people to their own company). */
  companyId?: string;
}

export interface SsoStartRequest {
  email: string;
  redirectUri: string;
}

export interface SsoStartResponse {
  authorizationUrl: string;
}

export interface ForgotPasswordRequest {
  email: string;
}

/** One line in a CRM data answer (a record or a group). */
export interface CrmRow {
  label: string;
  detail?: string;
  /** Link to the record in Salesforce, when the row is a single record. */
  url?: string;
}

/** Answer to a fixed CRM data question asked in the help assistant. */
export interface CrmAnswer {
  id: string;
  title: string;
  /** Markdown-lite summary (supports **bold**). */
  summary: string;
  total: number | null;
  rows: CrmRow[];
  /** Link to the matching list in Salesforce. */
  salesforceUrl: string | null;
  /** The same list in Your Data. */
  appUrl?: string | null;
  asOf: string;
}

// ---- Data explorer (read-only view of the connected org) ----

export interface DataObject {
  name: string;
  label: string;
  labelPlural: string;
  custom: boolean;
  /** Everyday sales objects (Account, Contact, Lead…), listed first. */
  common: boolean;
  /** Housekeeping objects (history, sharing, feeds…), hidden by default. */
  system: boolean;
  /** Approximate record count from Salesforce; refreshed by Salesforce periodically. */
  approxCount: number | null;
}

export interface DataField {
  name: string;
  label: string;
  type: string;
  custom: boolean;
  required: boolean;
  sortable: boolean;
  filterable: boolean;
  /** Whether it can be shown as a table column. */
  column: boolean;
  referenceTo: string[];
  helpText: string | null;
  picklistValues: string[];
  /** Its values can be listed (the column's filter drop-down). */
  groupable?: boolean;
}

/** A related list: child records that point at this object (e.g. an Account's Contacts). */
export interface DataChildRelationship {
  /** Salesforce relationship name, e.g. "Contacts". */
  name: string;
  /** Child object, e.g. "Contact". */
  object: string;
  /** Field on the child that points back, e.g. "AccountId". */
  field: string;
  label: string;
  /** The standard link (e.g. Contact.AccountId), rather than an extra lookup field. */
  primary?: boolean;
}

export interface DataRelatedPage {
  relationship: string;
  object: string;
  label: string;
  nameField: string | null;
  columns: { name: string; label: string; type: string }[];
  records: DataRow[];
  totalSize: number | null;
  salesforceUrl: string | null;
}

export interface DataObjectDetail {
  name: string;
  label: string;
  labelPlural: string;
  custom: boolean;
  nameField: string | null;
  searchable: boolean;
  defaultColumns: string[];
  childRelationships?: DataChildRelationship[];
  approxCount: number | null;
  salesforceUrl: string | null;
  fields: DataField[];
}

export interface DataRow {
  id: string | null;
  values: Record<string, unknown>;
  /** Display names for reference fields, e.g. { OwnerId: "Jane Doe" }. */
  refNames: Record<string, string>;
}

export interface DataRecordPage {
  columns: string[];
  records: DataRow[];
  totalSize: number | null;
  nextCursor: string | null;
}

export interface DataRecord extends DataRow {
  salesforceUrl: string;
}

export interface DataRecordQuery {
  fields?: string[];
  q?: string;
  sort?: string;
  dir?: 'asc' | 'desc';
  /** Show only these records (e.g. one opened from a related list). */
  ids?: string[];
  /** Filters from a question (checked again by the server). */
  filters?: DataFilter[];
}

/** The different values of one column, with how many records have each. */
export interface FieldValues {
  field: string;
  values: { value: string | number | boolean; label: string; count: number }[];
  blanks: number;
  truncated: boolean;
}

export interface DataFilter {
  field: string;
  op: string;
  value?: unknown;
  /** Readable text, e.g. "Amount > 50,000". */
  label?: string | null;
}

export interface DataSearchHit {
  id: string;
  name: string;
  detail: string | null;
}

export interface DataSearchGroup {
  object: string;
  label: string;
  labelPlural: string;
  records: DataSearchHit[];
}

/** A plain-English question turned into filters on one object. */
export interface DataAnswer {
  question: string;
  object: string;
  label: string;
  labelPlural: string;
  filters: DataFilter[];
  sort: string | null;
  dir: 'asc' | 'desc' | null;
  countOnly: boolean;
  /** Words that weren't understood (and so weren't applied). */
  ignored: string[];
  total: number | null;
}

export type ReportType = 'executive' | 'category' | 'findings' | 'severity' | 'history' | 'proposal';

// ---------------- Consultant features ----------------

export type ScheduleFrequency = 'daily' | 'weekly' | 'monthly';

export interface ScanSchedule {
  orgId: string;
  organizationName: string | null;
  frequency: ScheduleFrequency;
  enabled: boolean;
  areaIds: string[] | null;
  nextRunAt: string | null;
  lastRunAt: string | null;
  lastAssessmentId: string | null;
  alertEmail: string | null;
  scoreDrop: number;
  alertNewCritical: boolean;
}

export interface ScanScheduleUpdate {
  frequency: ScheduleFrequency;
  enabled: boolean;
  areaIds?: string[] | null;
  alertEmail?: string | null;
  scoreDrop: number;
  alertNewCritical: boolean;
}

/** One client org in the consultant's portfolio. */
export interface PortfolioOrg {
  orgId: string;
  /** Taken off your own list ("Remove from my list"); opening it adds it back. */
  hidden?: boolean;
  organizationName: string;
  edition: string | null;
  environment: string | null;
  connectionStatus: string;
  active: boolean;
  instanceUrl: string | null;
  latestAssessmentId: string | null;
  score: number | null;
  previousScore: number | null;
  lastCheckedAt: string | null;
  trend: number[];
  openProblems: number;
  criticalProblems: number;
  /** Biggest single problem's value at risk (problems can overlap, so not a sum). */
  valueAtRisk: number | null;
  running: boolean;
  schedule: ScanSchedule | null;
  highProblems: number;
  /** Latest score per topic (from the combined view of the latest check). */
  categoryScores: { categoryId: CategoryId; score: number | null }[];
  /** The three most urgent open problems. */
  topProblems: { findingId: string; assessmentId: string; name: string; severity: Severity; affectedRecords: number; valueAtRisk: number | null }[];
}

export interface ProposalLine {
  findingId: string;
  name: string;
  categoryId: CategoryId;
  areaId: string;
  severity: Severity;
  phase: 'P1' | 'P2' | 'P3';
  affectedRecords: number;
  valueAtRisk: number | null;
  hours: number;
  action: string;
}

export interface ProposalPhase {
  id: 'P1' | 'P2' | 'P3';
  name: string;
  description: string;
  hours: number;
  cost: number;
  valueAtRisk: number | null;
  problems: number;
}

/** A statement of work drafted from a health check (meant to be edited). */
export interface Proposal {
  assessmentId: string;
  organizationName: string;
  overallScore: number | null;
  rate: number;
  currency: string;
  hours: number;
  cost: number;
  weeks: number;
  valueAtRisk: number | null;
  summary: string;
  phases: ProposalPhase[];
  lines: ProposalLine[];
}

export interface BenchmarkLine {
  key: string;
  label: string;
  score: number | null;
  peers: number;
  median: number | null;
  /** Share of peer orgs scoring lower (0–100); null until there are enough peers. */
  percentile: number | null;
}

export interface Benchmarks {
  assessmentId: string;
  peers: number;
  minPeers: number;
  ready: boolean;
  lines: BenchmarkLine[];
}

export interface FixPlan {
  summary: string;
  steps: { title: string; detail: string }[];
  risks: string;
  effortHours: number | null;
}

export interface ReportExportRequest {
  type: ReportType;
  format: 'pdf' | 'csv';
  assessmentId: string | null;
  categoryId: CategoryId | null;
  from: string | null;
  to: string | null;
}
