import type {
  Company,
  UploadPreview,
  UploadResult,
  UploadedObject,
  DataFilter,
  FieldValues,
  FieldCheckResult,
  AccessRequest,
  EmptyResult,
  DuplicateOptions,
  DuplicateResult,
  ConnectionSnapshot,
  AccessRequestStatus,
  AdminOverview,
  AuditEvent,
  UserRole,
  ApiHealth,
  AppNotification,
  AppSettings,
  ForgotPasswordRequest,
  LoginRequest,
  SsoStartRequest,
  SsoStartResponse,
  Assessment,
  AssessmentResults,
  AssessmentStatus,
  CreateAssessmentRequest,
  DataObject,
  DataObjectDetail,
  DataRecord,
  DataRecordPage,
  DataRecordQuery,
  DataAnswer,
  DataRelatedPage,
  DataSearchGroup,
  Finding,
  FindingRecordsPage,
  OAuthCallbackRequest,
  OAuthStartRequest,
  OAuthStartResponse,
  Paginated,
  ReportExportRequest,
  SalesforceAppConfig,
  SalesforceAppUpdate,
  SalesforceConnection,
  UpdateFindingRequest,
  UserProfile,
  AuthStatus,
  SetupRequest,
  TeamMember,
  TeamMemberCreate,
  PortfolioOrg,
  ScanSchedule,
  ScanScheduleUpdate,
  Proposal,
  Benchmarks,
  FixPlan,
} from '@/types';
import { API_BASE_URL, http } from './client';

/**
 * Backend API integration points. Each function maps 1:1 to an endpoint
 * documented in docs/API_CONTRACT.md.
 */

export const systemApi = {
  health: (signal?: AbortSignal) => http.get<ApiHealth>('/health', undefined, signal),
};

export const authApi = {
  /** Public: is sign-in required, and does the first admin still need creating? */
  status: (signal?: AbortSignal) => http.get<AuthStatus>('/auth/setup-status', undefined, signal),
  /** First run only: create the first admin and sign in. */
  setup: (body: SetupRequest) => http.post<UserProfile>('/auth/setup', body),
  changePassword: (body: { currentPassword: string; newPassword: string }) => http.post<void>('/me/password', body),
  /** Creates a session (HttpOnly cookie) and returns the signed-in user. */
  login: (body: LoginRequest) => http.post<UserProfile>('/auth/login', body),
  logout: () => http.post<void>('/auth/logout'),
  /** Resolves the user's identity provider from their email domain. */
  ssoStart: (body: SsoStartRequest) => http.post<SsoStartResponse>('/auth/sso/start', body),
  /** Always 202 regardless of whether the account exists. */
  forgotPassword: (body: ForgotPasswordRequest) => http.post<void>('/auth/password/forgot', body),
};

export const uploadApi = {
  /** Read a CSV/Excel file: its columns, the field each one matches, a few rows. */
  preview: (file: File, object: string) => http.upload<UploadPreview>('/uploads/preview', file, { filename: file.name, object }),
  /** The same file matched to another object. */
  previewAgain: (token: string, object: string) => http.get<UploadPreview>(`/uploads/preview/${token}`, { object }),
  /** Load it (a new upload, or added to `orgId`); the upload becomes the active org. */
  import: (body: { token: string; object: string; mapping: Record<string, string | null>; orgId?: string | null; name?: string }) =>
    http.post<UploadResult>('/uploads/import', body, 180_000),
  objects: (orgId: string, signal?: AbortSignal) => http.get<UploadedObject[]>(`/uploads/${encodeURIComponent(orgId)}/objects`, undefined, signal),
  removeObject: (orgId: string, name: string) => http.delete<void>(`/uploads/${encodeURIComponent(orgId)}/objects/${encodeURIComponent(name)}`),
};

export const connectionApi = {
  get: (signal?: AbortSignal) => http.get<SalesforceConnection>('/salesforce/connection', undefined, signal),
  startOAuth: (body: OAuthStartRequest) => http.post<OAuthStartResponse>('/salesforce/oauth/start', body),
  completeOAuth: (body: OAuthCallbackRequest) => http.post<SalesforceConnection>('/salesforce/oauth/callback', body),
  check: () => http.post<SalesforceConnection>('/salesforce/connection/check'),
  /** Live limits, users, record counts and response time of the active org. */
  /** `fresh` (the Refresh button) reads straight from Salesforce instead of the server's short-lived read cache. */
  snapshot: (signal?: AbortSignal, fresh = false) =>
    http.get<ConnectionSnapshot>('/salesforce/connection/snapshot', fresh ? { fresh: 'true' } : undefined, signal),
  disconnect: () => http.delete<void>('/salesforce/connection'),
  /** Connected App keys entered on the Connect Salesforce page. */
  getApp: (signal?: AbortSignal) => http.get<SalesforceAppConfig>('/salesforce/app', undefined, signal),
  saveApp: (body: SalesforceAppUpdate) => http.put<SalesforceAppConfig>('/salesforce/app', body),
  clearApp: () => http.delete<SalesforceAppConfig>('/salesforce/app'),
};

