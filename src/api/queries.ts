import { QueryCache, QueryClient, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { AccessRequestStatus, AppSettings, Assessment, CreateAssessmentRequest, DataRecordQuery, Finding, Paginated, SalesforceAppConfig, SalesforceAppUpdate, ScanScheduleUpdate, TeamMember, TeamMemberCreate, UpdateFindingRequest, UserProfile, UserRole } from '@/types';
import { isApiError } from './client';
import { accessApi, adminApi, assessmentApi, authApi, connectionApi, consultantApi, dataApi, findingApi, reportApi, systemApi, teamApi, userApi } from './endpoints';

export const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({
    // A 401 on any request means the session ended: re-check identity so RequireAuth redirects to login.
    onError: (err, query) => {
      if (isApiError(err) && err.status === 401 && query.queryKey[0] !== 'me') {
        queryClient.invalidateQueries({ queryKey: ['me'], exact: true });
      }
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      // Never retry 4xx client errors. If the server can't be reached (a restart, a dev server being
      // replaced), keep trying for ~30 s before showing "unavailable"; other failures retry twice.
      retry: (count, err) => {
        if (isApiError(err) && err.kind === 'http' && err.status !== null && err.status < 500) return false;
        if (isApiError(err) && err.isUnavailable) return count < 6;
        return count < 2;
      },
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
    },
  },
});

export const qk = {
  health: ['health'] as const,
  connection: ['connection'] as const,
  salesforceApp: ['salesforce-app'] as const,
  data: ['data'] as const,
  assessments: (params?: object) => ['assessments', params ?? {}] as const,
  assessment: (id: string) => ['assessment', id] as const,
  results: (id: string) => ['assessment', id, 'results'] as const,
  findings: (id: string) => ['assessment', id, 'findings'] as const,
  me: ['me'] as const,
  settings: ['me', 'settings'] as const,
  notifications: ['me', 'notifications'] as const,
  portfolio: ['portfolio'] as const,
};

const ACTIVE: Assessment['status'][] = ['queued', 'running'];
const isActive = (a?: Pick<Assessment, 'status'> | null) => !!a && ACTIVE.includes(a.status);

/**
 * When polling sees an assessment leave queued/running, refresh every list that
 * filters by status (e.g. "completed") so dashboards pick up the new results.
 */
function syncFinished(prev: Assessment[], next: Assessment[]) {
  const before = new Map(prev.map((a) => [a.id, a.status]));
  const finished = next.some((a) => {
    const s = before.get(a.id);
    return s !== undefined && ACTIVE.includes(s) && !isActive(a);
  });
  if (finished) {
    queryClient.invalidateQueries({ queryKey: ['assessments'] });
    queryClient.invalidateQueries({ queryKey: qk.notifications });
  }
}

// ---------------- System ----------------

export const useApiHealth = () =>
  useQuery({ queryKey: qk.health, queryFn: ({ signal }) => systemApi.health(signal), refetchInterval: 60_000, retry: 1 });

// ---------------- Salesforce connection ----------------

export const useConnection = () =>
  useQuery({ queryKey: qk.connection, queryFn: ({ signal }) => connectionApi.get(signal) });

export const useStartOAuth = () => useMutation({ mutationFn: connectionApi.startOAuth });

export function useCompleteOAuth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: connectionApi.completeOAuth,
    onSuccess: (conn) => qc.setQueryData(qk.connection, conn),
  });
}

export function useCheckConnection() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: connectionApi.check, onSuccess: (conn) => qc.setQueryData(qk.connection, conn) });
}

export function useDisconnect() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: connectionApi.disconnect,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.connection });
      qc.removeQueries({ queryKey: qk.data }); // don't keep showing the old org's data
    },
  });
}

// ---------------- Salesforce app (Connected App keys) ----------------

export const useSalesforceApp = () =>
  useQuery({ queryKey: qk.salesforceApp, queryFn: ({ signal }) => connectionApi.getApp(signal) });

