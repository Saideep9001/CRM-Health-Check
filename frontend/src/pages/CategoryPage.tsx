import { AnimatePresence } from 'framer-motion';
import { ArrowLeft, Hourglass, SearchX } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { RunCheckPanel } from '@/components/assessment/RunCheckPanel';
import { DiagnosticAreaCard, type ObjectChip } from '@/components/category/DiagnosticAreaCard';
import { measureFor } from '@/components/findings/DetailsPanel';
import { SEVERITY_RANK } from '@/lib/health';
import { TopicHero } from '@/components/category/TopicHero';
import { Button, LinkButton } from '@/components/ui/Button';
import { SearchInput, Select } from '@/components/ui/Form';
import { Notice } from '@/components/ui/Page';
import { EmptyState, ErrorState } from '@/components/ui/States';
import { CATEGORY_COLORS, getAreasForCategory, getCategory } from '@/config/categories';
import { useLatestAssessment } from '@/hooks/useLatestAssessment';
import { findingsForArea, findingsForCategory, getAreaResult, getCategoryCoverage, getCategoryScore } from '@/lib/health';
import { cx } from '@/lib/format';
import NotFoundPage from './NotFoundPage';

type AssessedFilter = 'all' | 'assessed' | 'not-assessed';
type FindingFilter = 'all' | 'with' | 'without';

