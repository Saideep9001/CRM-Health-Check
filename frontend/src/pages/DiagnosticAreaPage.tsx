import { motion } from 'framer-motion';
import { ArrowLeft, ArrowRight, CalendarDays, CheckCircle2, Gauge, Hourglass, TriangleAlert } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { RunCheckPanel } from '@/components/assessment/RunCheckPanel';
import { FindingDetailsPanel } from '@/components/findings/FindingDetailsPanel';
import { FindingsTable } from '@/components/findings/FindingsTable';
import { Badge, ReleaseBadge } from '@/components/ui/Badges';
import { LinkButton } from '@/components/ui/Button';
import { CategoryTile } from '@/components/ui/CategoryIcon';
import { Notice } from '@/components/ui/Page';
import { InfoTip } from '@/components/ui/HelpTip';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States';
import { Tabs } from '@/components/ui/Tabs';
import { ProgressBar, ScoreRing } from '@/components/ui/Visuals';
import { CATEGORY_COLORS, DIAGNOSTIC_AREAS, getArea, getAreaRelease, getCategory } from '@/config/categories';
import { useLatestAssessment } from '@/hooks/useLatestAssessment';
import { fmtDate, fmtNumber } from '@/lib/format';
import { findingsForArea, getAreaResult } from '@/lib/health';
import type { IndicatorValue } from '@/types';
import NotFoundPage from './NotFoundPage';

type Tab = 'indicators' | 'findings' | 'recommendations';

/** Visual fill for an indicator: percentages map directly; counts show presence vs absence of issues. */
function indicatorFill(i: IndicatorValue): number {
  if (i.unit === '%') return i.direction === 'higher-better' ? i.value : 100 - i.value;
  return i.direction === 'lower-better' ? (i.value === 0 ? 100 : 25) : i.value > 0 ? 100 : 25;
}