export interface AssessmentListParams {
  status?: AssessmentStatus;
  page?: number;
  pageSize?: number;
  sort?: string; // e.g. "-createdAt"
}

export const assessmentApi = {
  list: (params: AssessmentListParams = {}, signal?: AbortSignal) =>
    http.get<Paginated<Assessment>>('/assessments', { page: 1, pageSize: 100, sort: '-createdAt', ...params }, signal),
  get: (id: string, signal?: AbortSignal) => http.get<Assessment>(`/assessments/${encodeURIComponent(id)}`, undefined, signal),
  create: (body: CreateAssessmentRequest) => http.post<Assessment>('/assessments', body),
  cancel: (id: string) => http.post<Assessment>(`/assessments/${encodeURIComponent(id)}/cancel`),
  results: (id: string, signal?: AbortSignal) =>
    http.get<AssessmentResults>(`/assessments/${encodeURIComponent(id)}/results`, undefined, signal),
  findings: (id: string, signal?: AbortSignal) =>
    http.get<Paginated<Finding>>(`/assessments/${encodeURIComponent(id)}/findings`, { page: 1, pageSize: 1000 }, signal),
};

/** Read-only browsing of the connected Salesforce org. */
export const dataApi = {
  /** Each record type's fields (from its page layout), fields on none ("other"), and which fields the field cards count. */
  recordTypes: (object: string, signal?: AbortSignal) =>
    http.get<{ recordTypes: { name: string; id: string; fields: string[] }[]; other: string[]; fillable: string[]; ownCustom: string[]; setupLinks?: Record<string, string> }>(
      `/data/objects/${encodeURIComponent(object)}/record-types`,
      undefined,
      signal,
    ),
  /** Fields that can be checked for being empty. */
  emptyOptions: (object: string, signal?: AbortSignal) => http.get<{ name: string; label: string; type: string }[]>('/data/empty/options', { object }, signal),
  /** Records whose chosen fields are empty (any or all), 200 per page. */
  findEmpty: (body: { object: string; fields: string[]; match: 'any' | 'all'; cursor?: string }) => http.post<EmptyResult>('/data/empty', body, 60_000),
  emptyCsvUrl: (object: string, fields: string[], match: 'any' | 'all') =>
    `${API_BASE_URL}/data/empty.csv?${new URLSearchParams({ object, fields: fields.join(','), match })}`,
  /** Fields that can be compared to find duplicates, and Salesforce's standard rule for the object. */
  duplicateOptions: (object: string, signal?: AbortSignal) => http.get<DuplicateOptions>('/data/duplicates/options', { object }, signal),
  /** Groups of duplicate records (read-only). */
  /** Empty values, duplicates and odd spellings for each chosen field (reads up to 20,000 records). */
  checkFields: (body: { object: string; fields: string[] }) => http.post<FieldCheckResult>('/data/fields/check', body, 180_000),
  findDuplicates: (body: { object: string; standard: boolean; fields: string[] }) => http.post<DuplicateResult>('/data/duplicates', body, 120_000),
  objects: (signal?: AbortSignal) => http.get<DataObject[]>('/data/objects', undefined, signal),
  object: (name: string, signal?: AbortSignal) => http.get<DataObjectDetail>(`/data/objects/${encodeURIComponent(name)}`, undefined, signal),
  records: (name: string, query: DataRecordQuery, cursor: string | null, signal?: AbortSignal) =>
    http.get<DataRecordPage>(
      `/data/objects/${encodeURIComponent(name)}/records`,
      {
        fields: query.fields?.length ? query.fields.join(',') : undefined,
        q: query.q || undefined,
        sort: query.sort,
        dir: query.dir,
        ids: query.ids?.length ? query.ids.join(',') : undefined,
        filters: query.filters?.length ? JSON.stringify(query.filters.map(({ field, op, value }) => ({ field, op, value }))) : undefined,
        cursor: cursor ?? undefined,
      },
      signal,
    ),
  /** The values of one column (for its filter drop-down), following the search box and the other filters. */
  fieldValues: (name: string, field: string, q: string | undefined, filters: DataFilter[], signal?: AbortSignal) =>
    http.get<FieldValues>(
      `/data/objects/${encodeURIComponent(name)}/values`,
      { field, q: q || undefined, filters: filters.length ? JSON.stringify(filters.map(({ field: f, op, value }) => ({ field: f, op, value }))) : undefined },
      signal,
    ),
  /** Records matching some text, across many objects at once. */
  search: (q: string, objects: string[] | undefined, signal?: AbortSignal) =>
    http.get<DataSearchGroup[]>('/data/search', { q, objects: objects?.length ? objects.join(',') : undefined }, signal),
  /** Turn a question into filters on one object. */
  ask: (body: { question: string; objects?: string[]; context?: string }) => http.post<DataAnswer>('/data/ask', body),
  record: (name: string, id: string, signal?: AbortSignal) =>
    http.get<DataRecord>(`/data/objects/${encodeURIComponent(name)}/records/${encodeURIComponent(id)}`, undefined, signal),
  related: (name: string, id: string, relationship: string, signal?: AbortSignal) =>
    http.get<DataRelatedPage>(
      `/data/objects/${encodeURIComponent(name)}/records/${encodeURIComponent(id)}/related/${encodeURIComponent(relationship)}`,
      undefined,
      signal,
    ),
  refresh: () => http.post<void>('/data/refresh'),
};