export default function CategoryPage() {
  const { categoryId = '' } = useParams();
  const category = getCategory(categoryId);
  const { state, error, refetch, latest, results, findings } = useLatestAssessment();
  const [q, setQ] = useState('');
  const [assessedFilter, setAssessedFilter] = useState<AssessedFilter>('all');
  const [findingFilter, setFindingFilter] = useState<FindingFilter>('all');
  // A problem opened from a card's "Fix first" list, shown in a side panel on this page.
  const navigate = useNavigate();
  const openProblem = (id: string) => navigate(`/problems/${encodeURIComponent(id)}`);
  const openMeasure = (areaId: string, label: string, object?: string) =>
    navigate(`/measures/${areaId}?${new URLSearchParams({ label, ...(object ? { object } : {}) })}`);

  // A "By object" chip: its measure with that object first, else that object's most urgent problem.
  const openObject = (areaId: string, chip: ObjectChip) => {
    const indicators = getAreaResult(results, areaId)?.indicators ?? [];
    const own = findingsForArea(findings, areaId)
      .filter((f) => f.objectName === chip.name && f.status !== 'resolved' && f.status !== 'accepted-risk')
      .sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || b.affectedRecords - a.affectedRecords);
    const label = (chip.measure && indicators.some((i) => i.label === chip.measure) ? chip.measure : null) ?? (own[0] ? measureFor(own[0], indicators)?.label : null);
    if (label) openMeasure(areaId, label, chip.name);
    else if (own[0]) openProblem(own[0].id);
  };

  const areas = useMemo(() => (category ? getAreasForCategory(category.id) : []), [category]);
  if (!category) return <NotFoundPage />;

  const term = q.trim().toLowerCase();
  const filtered = areas.filter((a) => {
    const n = findingsForArea(findings, a.id).length;
    const done = getAreaResult(results, a.id)?.status === 'assessed';
    return (
      (!term ||
        a.name.toLowerCase().includes(term) ||
        a.description.toLowerCase().includes(term) ||
        a.indicators.some((i) => i.toLowerCase().includes(term)) ||
        String(a.number) === term) &&
      (assessedFilter === 'all' || (assessedFilter === 'assessed' ? done : !done)) &&
      (findingFilter === 'all' || (findingFilter === 'with' ? n > 0 : n === 0))
    );
  });

  const color = CATEGORY_COLORS[category.id];
  const score = getCategoryScore(results, category.id);
  const coverage = getCategoryCoverage(results, category.id);
  const catFindings = findingsForCategory(findings, category.id);
  const soon = category.release === 'coming-soon';
  const lastAssessed = latest?.completedAt ?? null;
  const topicAreaResults = (results?.areas ?? []).filter((r) => category.areaIds.includes(r.areaId) && r.status === 'assessed');
  // Most recent check of any area in this topic (areas can come from different checks).
  const lastChecked = topicAreaResults.map((r) => r.checkedAt ?? lastAssessed).filter(Boolean).sort().at(-1) ?? lastAssessed;
  const objectRecords = results?.objects?.reduce((n, o) => n + (o.records ?? 0), 0) ?? 0;
  const recordsChecked = category.id === 'data-quality' && objectRecords ? objectRecords : (latest?.recordsAssessed ?? null);

  return (
    <div>
      <Link to="/dashboard" className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink">
        <ArrowLeft className="h-4 w-4" /> Back to overview
      </Link>

      <TopicHero
        category={category}
        color={color}
        score={score}
        coverage={coverage}
        areas={areas.length}
        problems={coverage === 'not-assessed' ? null : catFindings.length}
        critical={coverage === 'not-assessed' ? null : catFindings.filter((f) => f.severity === 'critical').length}
        records={coverage === 'not-assessed' ? null : recordsChecked}
        lastChecked={coverage === 'not-assessed' ? null : lastChecked}
      />

      {soon ? (
        <Notice tone="warn" icon={<Hourglass className="h-4 w-4" />} title="Coming Soon.">
          You can’t check this topic yet. Here’s what it will cover.
        </Notice>
      ) : state === 'error' ? (
        <div className="card mb-6">
          <ErrorState error={error} onRetry={refetch} />
        </div>
      ) : state !== 'loading' ? (
        <RunCheckPanel
          areaIds={category.areaIds}
          label="this topic"
          checked={coverage !== 'not-assessed'}
          lastChecked={lastAssessed}
          objectPicker={category.id === 'data-quality'}
        />
      ) : null}

      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <h2 className="shrink-0 whitespace-nowrap text-lg font-semibold tracking-tight">
          Areas in this topic <span className="text-ink-subtle">({filtered.length} of {areas.length})</span>
        </h2>
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:flex-wrap lg:justify-end">
          <SearchInput value={q} onChange={setQ} placeholder="Search areas…" className="sm:w-64" />
          <Select<AssessedFilter>
            label="Filter by status"
            value={assessedFilter}
            onChange={setAssessedFilter}
            className="sm:w-44"
            options={[
              { value: 'all', label: 'All areas' },
              { value: 'assessed', label: 'Checked' },
              { value: 'not-assessed', label: 'Not checked yet' },
            ]}
          />
          <Select<FindingFilter>
            label="Filter by problems"
            value={findingFilter}
            onChange={setFindingFilter}
            className="sm:w-44"
            options={[
              { value: 'all', label: 'With or without problems' },
              { value: 'with', label: 'Has problems' },
              { value: 'without', label: 'No problems' },
            ]}
          />
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="card">
          <EmptyState
            icon={<SearchX className="h-6 w-6" />}
            title="No areas match"
            description="Try another search."
            action={
              <Button
                size="sm"
                onClick={() => {
                  setQ('');
                  setAssessedFilter('all');
                  setFindingFilter('all');
                }}
              >
                Clear filters
              </Button>
            }
          />
        </div>
      ) : (
        <div className={cx('grid gap-4 md:grid-cols-2', areas.length > 2 && 'xl:grid-cols-3')}>
          <AnimatePresence>
            {filtered.map((a) => (
              <DiagnosticAreaCard
                key={a.id}
                area={a}
                color={color}
                result={getAreaResult(results, a.id)}
                findingsCount={findingsForArea(findings, a.id).length}
                lastAssessed={lastAssessed}
                findings={findingsForArea(findings, a.id)}
                objects={results?.objects ?? []}
                assessmentId={latest?.id}
                onSelectFinding={(f) => openProblem(f.id)}
                onSelectObject={(o) => openObject(a.id, o)}
                onSelectMeasure={(label) => openMeasure(a.id, label)}
              />
            ))}
          </AnimatePresence>
        </div>
      )}

      <div className="mt-8 flex flex-wrap justify-between gap-2">
        <LinkButton to="/assessment" icon={<ArrowLeft className="h-4 w-4" />}>
          All topics
        </LinkButton>
        {latest && catFindings.length > 0 && (
          <LinkButton to={`/results?assessment=${latest.id}&category=${category.id}`} variant="subtle">
            View {catFindings.length} problems
          </LinkButton>
        )}
      </div>
    </div>
  );
}