/** Saving or removing keys can end the current connection, so refresh it too. */
function useAppMutation<TArg>(fn: (arg: TArg) => Promise<SalesforceAppConfig>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (cfg) => {
      qc.setQueryData(qk.salesforceApp, cfg);
      qc.invalidateQueries({ queryKey: qk.connection });
    },
  });
}

export const useSaveSalesforceApp = () => useAppMutation((body: SalesforceAppUpdate) => connectionApi.saveApp(body));
export const useClearSalesforceApp = () => useAppMutation((_: void) => connectionApi.clearApp());

// ---------------- Data explorer ----------------

const DATA_STALE = 5 * 60_000;

export const useDataObjects = (enabled = true) =>
  useQuery({ queryKey: [...qk.data, 'objects'], queryFn: ({ signal }) => dataApi.objects(signal), staleTime: DATA_STALE, enabled });

export const useDataObject = (name: string | undefined) =>
  useQuery({
    queryKey: [...qk.data, 'object', name],
    queryFn: ({ signal }) => dataApi.object(name!, signal),
    staleTime: DATA_STALE,
    enabled: !!name,
  });

export const useDataRecords = (name: string | undefined, query: DataRecordQuery, enabled = true) =>
  useInfiniteQuery({
    queryKey: [...qk.data, 'records', name, query],
    queryFn: ({ signal, pageParam }) => dataApi.records(name!, query, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor,
    staleTime: 60_000,
    enabled: !!name && enabled,
  });

export const useDataSearch = (q: string, objects: string[] | undefined, enabled = true) =>
  useQuery({
    queryKey: [...qk.data, 'search', q, objects ?? null],
    queryFn: ({ signal }) => dataApi.search(q, objects, signal),
    enabled: enabled && q.trim().length >= 2,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  });

export const useDataAsk = () => useMutation({ mutationFn: dataApi.ask });

export const useDataRecord = (name: string | undefined, id: string | null) =>
  useQuery({
    queryKey: [...qk.data, 'record', name, id],
    queryFn: ({ signal }) => dataApi.record(name!, id!, signal),
    enabled: !!name && !!id,
  });

export const useDataRelated = (name: string, id: string | null, relationship: string) =>
  useQuery({
    queryKey: [...qk.data, 'related', name, id, relationship],
    queryFn: ({ signal }) => dataApi.related(name, id!, relationship, signal),
    enabled: !!id,
    staleTime: 60_000,
  });

export function useRefreshData() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: dataApi.refresh, onSuccess: () => qc.invalidateQueries({ queryKey: qk.data }) });
}

// ---------------- Assessments ----------------

export const useAssessments = () =>
  useQuery({
    queryKey: qk.assessments(),
    queryFn: async ({ signal }) => {
      const prev = queryClient.getQueryData<Paginated<Assessment>>(qk.assessments())?.items ?? [];
      const next = await assessmentApi.list({}, signal);
      syncFinished(prev, next.items);
      return next;
    },
    select: (d: Paginated<Assessment>) => d.items,
    // Poll while any assessment is executing so status/progress stay current.
    refetchInterval: (q) => (q.state.data?.items.some((a) => ACTIVE.includes(a.status)) ? 5_000 : false),
  });

/** Completed assessments, newest first. `[0]` is the latest. */
export const useCompletedAssessments = () =>
  useQuery({
    queryKey: qk.assessments({ status: 'completed' }),
    queryFn: ({ signal }) => assessmentApi.list({ status: 'completed', sort: '-completedAt', pageSize: 24 }, signal),
    select: (d: Paginated<Assessment>) => d.items,
  });

export const useAssessment = (id: string | null) =>
  useQuery({
    queryKey: qk.assessment(id ?? ''),
    queryFn: async ({ signal }) => {
      const prev = queryClient.getQueryData<Assessment>(qk.assessment(id!));
      const next = await assessmentApi.get(id!, signal);
      if (prev) syncFinished([prev], [next]);
      return next;
    },
    enabled: !!id,
    refetchInterval: (q) => (q.state.data && ACTIVE.includes(q.state.data.status) ? 3_000 : false),
  });