export const findingApi = {
  get: (id: string, signal?: AbortSignal) => http.get<Finding>(`/findings/${encodeURIComponent(id)}`, undefined, signal),
  update: (id: string, body: UpdateFindingRequest) => http.patch<Finding>(`/findings/${encodeURIComponent(id)}`, body),
  /** The records a problem is about, live from Salesforce (narrowed by column filters). */
  records: (id: string, cursor: string | null, signal?: AbortSignal, filters: DataFilter[] = []) =>
    http.get<FindingRecordsPage>(`/findings/${encodeURIComponent(id)}/records`, { cursor: cursor ?? undefined, filters: filterParam(filters) }, signal),
  /** The values of one column among a problem's records (for its filter drop-down). */
  values: (id: string, field: string, filters: DataFilter[], signal?: AbortSignal) =>
    http.get<FieldValues>(`/findings/${encodeURIComponent(id)}/values`, { field, filters: filterParam(filters) }, signal),
  /** Link that downloads the affected records (only those the column filters keep) as a CSV file. */
  recordsCsvUrl: (id: string, filters: DataFilter[] = []) =>
    `${API_BASE_URL}/findings/${encodeURIComponent(id)}/records.csv${filters.length ? `?${new URLSearchParams({ filters: filterParam(filters)! })}` : ''}`,
};

/** Column filters as the API takes them (labels stay in the browser). */
const filterParam = (filters: DataFilter[]) =>
  filters.length ? JSON.stringify(filters.map(({ field, op, value }) => ({ field, op, value }))) : undefined;

/** One Opportunity Sales Path with every stage of its sales process and that stage's guidance, live from Setup. */
export type SalesPathData = {
  id: string;
  /** the Sales Process's name (or "Master (no record type)") */
  name: string;
  /** it has an active Sales Path */
  active: boolean;
  processActive: boolean;
  /** the Sales Path shown for it (null = none) */
  pathName: string | null;
  pathActive: boolean | null;
  recordType: string | null;
  salesProcess: string | null;
  stages: { stage: string; apiName: string; closed: boolean; available: boolean; details: string[]; keyFields: string[] }[];
  openStages: number;
  guided: number;
};

/** One user assigned EAC: their status, and whether and when they last logged in to Salesforce. */
export type EacUser = {
  id: string;
  name: string;
  profile: string | null;
  status: string;
  tone: 'bad' | 'warn' | 'good';
  lastLogin?: string | null;
  login?: string;
  /** the user's Active flag in Salesforce */
  isActive?: boolean;
  email?: string | null;
  title?: string | null;
  phone?: string | null;
  /** Master status (EAC assigned and an active user), then Email, Calendar and Contact sync (the org's EAC settings); null = not available */
  sync?: { key: string; label: string; on: boolean | null; source: string }[];
};

