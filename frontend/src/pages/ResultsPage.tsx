import { motion } from 'framer-motion';
import { AlertOctagon, Ban, CircleAlert, CircleDashed, FilterX, ListChecks, OctagonAlert, Play, SearchX, ShieldAlert, TriangleAlert } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { errorMessage } from '@/api/client';
import { useAssessment, useAssessmentResults, useAssessments, useCancelAssessment, useFindings } from '@/api/queries';
import { ResolvedCard } from '@/components/findings/ResolvedCard';
import { FindingDetailsPanel } from '@/components/findings/FindingDetailsPanel';
import { FindingsTable } from '@/components/findings/FindingsTable';
import { AssessmentStatusBadge, FINDING_STATUS_LABEL } from '@/components/ui/Badges';
import { Button, LinkButton } from '@/components/ui/Button';
import { SearchInput, Select } from '@/components/ui/Form';
import { PageHeader, StaggerGrid, StaggerItem } from '@/components/ui/Page';
import { EmptyState, ErrorState, InlineError, LoadingState } from '@/components/ui/States';
import { AnimatedNumber } from '@/components/ui/Visuals';
import { CATEGORIES, DIAGNOSTIC_AREAS } from '@/config/categories';
import { useToast } from '@/context/ToastContext';
import { cx, fmtDate, fmtDateTime, fmtNumber } from '@/lib/format';
import { countBySeverity, SEVERITIES } from '@/lib/health';
import type { Assessment, FindingStatus } from '@/types';

const SUMMARY = [
  { key: 'total',    label: 'Problems Found',       icon: ListChecks,  cls: 'text-brand bg-brand-soft',          hint: 'All problems found' },
  { key: 'critical', label: 'Urgent — Fix Now',     icon: OctagonAlert, cls: 'text-sev-critical bg-sev-critical/10', hint: 'Fix these now' },
  { key: 'high',    label: 'High Priority',         icon: ShieldAlert, cls: 'text-sev-high bg-sev-high/10',      hint: 'Fix these soon' },
  { key: 'medium',  label: 'Medium Priority',       icon: TriangleAlert, cls: 'text-sev-medium bg-sev-medium/10', hint: 'Plan a fix' },
  { key: 'low',     label: 'Low Priority',          icon: CircleAlert, cls: 'text-sev-low bg-sev-low/10',        hint: 'Fix when you can' },
] as const;

function RunningPanel({ assessment }: { assessment: Assessment }) {
  const cancel = useCancelAssessment();
  const { notify } = useToast();
  const pct = assessment.progress ?? 0;
  return (
    <div className="card p-8">
      <div className="mx-auto max-w-xl text-center">
        <CircleDashed className="mx-auto h-10 w-10 animate-spin text-brand" />
        <h2 className="mt-3 text-lg font-semibold">
          {assessment.status === 'queued' ? 'Your health check is queued' : 'Health check in progress…'}
        </h2>
        <p className="mt-1 text-sm text-ink-muted">
          {assessment.currentStep
            ? assessment.currentStep
            : assessment.status === 'queued'
              ? 'Waiting to start…'
              : 'Checking your Salesforce. This takes a few minutes.'}
        </p>
        <div className="mt-5 h-2 overflow-hidden rounded-full bg-muted">
          <motion.div className="relative h-full overflow-hidden rounded-full bg-brand" animate={{ width: `${pct}%` }} transition={{ duration: 0.6 }}>
            <span className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-white/40 to-transparent" />
          </motion.div>
        </div>
        <p className="mt-2 text-xs tabular-nums text-ink-subtle">
          {pct}% complete · started {assessment.startedAt ? fmtDateTime(assessment.startedAt) : '—'} · this page updates automatically
        </p>
        <Button
          className="mt-5"
          variant="danger"
          size="sm"
          icon={<Ban className="h-3.5 w-3.5" />}
          disabled={cancel.isPending}
          onClick={() => cancel.mutate(assessment.id, { onSuccess: () => notify('Health check cancelled', assessment.name) })}
        >
          Cancel this check
        </Button>
        <div className="mt-3">
          <InlineError error={cancel.error} />
        </div>
      </div>
    </div>
  );
}