export const useAssessmentResults = (id: string | null, enabled = true) =>
  useQuery({
    queryKey: qk.results(id ?? ''),
    queryFn: ({ signal }) => assessmentApi.results(id!, signal),
    enabled: !!id && enabled,
  });

export const useFindings = (id: string | null, enabled = true) =>
  useQuery({
    queryKey: qk.findings(id ?? ''),
    queryFn: ({ signal }) => assessmentApi.findings(id!, signal),
    enabled: !!id && enabled,
    select: (d: Paginated<Finding>) => d.items,
  });

export function useCreateAssessment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateAssessmentRequest) => assessmentApi.create(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['assessments'] }),
  });
}

export function useCancelAssessment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: assessmentApi.cancel,
    onSuccess: (a) => {
      qc.setQueryData(qk.assessment(a.id), a);
      qc.invalidateQueries({ queryKey: ['assessments'] });
    },
  });
}

export const useFindingRecords = (findingId: string | null, enabled = true) =>
  useInfiniteQuery({
    queryKey: ['finding-records', findingId],
    queryFn: ({ signal, pageParam }) => findingApi.records(findingId!, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor,
    enabled: !!findingId && enabled,
    staleTime: 60_000,
  });

export function useUpdateFinding(assessmentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: UpdateFindingRequest }) => findingApi.update(id, body),
    onSuccess: (updated) =>
      qc.setQueryData<Paginated<Finding>>(qk.findings(assessmentId), (old) =>
        old ? { ...old, items: old.items.map((f) => (f.id === updated.id ? updated : f)) } : old,
      ),
  });
}

export const useExportReport = () => useMutation({ mutationFn: reportApi.export });

// ---------------- User ----------------

export const useMe = () => useQuery({ queryKey: qk.me, queryFn: ({ signal }) => userApi.me(signal), staleTime: 5 * 60_000 });

// ---------------- Auth ----------------

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: authApi.login,
    onSuccess: (me) => {
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'me' });
      qc.setQueryData(qk.me, me);
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: authApi.logout,
    // Clear cached customer data even if the request fails, so nothing lingers in memory.
    onSettled: () => qc.clear(),
  });
}

export const useSsoStart = () => useMutation({ mutationFn: authApi.ssoStart });

/** Sign-in mode comes from the server, so the website and API always agree. */
export const useAuthStatus = () =>
  useQuery({ queryKey: ['auth', 'status'], queryFn: ({ signal }) => authApi.status(signal), staleTime: 5 * 60_000, retry: 1 });

export function useSetup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: authApi.setup,
    onSuccess: (me) => {
      qc.setQueryData(qk.me, me);
      qc.invalidateQueries({ queryKey: ['auth', 'status'] });
    },
  });
}

export function useChangePassword() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: authApi.changePassword, onSuccess: () => qc.invalidateQueries({ queryKey: qk.me }) });
}

/** What the signed-in person may do (the server enforces the same rules). */
export function useRole() {
  const me = useMe();
  const role = (me.data?.role ?? 'viewer') as UserRole;
  return { role, isAdmin: role === 'admin', canEdit: role === 'admin' || role === 'consultant', loading: me.isLoading };
}

export const useTeam = (enabled = true) => useQuery({ queryKey: ['team'], queryFn: ({ signal }) => teamApi.list(signal), enabled });

export function useCreateMember() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (body: TeamMemberCreate) => teamApi.create(body), onSuccess: () => invalidateTeam(qc) });
}

export function useUpdateMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<Pick<TeamMember, 'name' | 'role' | 'allOrgs' | 'orgIds' | 'isActive'>> }) => teamApi.update(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['team'] }),
  });
}

const invalidateTeam = (qc: QueryClient) => {
  qc.invalidateQueries({ queryKey: ['team'] });
  qc.invalidateQueries({ queryKey: ['admin'] });
};

export function useUnlockMember() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => teamApi.unlock(id), onSuccess: () => invalidateTeam(qc) });
}

export function useSignOutMember() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => teamApi.signOut(id), onSuccess: () => invalidateTeam(qc) });
}

// ---------------- Admin Panel ----------------

