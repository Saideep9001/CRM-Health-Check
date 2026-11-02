import { ArrowRight, Cloud, Database, FileBarChart, Gauge, LayoutGrid, ListChecks, OctagonAlert, Play, TriangleAlert, Workflow } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { isApiError } from '@/api/client';
import { useApiHealth, useAssessments } from '@/api/queries';
import { AssessmentTable } from '@/components/assessments/AssessmentTable';
import { FindingsBySeverityChart, IssuesByCategoryChart, ScoreTrendChart, SEVERITY_COLORS } from '@/components/charts/Charts';
import { CategoryCard } from '@/components/dashboard/CategoryCard';
import { GettingStarted } from '@/components/dashboard/GettingStarted';
import { HealthHero } from '@/components/dashboard/HealthHero';
import { HealthScoreCard } from '@/components/dashboard/HealthScoreCard';
import { InfoTip } from '@/components/ui/HelpTip';
import { Button, LinkButton } from '@/components/ui/Button';
import { PageHeader, SectionCard, StaggerGrid, StaggerItem } from '@/components/ui/Page';
import { EmptyState, ErrorState, LoadingState, Skeleton } from '@/components/ui/States';
import { CATEGORIES, CATEGORY_COLORS } from '@/config/categories';
import { useLatestAssessment } from '@/hooks/useLatestAssessment';
import { SEVERITIES, SEVERITY_RANK, countBySeverity, delta, pctChange } from '@/lib/health';
import { fmtNumber } from '@/lib/format';
import type { Finding, HealthMetric, Severity } from '@/types';

const KPI_META = {
  overall: {
    icon: Gauge,
    accent: '#3b82f6',
    hint: 'A score from 0 to 100 (not a percentage): the average of the topic scores below. 100 means no problems were found. 80+ healthy, 65–79 fair, below 65 needs attention.',
  },
  dataQuality: {
    icon: Database,
    accent: '#14b8a6',
    hint: 'Score out of 100 for the Data Quality & Optimization topic: duplicate, missing and invalid values in your records, and unused or look-alike fields.',
  },
  salesProcess: {
    icon: Workflow,
    accent: '#8b5cf6',
    hint: 'The average score of two topics: Workflows & Automation (lead assignment, stale leads, stage progression, overdue and stuck deals, automation) and Reporting & Dashboards (unused, outdated and duplicate reports and dashboards). Out of 100.',
  },
  records: {
    icon: LayoutGrid,
    accent: '#06b6d4',
    hint: 'How many Salesforce records the last check read.',
  },
  issues: {
    icon: TriangleAlert,
    accent: '#f59e0b',
    lowerIsBetter: true,
    hint: 'Every problem the last check found, by topic. Click a topic to see only its problems.',
  },
  critical: {
    icon: OctagonAlert,
    accent: '#ef4444',
    lowerIsBetter: true,
    hint: 'Critical problems: they block the sales process or affect most of the records checked. Fix these first.',
  },
} as const;

const URGENCY_MEANING: Record<Severity, string> = {
  critical: 'Blocks the sales process or affects most records. Fix now.',
  high: 'Causes wrong numbers or lost deals. Fix this month.',
  medium: 'Slows people down or makes reports less reliable. Plan it in.',
  low: 'Tidy-up. Fix when convenient.',
};