/** Einstein Activity Capture (EAC) Health, live from Salesforce (only what its APIs expose; null = not available). */
export type EacHealthData = {
  status: 'Healthy' | 'Warning' | 'Not set up';
  settings: { available: boolean; flags: { name: string; label: string; on: boolean }[]; error: string | null };
  tiles: { key: string; label: string; on: boolean | null; setting: string | null }[];
  sources: string[];
  users: { total: number; active: number; attention: number; issues: EacUser[]; all?: EacUser[] };
  pipeline: { key: string; label: string; value: number | null }[];
};

/** One rep and what they logged in the period (Reps with No Activities Logged Recently). */
export type RepActivityRep = {
  id: string;
  name: string;
  profile: string | null;
  email: string | null;
  title: string | null;
  lastLogin: string | null;
  counts: { email: number; event: number; task: number };
  lastActivity: string | null;
};

/** Web-to-Lead: whether website Leads still arrive as usual, and their last 12 weeks and months (live from Salesforce). */
export type WebLeadHistory = {
  verdict: 'Healthy' | 'Slowing' | 'Stopped' | 'No web leads';
  tone: 'good' | 'warn' | 'bad' | 'muted';
  why: string;
  last7: number;
  last14: number;
  expected14: number;
  lastCreated: string | null;
  weeks: { label: string; start: string; end: string; count: number }[];
  months: { label: string; count: number }[];
  /** the chart's calendar year (null = the last 12 months), and the years with website Leads, newest first */
  year: number | null;
  years: number[];
};

/** Email template availability: the templates with type, status, area and usage share (live from Salesforce). */
export type EmailTemplatesData = {
  status: 'all' | 'active' | 'inactive';
  counts: { all: number; active: number; inactive: number };
  templates: {
    id: string;
    name: string;
    type: string;
    active: boolean;
    area: string;
    folder: string | null;
    timesUsed: number | null;
    usagePct: number | null;
    lastUsed: string | null;
  }[];
  areas: { area: string; timesUsed: number; pct: number }[];
  totalUsed: number | null;
  truncated: boolean;
};