export const useAdminOverview = (enabled = true) =>
  useQuery({ queryKey: ['admin', 'overview'], queryFn: ({ signal }) => adminApi.overview(signal), enabled, refetchInterval: 60_000 });
export const useAccessRequests = (status?: AccessRequestStatus) =>
  useQuery({ queryKey: ['admin', 'requests', status ?? 'all'], queryFn: ({ signal }) => adminApi.requests(status, signal) });
export const useAuditLog = () => useQuery({ queryKey: ['admin', 'activity'], queryFn: ({ signal }) => adminApi.activity(signal) });

export function useDecideRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, approve, ...body }: { id: string; approve: boolean; orgIds?: string[]; allOrgs?: boolean; role?: UserRole; note?: string }) =>
      approve ? adminApi.approve(id, body) : adminApi.reject(id, body.note),
    onSuccess: () => invalidateTeam(qc),
  });
}

export const useMyAccessRequests = () => useQuery({ queryKey: ['access-requests', 'mine'], queryFn: ({ signal }) => accessApi.mine(signal) });

export function useRequestAccess() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: accessApi.create, onSuccess: () => qc.invalidateQueries({ queryKey: ['access-requests'] }) });
}

export function useCancelAccessRequest() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: accessApi.cancel, onSuccess: () => qc.invalidateQueries({ queryKey: ['access-requests'] }) });
}

export const useResetMemberPassword = () => useMutation({ mutationFn: ({ id, password }: { id: string; password: string }) => teamApi.resetPassword(id, password) });
export const useForgotPassword = () => useMutation({ mutationFn: authApi.forgotPassword });

export function useUpdateMe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<Omit<UserProfile, 'id'>>) => userApi.updateMe(body),
    onSuccess: (me) => qc.setQueryData(qk.me, me),
  });
}

export const useSettings = () => useQuery({ queryKey: qk.settings, queryFn: ({ signal }) => userApi.settings(signal) });

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AppSettings) => userApi.updateSettings(body),
    onSuccess: (s) => qc.setQueryData(qk.settings, s),
  });
}

export const useNotifications = () =>
  useQuery({ queryKey: qk.notifications, queryFn: ({ signal }) => userApi.notifications(signal), refetchInterval: 60_000 });

export function useMarkNotificationsRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: userApi.markNotificationsRead,
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.notifications }),
  });
}

// ---------------- Consultant features: portfolio, schedules, proposals, benchmarks, fix plans ----------------

export const usePortfolio = () =>
  useQuery({ queryKey: qk.portfolio, queryFn: ({ signal }) => consultantApi.portfolio(signal), refetchInterval: 30_000 });

/** Switch the active org: everything shown (data, checks, results) belongs to it, so refetch it all. */
export function useActivateOrg() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: consultantApi.activate,
    onSuccess: () => {
      qc.removeQueries({ queryKey: qk.data });
      qc.invalidateQueries();
    },
  });
}

export function useRemoveOrg() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: consultantApi.removeOrg,
    onSuccess: () => {
      qc.removeQueries({ queryKey: qk.data });
      qc.invalidateQueries();
    },
  });
}

export function useSaveSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ orgId, body }: { orgId: string; body: ScanScheduleUpdate }) => consultantApi.putSchedule(orgId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.portfolio }),
  });
}

export function useDeleteSchedule() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: consultantApi.deleteSchedule, onSuccess: () => qc.invalidateQueries({ queryKey: qk.portfolio }) });
}

export const useTestAlertEmail = () => useMutation({ mutationFn: consultantApi.testEmail });

export const useProposal = (id: string | null, rate: number, currency: string) =>
  useQuery({
    queryKey: ['assessment', id, 'proposal', rate, currency],
    queryFn: ({ signal }) => consultantApi.proposal(id!, rate, currency, signal),
    enabled: !!id,
    staleTime: 5 * 60_000,
  });

export const useBenchmarks = (id: string | null) =>
  useQuery({ queryKey: ['assessment', id, 'benchmarks'], queryFn: ({ signal }) => consultantApi.benchmarks(id!, signal), enabled: !!id });

export const useFixPlan = () => useMutation({ mutationFn: consultantApi.fixPlan });