export default function ResultsPage() {
  const [params, setParams] = useSearchParams();
  const list = useAssessments();
  const assessments = list.data ?? [];
  const fallbackId = assessments.find((a) => a.status === 'completed')?.id ?? assessments[0]?.id ?? null;
  const assessmentId = params.get('assessment') ?? fallbackId;

  const detail = useAssessment(assessmentId);
  const assessment = detail.data ?? assessments.find((a) => a.id === assessmentId) ?? null;
  const completed = assessment?.status === 'completed';
  const findingsQ = useFindings(assessmentId, completed);
  const resultsQ = useAssessmentResults(assessmentId, completed);

  const [q, setQ] = useState('');
  const category = params.get('category') ?? 'all';
  const area = params.get('area') ?? 'all';
  const severity = params.get('severity') ?? 'all';
  const status = params.get('status') ?? 'all';
  const object = params.get('object') ?? 'all';
  const [selectedId, setSelectedId] = useState<string | null>(params.get('finding'));

  useEffect(() => {
    const id = params.get('finding');
    if (id) setSelectedId(id);
  }, [params]);

  const setParam = (key: string, value: string) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        if (value === 'all' || !value) n.delete(key);
        else n.set(key, value);
        if (key === 'category') n.delete('area');
        return n;
      },
      { replace: true },
    );

  const all = useMemo(() => findingsQ.data ?? [], [findingsQ.data]);
  const selected = all.find((f) => f.id === selectedId) ?? null;

  // Summary cards reflect every filter except severity, so they double as a severity switcher.
  const baseFiltered = useMemo(() => {
    const term = q.trim().toLowerCase();
    return all.filter(
      (f) =>
        (category === 'all' || f.categoryId === category) &&
        (area === 'all' || f.areaId === area) &&
        (status === 'all' || f.status === status) &&
        (object === 'all' || f.objectName === object) &&
        (!term ||
          f.name.toLowerCase().includes(term) ||
          f.id.toLowerCase().includes(term) ||
          f.businessImpact.toLowerCase().includes(term) ||
          f.recommendedAction.toLowerCase().includes(term)),
    );
  }, [all, q, category, area, status, object]);
  const filtered = severity === 'all' ? baseFiltered : baseFiltered.filter((f) => f.severity === severity);
  const counts: Record<string, number> = { total: baseFiltered.length, ...countBySeverity(baseFiltered) };

  const areaOptions = DIAGNOSTIC_AREAS.filter((a) => category === 'all' || a.categoryId === category);
  const anyFilter = q || category !== 'all' || area !== 'all' || severity !== 'all' || status !== 'all' || object !== 'all';
  // Objects that have problems in this check (plus the one in the URL, so the filter always shows it).
  const objectOptions = useMemo(() => {
    const names = new Set(all.map((f) => f.objectName).filter((n): n is string => !!n));
    if (object !== 'all') names.add(object);
    return [...names].sort();
  }, [all, object]);
  const clear = () => {
    setQ('');
    setParams(assessmentId ? { assessment: assessmentId } : {}, { replace: true });
  };
  const closePanel = () => {
    setSelectedId(null);
    if (params.get('finding')) setParam('finding', '');
  };

  return (
    <div>
      <PageHeader
        title="Health Check Results"
        description="Every problem we found. Click one to see how to fix it."
        actions={
          assessments.length > 0 && (
            <Select
              label="Which health check?"
              value={assessmentId ?? ''}
              onChange={(v) => setParams({ assessment: v })}
              className="w-full sm:w-80"
              options={assessments.map((a) => ({ value: a.id, label: `${a.name} · ${fmtDate(a.completedAt ?? a.createdAt)}` }))}
            />
          )
        }
      />

      {list.isLoading ? (
        <div className="card">
          <LoadingState rows={6} label="Loading your health checks…" />
        </div>
      ) : list.error ? (
        <div className="card">
          <ErrorState error={list.error} onRetry={() => list.refetch()} />
        </div>
      ) : !assessmentId ? (
        <div className="card">
          <EmptyState
            title="No health checks run yet"
            description="Run a health check to see your problems here."
            action={
              <LinkButton to="/assessment" variant="primary" size="sm" icon={<Play className="h-3.5 w-3.5" />}>
                Run my first health check
              </LinkButton>
            }
          />
        </div>
      ) : detail.error && !assessment ? (
        <div className="card">
          <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
        </div>
      ) : !assessment ? (
        <div className="card">
          <LoadingState rows={6} />
        </div>
      ) : (
        <>
          {/* Meta row */}
          <div className="mb-6 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-ink-muted">
            <span>
              <span className="text-ink-subtle">Salesforce:</span>{' '}
              <span className="font-medium text-ink">{assessment.organizationName}</span>
            </span>
            {assessment.recordsAssessed !== null && (
              <span>
                <span className="text-ink-subtle">Records checked:</span> {fmtNumber(assessment.recordsAssessed)}
              </span>
            )}
            {assessment.completedAt && (
              <span>
                <span className="text-ink-subtle">Completed:</span> {fmtDateTime(assessment.completedAt)}
              </span>
            )}
            <AssessmentStatusBadge status={assessment.status} />
          </div>

          {assessment.status === 'running' || assessment.status === 'queued' ? (
            <RunningPanel assessment={assessment} />
          ) : assessment.status === 'failed' ? (
            <div className="card">
              <EmptyState
                icon={<AlertOctagon className="h-6 w-6 text-bad" />}
                title="This health check didn't complete"
                description={assessment.errorMessage ?? 'Something went wrong. Please start a new check.'}
                action={
                  <LinkButton to="/assessment" size="sm" variant="primary">
                    Start a new health check
                  </LinkButton>
                }
              />
            </div>
          ) : assessment.status === 'cancelled' ? (
            <div className="card">
              <EmptyState
                icon={<Ban className="h-6 w-6" />}
                title="This check was cancelled"
                description="No results were saved."
              />
            </div>
          ) : (
            <>
              {resultsQ.data?.resolved && resultsQ.data.resolved.length > 0 && <ResolvedCard resolved={resultsQ.data.resolved} />}

              {/* Summary cards — also act as severity filters */}
              <StaggerGrid className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
                {SUMMARY.map((s) => {
                  const active = s.key !== 'total' && severity === s.key;
                  return (
                    <StaggerItem key={s.key} className="h-full">
                      <button
                        onClick={() => setParam('severity', s.key === 'total' || severity === s.key ? 'all' : s.key)}
                        className={cx(
                          'card card-pad flex h-full w-full flex-col items-start text-left transition hover:shadow-pop',
                          active ? 'ring-2 ring-brand/50' : 'hover:-translate-y-0.5',
                        )}
                        aria-pressed={active}
                        title={s.hint}
                      >
                        <span className={`flex h-9 w-9 items-center justify-center rounded-lg ${s.cls}`}>
                          <s.icon className="h-[18px] w-[18px]" />
                        </span>
                        <p className="mt-3 text-[13px] font-medium text-ink-muted">{s.label}</p>
                        <p className="mt-1 text-[28px] font-semibold leading-none">
                          {findingsQ.isLoading ? '—' : <AnimatedNumber value={counts[s.key]} duration={0.6} />}
                        </p>
                        <p className="mt-1 text-[11px] text-ink-subtle">
                          {s.key === 'total' ? (severity === 'all' ? 'All urgency levels' : 'Click to show all') : active ? 'Click to clear filter' : 'Click to filter'}
                        </p>
                      </button>
                    </StaggerItem>
                  );
                })}
              </StaggerGrid>

              {/* Filter bar */}
              <div className="card">
                <div className="flex flex-col gap-3 border-b border-line p-4 xl:flex-row xl:items-center">
                  <SearchInput value={q} onChange={setQ} placeholder="Search problems…" className="xl:w-80" />
                  <div className={cx('grid flex-1 grid-cols-1 gap-2 sm:grid-cols-2', objectOptions.length ? 'lg:grid-cols-5' : 'lg:grid-cols-4')}>
                    <Select
                      label="Topic area"
                      value={category}
                      onChange={(v) => setParam('category', v)}
                      options={[{ value: 'all', label: 'All topic areas' }, ...CATEGORIES.map((c) => ({ value: c.id, label: c.name }))]}
                    />
                    <Select
                      label="Specific check"
                      value={area}
                      onChange={(v) => setParam('area', v)}
                      options={[{ value: 'all', label: 'All checks' }, ...areaOptions.map((a) => ({ value: a.id, label: `#${a.number}: ${a.name}` }))]}
                    />
                    {objectOptions.length > 0 && (
                      <Select
                        label="Object"
                        value={object}
                        onChange={(v) => setParam('object', v)}
                        options={[{ value: 'all', label: 'All objects' }, ...objectOptions.map((o) => ({ value: o, label: o }))]}
                      />
                    )}
                    <Select
                      label="Urgency"
                      value={severity}
                      onChange={(v) => setParam('severity', v)}
                      options={[{ value: 'all', label: 'All urgency levels' }, ...SEVERITIES.map((s) => ({ value: s, label: s[0].toUpperCase() + s.slice(1) }))]}
                    />
                    <Select
                      label="Progress"
                      value={status}
                      onChange={(v) => setParam('status', v)}
                      options={[
                        { value: 'all', label: 'All statuses' },
                        ...(Object.keys(FINDING_STATUS_LABEL) as FindingStatus[]).map((s) => ({ value: s, label: FINDING_STATUS_LABEL[s] })),
                      ]}
                    />
                  </div>
                  {anyFilter && (
                    <Button size="sm" variant="ghost" icon={<FilterX className="h-4 w-4" />} onClick={clear}>
                      Clear filters
                    </Button>
                  )}
                </div>
                <p className="px-4 py-2.5 text-xs text-ink-subtle">
                  Showing <span className="font-semibold text-ink">{filtered.length}</span> of {all.length} problems · click a column header to sort
                </p>
                {findingsQ.isLoading ? (
                  <LoadingState rows={8} label="Loading problems…" />
                ) : findingsQ.error ? (
                  <ErrorState error={findingsQ.error} onRetry={() => findingsQ.refetch()} />
                ) : all.length === 0 ? (
                  <EmptyState
                    title="No problems found"
                    description="Great news — this health check didn't find any issues in the areas that were checked."
                  />
                ) : filtered.length === 0 ? (
                  <EmptyState
                    icon={<SearchX className="h-6 w-6" />}
                    title="No results match your filters"
                    description="Try changing the filters."
                    action={
                      <Button size="sm" onClick={clear}>
                        Clear all filters
                      </Button>
                    }
                  />
                ) : (
                  <FindingsTable findings={filtered} onSelect={(f) => setSelectedId(f.id)} />
                )}
              </div>
            </>
          )}
          {detail.error && <p className="mt-3 text-xs text-ink-subtle">Status refresh failed: {errorMessage(detail.error)}</p>}
        </>
      )}

      <FindingDetailsPanel finding={selected} onClose={closePanel} />
    </div>
  );
}