export default function DiagnosticAreaPage() {
  const { categoryId = '', areaId = '' } = useParams();
  const area = getArea(areaId);
  const category = getCategory(categoryId);
  const { state, error, refetch, latest, results, findings } = useLatestAssessment();
  const [tab, setTab] = useState<Tab>('indicators');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (!area || !category || area.categoryId !== category.id) return <NotFoundPage />;

  const release = getAreaRelease(area);
  const result = getAreaResult(results, area.id);
  const assessed = result?.status === 'assessed';
  const areaFindings = findingsForArea(findings, area.id);
  const selected = areaFindings.find((f) => f.id === selectedId) ?? null;
  const color = CATEGORY_COLORS[category.id];
  const idx = DIAGNOSTIC_AREAS.findIndex((a) => a.id === area.id);
  const prev = DIAGNOSTIC_AREAS[idx - 1];
  const next = DIAGNOSTIC_AREAS[idx + 1];

  return (
    <div>
      <Link to={`/assessment/${category.id}`} className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink">
        <ArrowLeft className="h-4 w-4" /> Back to {category.name}
      </Link>

      <section className="card relative mb-6 overflow-hidden">
        <span className="absolute inset-x-0 top-0 h-1" style={{ background: color }} />
        <div className="flex flex-col gap-6 p-6 lg:flex-row lg:items-center">
          <div className="flex min-w-0 flex-1 gap-4">
            <motion.span
              initial={{ rotate: -8, scale: 0.8 }}
              animate={{ rotate: 0, scale: 1 }}
              className="flex h-14 w-14 shrink-0 flex-col items-center justify-center rounded-xl text-white shadow"
              style={{ background: color }}
            >
              <span className="text-[10px] font-semibold uppercase opacity-80">Area</span>
              <span className="text-xl font-bold leading-none">{area.number}</span>
            </motion.span>
            <div className="min-w-0">
              <div className="mb-1.5 flex flex-wrap items-center gap-2">
                <Link to={`/assessment/${category.id}`} className="flex items-center gap-1.5 text-xs font-medium text-ink-muted hover:text-ink">
                  <CategoryTile id={category.id} size="sm" /> {category.name}
                </Link>
                <ReleaseBadge release={release} />
                {result && <Badge tone={assessed ? 'good' : result.status === 'failed' ? 'bad' : 'neutral'}>{assessed ? 'Assessed' : result.status === 'failed' ? 'Check failed' : 'Skipped'}</Badge>}
              </div>
              <h1 className="text-2xl font-semibold tracking-tight">
                {area.name}{' '}
                <InfoTip size="md" label="About this area">{area.description}</InfoTip>
              </h1>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-6">
            <div className="space-y-2 text-sm">
              <p className="flex items-center gap-2 text-ink-muted">
                <TriangleAlert className="h-4 w-4" /> {assessed ? `${areaFindings.length} problems found` : 'No problems yet'}
              </p>
              <p className="flex items-center gap-2 text-ink-muted">
                <CalendarDays className="h-4 w-4" /> {assessed && (result?.checkedAt ?? latest?.completedAt) ? `Last checked ${fmtDate((result?.checkedAt ?? latest?.completedAt)!)}` : 'Not checked yet'}
              </p>
              {assessed && result.recordsEvaluated !== null && <p className="text-xs text-ink-subtle">{fmtNumber(result.recordsEvaluated)} records evaluated</p>}
            </div>
            <ScoreRing score={assessed ? result.score : null} size={92} stroke={8} label={assessed ? 'Area score' : 'N/A'} />
          </div>
        </div>
      </section>

      {release === 'coming-soon' ? (
        <Notice tone="warn" icon={<Hourglass className="h-4 w-4" />} title="Coming Soon.">
          You can’t check this area yet. Here’s what it will measure.
        </Notice>
      ) : state === 'error' ? (
        <div className="card mb-6">
          <ErrorState error={error} onRetry={refetch} />
        </div>
      ) : state !== 'loading' ? (
        <>
          {result && result.status !== 'assessed' && (
            <Notice tone="warn" icon={<TriangleAlert className="h-4 w-4" />} title={result.status === 'failed' ? 'The last check for this area failed.' : 'This area was skipped last time.'}>
              {result.message ?? 'Try checking it again.'}
            </Notice>
          )}
          <RunCheckPanel
            areaIds={[area.id]}
            label="this area"
            checked={assessed}
            lastChecked={result?.checkedAt ?? latest?.completedAt}
            objectPicker={category.id === 'data-quality'}
          />
        </>
      ) : null}

      <div className="card">
        <div className="px-5 pt-2">
          <Tabs<Tab>
            layoutId="area-tabs"
            value={tab}
            onChange={setTab}
            tabs={[
              { id: 'indicators', label: 'What we measure', icon: <Gauge className="h-4 w-4" />, count: area.indicators.length },
              { id: 'findings', label: 'Problems found', icon: <TriangleAlert className="h-4 w-4" />, count: areaFindings.length },
              { id: 'recommendations', label: 'How to fix', icon: <CheckCircle2 className="h-4 w-4" /> },
            ]}
          />
        </div>

        <div className={tab === 'findings' && areaFindings.length ? '' : 'p-5'}>
          {state === 'loading' ? (
            <LoadingState rows={4} />
          ) : (
            <>
              {tab === 'indicators' && (
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {area.indicators.map((label, i) => {
                    const v = result?.indicators.find((x) => x.label === label);
                    return (
                      <motion.div key={label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }} className="rounded-xl border border-line p-4">
                        <p className="text-sm font-medium text-ink-muted">{label}</p>
                        {v ? (
                          <>
                            <p className="mt-2 text-2xl font-semibold tabular-nums">
                              {fmtNumber(v.value)}
                              {v.unit === '%' && <span className="text-base text-ink-subtle">%</span>}
                            </p>
                            <div className="mt-3">
                              <ProgressBar value={indicatorFill(v)} delay={i * 0.05} />
                            </div>
                            <p className="mt-2 text-[11px] text-ink-subtle">{v.direction === 'higher-better' ? 'Higher is better' : 'Lower is better'}</p>
                          </>
                        ) : (
                          <>
                            <p className="mt-2 text-2xl font-semibold text-ink-subtle">—</p>
                            <p className="mt-3 text-[11px] text-ink-subtle">{release === 'coming-soon' ? 'Coming Soon' : 'Not measured yet'}</p>
                          </>
                        )}
                      </motion.div>
                    );
                  })}
                </div>
              )}

              {tab === 'findings' &&
                (areaFindings.length ? (
                  <FindingsTable findings={areaFindings} onSelect={(f) => setSelectedId(f.id)} compact />
                ) : (
                  <EmptyState
                    title="No problems found here"
                    description={assessed ? 'Good news — no problems here.' : 'Problems will show here after a check.'}
                  />
                ))}

              {tab === 'recommendations' &&
                (areaFindings.length ? (
                  <ol className="space-y-3">
                    {[...areaFindings]
                      .sort((a, b) => a.priority.localeCompare(b.priority))
                      .map((f) => (
                        <li key={f.id} className="flex gap-3 rounded-lg border border-line p-4">
                          <span className="flex h-7 w-10 shrink-0 items-center justify-center rounded-md bg-brand-soft text-xs font-bold text-brand-ink">{f.priority}</span>
                          <div className="min-w-0">
                            <p className="text-sm font-medium">{f.recommendedAction}</p>
                            <button onClick={() => setSelectedId(f.id)} className="mt-0.5 text-xs text-brand hover:underline">
                              {f.id} · {f.name}
                            </button>
                          </div>
                        </li>
                      ))}
                  </ol>
                ) : (
                  <EmptyState title="No recommendations yet" description="Fixes show here when problems are found." />
                ))}
            </>
          )}
        </div>
      </div>

      <div className="mt-8 flex flex-wrap justify-between gap-2">
        {prev ? (
          <LinkButton to={`/assessment/${prev.categoryId}/${prev.id}`} icon={<ArrowLeft className="h-4 w-4" />}>
            Area {prev.number}
          </LinkButton>
        ) : (
          <span />
        )}
        {next && (
          <LinkButton to={`/assessment/${next.categoryId}/${next.id}`} iconRight={<ArrowRight className="h-4 w-4" />}>
            Area {next.number}
          </LinkButton>
        )}
      </div>

      <FindingDetailsPanel finding={selected} onClose={() => setSelectedId(null)} />
    </div>
  );
}