/** The records one measure ("What we measure") counted, live from Salesforce. */
export const indicatorApi = {
  /** Email template availability: all, active or inactive templates. */
  emailTemplates: (assessmentId: string, status: string, signal?: AbortSignal) =>
    http.get<EmailTemplatesData>(`/assessments/${encodeURIComponent(assessmentId)}/email-templates`, { status }, signal),
  /** Web-to-Lead issues: the website Lead history and health. */
  webLeadHistory: (assessmentId: string, areaId: string, signal?: AbortSignal, year?: number) =>
    http.get<WebLeadHistory>(
      `/assessments/${encodeURIComponent(assessmentId)}/areas/${encodeURIComponent(areaId)}/web-lead-history`,
      { label: 'Web-to-Lead issues', year },
      signal,
    ),
  /** Reps with No Activities Logged Recently: each rep's Emails, Events and Tasks in the last `days` days. */
  /** `period`: a number of days (7, 14, 30, 90) or custom dates { from, to } (YYYY-MM-DD, both included). */
  repActivity: (assessmentId: string, period: number | { from: string; to: string }, signal?: AbortSignal) =>
    http.get<{ days: number | null; available: { email: boolean; event: boolean; task: boolean }; reps: RepActivityRep[]; quiet: Record<string, number> }>(
      `/assessments/${encodeURIComponent(assessmentId)}/rep-activity`,
      typeof period === 'number' ? { days: period } : { from: period.from, to: period.to },
      signal,
    ),
  /** Einstein Activity Capture (EAC) Health: settings, assigned users and the activity flowing in. */
  eacHealth: (assessmentId: string, signal?: AbortSignal) =>
    http.get<EacHealthData>(`/assessments/${encodeURIComponent(assessmentId)}/eac-health`, {}, signal),
  /** Sales stage guidance gaps: the Opportunity Sales Paths, active first. */
  salesPaths: (assessmentId: string, signal?: AbortSignal) =>
    http.get<SalesPathData[]>(`/assessments/${encodeURIComponent(assessmentId)}/sales-paths`, {}, signal),
  /** `only` = fields: just the records with a problem in one of them (a flagged value, or an empty key field). */
  /** `period` (No Activity only): "90", "180" or "range:YYYY-MM-DD:YYYY-MM-DD" instead of the health check's 6 months. */
  records: (assessmentId: string, areaId: string, label: string, object: string, cursor: string | null, signal?: AbortSignal, filters: DataFilter[] = [], only: string[] = [], period?: string, queue?: string, fields?: string[], days?: number, recordType?: string) =>
    http.get<FindingRecordsPage>(
      `/assessments/${encodeURIComponent(assessmentId)}/areas/${encodeURIComponent(areaId)}/indicator-records`,
      { label, object, cursor: cursor ?? undefined, filters: filterParam(filters), only: only.length ? only.join(',') : undefined, period, queue, fields: fields?.length ? fields.join(',') : undefined, days, record_type: recordType },
      signal,
    ),
  /** Stuck Queue-Owned Leads: every Lead queue, with how many of its Leads sit in each (for the Queue filter). */
  queues: (assessmentId: string, areaId: string, label: string, object: string, signal?: AbortSignal, days?: number, period?: string, recordType?: string) =>
    http.get<{ id: string; name: string; count: number; active?: boolean | null }[]>(
      `/assessments/${encodeURIComponent(assessmentId)}/areas/${encodeURIComponent(areaId)}/indicator-queues`,
      { label, object, days, period, record_type: recordType },
      signal,
    ),
  /** Stale Leads: the Lead record types, with how many stale Leads have each ("none" = no record type). */
  recordTypes: (assessmentId: string, areaId: string, label: string, object: string, signal?: AbortSignal, period?: string) =>
    http.get<{ id: string; name: string; count: number }[]>(
      `/assessments/${encodeURIComponent(assessmentId)}/areas/${encodeURIComponent(areaId)}/indicator-record-types`,
      { label, object, period },
      signal,
    ),
  /** Inactive Lead Assignment Rules: each inactive rule and who it assigns to (queues and users), with live counts. */
  ruleTargets: (assessmentId: string, areaId: string, label: string, object: string, signal?: AbortSignal) =>
    http.get<{
      rules: { name: string; targets: string[]; count: number }[];
      targets: { id: string; name: string; type: string; inactive: boolean; count: number }[];
    }>(
      `/assessments/${encodeURIComponent(assessmentId)}/areas/${encodeURIComponent(areaId)}/indicator-rule-targets`,
      { label, object },
      signal,
    ),
  /** The values of one column among a measure's records (for its filter drop-down). */
  values: (assessmentId: string, areaId: string, label: string, object: string, field: string, filters: DataFilter[], signal?: AbortSignal, only: string[] = [], period?: string, queue?: string, days?: number, recordType?: string) =>
    http.get<FieldValues>(
      `/assessments/${encodeURIComponent(assessmentId)}/areas/${encodeURIComponent(areaId)}/indicator-values`,
      { label, object, field, filters: filterParam(filters), only: only.length ? only.join(',') : undefined, period, queue, days, record_type: recordType },
      signal,
    ),
  csvUrl: (assessmentId: string, areaId: string, label: string, object: string, filters: DataFilter[] = [], only: string[] = [], period?: string, queue?: string, fields?: string[], days?: number, recordType?: string) =>
    `${API_BASE_URL}/assessments/${encodeURIComponent(assessmentId)}/areas/${encodeURIComponent(areaId)}/indicator-records.csv?${new URLSearchParams({ label, object, ...(filters.length ? { filters: filterParam(filters)! } : {}), ...(only.length ? { only: only.join(',') } : {}), ...(period ? { period } : {}), ...(queue ? { queue } : {}), ...(fields?.length ? { fields: fields.join(',') } : {}), ...(days != null ? { days: String(days) } : {}), ...(recordType ? { record_type: recordType } : {}) })}`,
};

/** Team management (admins only). */
export const teamApi = {
  list: (signal?: AbortSignal) => http.get<TeamMember[]>('/users', undefined, signal),
  create: (body: TeamMemberCreate) => http.post<TeamMember>('/users', body),
  update: (id: string, body: Partial<Pick<TeamMember, 'name' | 'role' | 'allOrgs' | 'orgIds' | 'isActive'>>) =>
    http.patch<TeamMember>(`/users/${encodeURIComponent(id)}`, body),
  resetPassword: (id: string, password: string) => http.post<void>(`/users/${encodeURIComponent(id)}/password`, { password }),
  unlock: (id: string) => http.post<void>(`/users/${encodeURIComponent(id)}/unlock`),
  signOut: (id: string) => http.post<void>(`/users/${encodeURIComponent(id)}/sign-out`),
};