/** Each urgency level: what it means, and its biggest problems by name (so the counts are never just numbers). */
function UrgencyList({ findings, worstFirst, assessmentId }: { findings: Finding[]; worstFirst: (l: Finding[]) => Finding[]; assessmentId: string }) {
  const levels = SEVERITIES.map((s) => ({ s, list: worstFirst(findings.filter((f) => f.severity === s)) })).filter((x) => x.list.length);
  if (!levels.length) return null;
  return (
    <ul className="mt-5 space-y-3 border-t border-line pt-4">
      {levels.map(({ s, list }) => (
        <li key={s} className="text-sm">
          <div className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: SEVERITY_COLORS[s] }} />
            <Link to={`/results?assessment=${assessmentId}&severity=${s}`} className="font-semibold capitalize hover:text-brand">{s} · {list.length}</Link>
            <span className="text-xs text-ink-subtle">{URGENCY_MEANING[s]}</span>
          </div>
          <ul className="ml-4 mt-1 space-y-0.5 text-xs text-ink-muted">
            {list.slice(0, 3).map((f) => (
              <li key={f.id} className="truncate">
                <Link to={`/problems/${encodeURIComponent(f.id)}`} className="hover:text-brand">
                  {f.name}
                  {f.affectedRecords > 0 && <span className="text-ink-subtle"> · {fmtNumber(f.affectedRecords)} records</span>}
                </Link>
              </li>
            ))}
            {list.length > 3 && <li className="text-ink-subtle">+{list.length - 3} more</li>}
          </ul>
        </li>
      ))}
    </ul>
  );
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const data = useLatestAssessment();
  const all = useAssessments();
  const health = useApiHealth();
  const { latest, previous, results, findings, history } = data;
  const running = (all.data ?? []).some((a) => a.status === 'running' || a.status === 'queued');

  const metrics: HealthMetric[] = latest
    ? [
        {
          key: 'overall',
          label: 'Overall Health Score',
          unit: 'score',
          value: results?.overallScore ?? latest.overallScore,
          trend: delta(results?.overallScore ?? latest.overallScore, previous?.overallScore),
        },
        { key: 'dataQuality', label: 'Data Quality', unit: 'score', value: results?.dataQualityScore ?? null, trend: null },
        { key: 'salesProcess', label: 'Sales Process Health', unit: 'score', value: results?.salesProcessScore ?? null, trend: null },
        {
          key: 'records',
          label: 'Records Checked',
          unit: 'count',
          value: results?.recordsAssessed ?? latest.recordsAssessed,
          trend: pctChange(results?.recordsAssessed ?? latest.recordsAssessed, previous?.recordsAssessed),
        },
        {
          key: 'issues',
          label: 'Total Problems Found',
          unit: 'count',
          value: findings.length,
          trend: pctChange(findings.length, previous?.findingsCount),
        },
        {
          key: 'critical',
          label: 'Critical Problems',
          unit: 'count',
          value: countBySeverity(findings).critical,
          trend: null,
        },
      ]
    : [];
  const overallSpark = [...history].reverse().map((a) => a.overallScore).filter((s): s is number => s !== null);
  const byTopic = CATEGORIES.map((c) => ({ c, n: findings.filter((f) => f.categoryId === c.id).length })).filter((x) => x.n > 0);
  const worstFirst = (list: Finding[]) => [...list].sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || b.affectedRecords - a.affectedRecords);
  const critical = worstFirst(findings.filter((f) => f.severity === 'critical'));
  const problemLink = (f: Finding) => `/problems/${encodeURIComponent(f.id)}`;
  const footers: Partial<Record<string, React.ReactNode>> = latest
    ? {
        issues: byTopic.length ? (
          <span className="flex flex-wrap gap-1">
            {byTopic.map(({ c, n }) => (
              <Link key={c.id} to={`/results?assessment=${latest.id}&category=${c.id}`} onClick={(e) => e.stopPropagation()}
                className="rounded-full border border-line px-2 py-0.5 hover:border-brand/40 hover:text-brand" style={{ borderLeftColor: CATEGORY_COLORS[c.id], borderLeftWidth: 3 }}>
                {c.shortName} {n}
              </Link>
            ))}
          </span>
        ) : null,
        critical: critical.length ? (
          <span className="block space-y-0.5">
            {critical.slice(0, 2).map((f) => (
              <Link key={f.id} to={problemLink(f)} onClick={(e) => e.stopPropagation()} className="block truncate text-ink hover:text-brand">• {f.name}</Link>
            ))}
            {critical.length > 2 && <span className="text-ink-subtle">+{critical.length - 2} more</span>}
          </span>
        ) : null,
      }
    : {};

  return (
    <div>
      <PageHeader
        title="Your CRM Health Overview"
        description="Your score, problems, and what to fix first."
        actions={
          <>
            <LinkButton to="/connection" icon={<Cloud className="h-4 w-4" />}>
              Connect Salesforce
            </LinkButton>
            <LinkButton to="/assessment" variant="primary" icon={<Play className="h-4 w-4" />}>
              Run a health check
            </LinkButton>
          </>
        }
      />

      {data.state === 'loading' ? (
        <div className="card p-8">
          <div className="flex items-center gap-8">
            <Skeleton className="h-40 w-40 rounded-full" />
            <div className="flex-1 space-y-3">
              <Skeleton className="h-6 w-1/2" />
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-4 w-1/3" />
            </div>
          </div>
        </div>
      ) : data.state === 'ready' && latest && results ? (
        <HealthHero assessment={latest} results={results} />
      ) : data.state === 'error' && (!!health.data || !(isApiError(data.error) && data.error.isUnavailable)) ? (
        <div className="card">
          <ErrorState error={data.error} onRetry={data.refetch} />
        </div>
      ) : (
        <GettingStarted hasRunningAssessment={running} />
      )}

      {data.state === 'ready' && latest && (
        <>
          {/* KPI tiles */}
          <div className="mb-3 mt-8">
            <h2 className="flex items-center gap-1.5 text-base font-semibold tracking-tight">
              Your latest results
              <InfoTip>Key numbers from your most recent health check. Use the i on each card to learn what it means.</InfoTip>
            </h2>
          </div>
          <StaggerGrid className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
            {metrics.map((m) => {
              const meta = KPI_META[m.key as keyof typeof KPI_META];
              return (
                <StaggerItem key={m.key}>
                  <HealthScoreCard
                    metric={m}
                    icon={meta.icon}
                    accent={meta.accent}
                    hint={meta.hint}
                    note={m.key === 'salesProcess' ? 'Workflows + Reporting average' : m.key === 'dataQuality' ? 'Data Quality & Optimization topic' : undefined}
                    footer={footers[m.key]}
                    lowerIsBetter={'lowerIsBetter' in meta}
                    spark={m.key === 'overall' ? overallSpark : undefined}
                    onClick={
                      m.key === 'critical'
                        ? () => navigate(`/results?assessment=${latest.id}&severity=critical`)
                        : m.key === 'issues'
                          ? () => navigate(`/results?assessment=${latest.id}`)
                          : undefined
                    }
                  />
                </StaggerItem>
              );
            })}
          </StaggerGrid>

          <div className="mt-8 grid gap-6 xl:grid-cols-2">
            <SectionCard
              title="Problems by urgency"
              description="What each level means, and the biggest problems in it"
              className="xl:row-span-2"
            >
              <FindingsBySeverityChart findings={findings} onSelect={(s) => navigate(`/results?assessment=${latest.id}&severity=${s}`)} />
              <UrgencyList findings={findings} worstFirst={worstFirst} assessmentId={latest.id} />
            </SectionCard>
            <SectionCard
              title="Which areas have the most problems?"
              description="Problems found in each topic"
            >
              <IssuesByCategoryChart findings={findings} />
            </SectionCard>
            <SectionCard
              title="Health score over time"
              description="How your score changes"
            >
              <ScoreTrendChart assessments={history} />
            </SectionCard>
          </div>
        </>
      )}

      {/* Category breakdown */}
      <div className="mb-4 mt-10 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-1.5 text-lg font-semibold tracking-tight">
            What was checked?
            <InfoTip>6 topics, 21 areas. Click a topic to see its areas.</InfoTip>
          </h2>
        </div>
        <LinkButton to="/assessment" size="sm" variant="ghost" iconRight={<ArrowRight className="h-3.5 w-3.5" />}>
          See all topics
        </LinkButton>
      </div>
      <StaggerGrid className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {CATEGORIES.map((c) => (
          <StaggerItem key={c.id}>
            <CategoryCard category={c} results={results} findings={findings} />
          </StaggerItem>
        ))}
      </StaggerGrid>

      <div className="mt-10 grid gap-6 xl:grid-cols-[1fr,320px]">
        <SectionCard
          title="Recent health checks"
          bodyClassName="p-0"
          actions={
            <LinkButton to="/history" size="sm" variant="ghost" iconRight={<ArrowRight className="h-3.5 w-3.5" />}>
              Full history
            </LinkButton>
          }
        >
          {all.isLoading ? (
            <LoadingState rows={5} />
          ) : all.error ? (
            <ErrorState error={all.error} onRetry={() => all.refetch()} />
          ) : !all.data?.length ? (
            <EmptyState
              title="No health checks run yet"
              description="Your checks will show here."
              action={
                <LinkButton to="/assessment" size="sm" variant="primary">
                  Run your first check
                </LinkButton>
              }
            />
          ) : (
            <AssessmentTable rows={all.data.slice(0, 5)} variant="recent" />
          )}
        </SectionCard>

        <SectionCard title="What would you like to do?">
          <div className="grid gap-2">
            <Button className="justify-start" icon={<Cloud className="h-4 w-4 text-brand" />} onClick={() => navigate('/connection')}>
              Connect my Salesforce
            </Button>
            <Button className="justify-start" icon={<LayoutGrid className="h-4 w-4 text-accent" />} onClick={() => navigate('/assessment')}>
              Browse check areas
            </Button>
            <Button
              className="justify-start"
              icon={<ListChecks className="h-4 w-4 text-sev-low" />}
              onClick={() => navigate(latest ? `/results?assessment=${latest.id}` : '/results')}
            >
              See my latest results
            </Button>
            <Button className="justify-start" icon={<FileBarChart className="h-4 w-4 text-warn" />} onClick={() => navigate('/reports')}>
              Download a report
            </Button>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
