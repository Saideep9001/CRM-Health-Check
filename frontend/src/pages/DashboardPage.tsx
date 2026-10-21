import { ArrowRight, Cloud, Database, FileBarChart, Gauge, LayoutGrid, ListChecks, OctagonAlert, Play, TriangleAlert, Workflow } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { isApiError } from '@/api/client';
import { useApiHealth, useAssessments } from '@/api/queries';
import { AssessmentTable } from '@/components/assessments/AssessmentTable';
import { CategoryHealthChart, FindingsBySeverityChart, IssuesByCategoryChart, ScoreTrendChart } from '@/components/charts/Charts';
import { CategoryCard } from '@/components/dashboard/CategoryCard';
import { GettingStarted } from '@/components/dashboard/GettingStarted';
import { HealthHero } from '@/components/dashboard/HealthHero';
import { HealthScoreCard } from '@/components/dashboard/HealthScoreCard';
import { InfoTip } from '@/components/ui/HelpTip';
import { Button, LinkButton } from '@/components/ui/Button';
import { PageHeader, SectionCard, StaggerGrid, StaggerItem } from '@/components/ui/Page';
import { EmptyState, ErrorState, LoadingState, Skeleton } from '@/components/ui/States';
import { CATEGORIES } from '@/config/categories';
import { useLatestAssessment } from '@/hooks/useLatestAssessment';
import { countBySeverity, delta, pctChange } from '@/lib/health';
import type { HealthMetric } from '@/types';

const KPI_META = {
  overall: {
    icon: Gauge,
    accent: '#3b82f6',
    hint: 'Your overall score. 80+ is healthy.',
  },
  dataQuality: {
    icon: Database,
    accent: '#14b8a6',
    hint: 'How clean and complete your data is.',
  },
  salesProcess: {
    icon: Workflow,
    accent: '#8b5cf6',
    hint: 'How well your sales process is set up.',
  },
  records: {
    icon: LayoutGrid,
    accent: '#06b6d4',
    hint: 'How many records we looked at.',
  },
  issues: {
    icon: TriangleAlert,
    accent: '#f59e0b',
    lowerIsBetter: true,
    hint: 'All problems found. Click to see them.',
  },
  critical: {
    icon: OctagonAlert,
    accent: '#ef4444',
    lowerIsBetter: true,
    hint: 'The most serious problems. Fix these first.',
  },
} as const;

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
          label: 'Urgent Issues',
          unit: 'count',
          value: countBySeverity(findings).critical,
          trend: null,
        },
      ]
    : [];
  const overallSpark = [...history].reverse().map((a) => a.overallScore).filter((s): s is number => s !== null);

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
              title="Health by area"
              description="Score for each topic (0–100)"
            >
              <CategoryHealthChart results={results} />
            </SectionCard>
            <SectionCard
              title="Problems by urgency"
              description="How serious the problems are"
            >
              <FindingsBySeverityChart findings={findings} />
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
