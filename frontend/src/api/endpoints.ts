import type {
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

export const connectionApi = {
  get: (signal?: AbortSignal) => http.get<SalesforceConnection>('/salesforce/connection', undefined, signal),
  startOAuth: (body: OAuthStartRequest) => http.post<OAuthStartResponse>('/salesforce/oauth/start', body),
  completeOAuth: (body: OAuthCallbackRequest) => http.post<SalesforceConnection>('/salesforce/oauth/callback', body),
  check: () => http.post<SalesforceConnection>('/salesforce/connection/check'),
  /** Live limits, users, record counts and response time of the active org. */
  snapshot: (signal?: AbortSignal) => http.get<ConnectionSnapshot>('/salesforce/connection/snapshot', undefined, signal),
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
  /** The records a problem is about, live from Salesforce. */
  records: (id: string, cursor: string | null, signal?: AbortSignal) =>
    http.get<FindingRecordsPage>(`/findings/${encodeURIComponent(id)}/records`, { cursor: cursor ?? undefined }, signal),
  /** Link that downloads the affected records as a CSV file. */
  recordsCsvUrl: (id: string) => `${API_BASE_URL}/findings/${encodeURIComponent(id)}/records.csv`,
};

/** The records one measure ("What we measure") counted, live from Salesforce. */
export const indicatorApi = {
  records: (assessmentId: string, areaId: string, label: string, object: string, cursor: string | null, signal?: AbortSignal) =>
    http.get<FindingRecordsPage>(
      `/assessments/${encodeURIComponent(assessmentId)}/areas/${encodeURIComponent(areaId)}/indicator-records`,
      { label, object, cursor: cursor ?? undefined },
      signal,
    ),
  csvUrl: (assessmentId: string, areaId: string, label: string, object: string) =>
    `${API_BASE_URL}/assessments/${encodeURIComponent(assessmentId)}/areas/${encodeURIComponent(areaId)}/indicator-records.csv?${new URLSearchParams({ label, object })}`,
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