/** Admin Panel (admins only). */
export const adminApi = {
  overview: (signal?: AbortSignal) => http.get<AdminOverview>('/admin/overview', undefined, signal),
  requests: (status?: AccessRequestStatus, signal?: AbortSignal) => http.get<AccessRequest[]>('/admin/requests', status ? { status } : undefined, signal),
  approve: (id: string, body: { orgIds?: string[]; allOrgs?: boolean; role?: UserRole; note?: string }) =>
    http.post<AccessRequest>(`/admin/requests/${encodeURIComponent(id)}/approve`, body),
  reject: (id: string, note?: string) => http.post<AccessRequest>(`/admin/requests/${encodeURIComponent(id)}/reject`, { note }),
  activity: (signal?: AbortSignal) => http.get<AuditEvent[]>('/admin/activity', { limit: 200 }, signal),
  /** Platform admins: every company, and creating one with its first admin. */
  companies: (signal?: AbortSignal) => http.get<Company[]>('/admin/companies', undefined, signal),
  createCompany: (body: { name: string; adminName: string; adminEmail: string; adminPassword: string }) => http.post<Company>('/admin/companies', body),
};

/** Asking an admin for more access (anyone signed in). */
export const accessApi = {
  mine: (signal?: AbortSignal) => http.get<AccessRequest[]>('/access-requests/mine', undefined, signal),
  create: (body: { kind: 'org' | 'role'; requestedRole?: UserRole; orgNote?: string; message?: string }) => http.post<AccessRequest>('/access-requests', body),
  cancel: (id: string) => http.delete<void>(`/access-requests/${encodeURIComponent(id)}`),
};

export const consultantApi = {
  portfolio: (signal?: AbortSignal) => http.get<PortfolioOrg[]>('/portfolio', undefined, signal),
  activate: (orgId: string) => http.post<PortfolioOrg | null>(`/salesforce/connections/${encodeURIComponent(orgId)}/activate`),
  /** Remove from my list: only you stop seeing it; everyone else keeps it. */
  hide: (orgId: string) => http.post<void>(`/salesforce/connections/${encodeURIComponent(orgId)}/hide`),
  /** Who a disconnect would affect (admins). */
  people: (orgId: string, signal?: AbortSignal) => http.get<string[]>(`/salesforce/connections/${encodeURIComponent(orgId)}/people`, undefined, signal),
  /** Disconnect an org; `deleteResults` also permanently deletes its saved health checks. */
  removeOrg: (orgId: string, deleteResults = false) =>
    http.delete<void>(`/salesforce/connections/${encodeURIComponent(orgId)}${deleteResults ? '?deleteResults=true' : ''}`),
  saved: (orgId: string, signal?: AbortSignal) => http.get<{ checks: number; problems: number }>(`/salesforce/connections/${encodeURIComponent(orgId)}/saved`, undefined, signal),
  putSchedule: (orgId: string, body: ScanScheduleUpdate) => http.put<ScanSchedule>(`/schedules/${encodeURIComponent(orgId)}`, body),
  deleteSchedule: (orgId: string) => http.delete<void>(`/schedules/${encodeURIComponent(orgId)}`),
  testEmail: (orgId: string) => http.post<void>(`/schedules/${encodeURIComponent(orgId)}/test-email`),
  proposal: (id: string, rate: number, currency: string, signal?: AbortSignal) =>
    http.get<Proposal>(`/assessments/${encodeURIComponent(id)}/proposal`, { rate, currency }, signal),
  benchmarks: (id: string, signal?: AbortSignal) => http.get<Benchmarks>(`/assessments/${encodeURIComponent(id)}/benchmarks`, undefined, signal),
  fixPlan: (findingId: string) => http.post<FixPlan>(`/findings/${encodeURIComponent(findingId)}/fix-plan`),
};

export const reportApi = {
  export: (body: ReportExportRequest) => http.blob('/reports/export', body),
};

export const userApi = {
  me: (signal?: AbortSignal) => http.get<UserProfile>('/me', undefined, signal),
  updateMe: (body: Partial<Omit<UserProfile, 'id'>>) => http.patch<UserProfile>('/me', body),
  settings: (signal?: AbortSignal) => http.get<AppSettings>('/me/settings', undefined, signal),
  updateSettings: (body: AppSettings) => http.put<AppSettings>('/me/settings', body),
  notifications: (signal?: AbortSignal) => http.get<AppNotification[]>('/me/notifications', undefined, signal),
  markNotificationsRead: (ids: string[]) => http.post<void>('/me/notifications/read', { ids }),
};
