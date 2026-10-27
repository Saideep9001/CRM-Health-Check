import { motion } from 'framer-motion';
import {
  ArrowLeft,
  ArrowRight,
  Archive,
  Award,
  Briefcase,
  CalendarDays,
  CheckCircle2,
  CircleOff,
  Clock,
  Columns3,
  Copy,
  Database,
  GitCompare,
  History,
  Link2,
  ListChecks,
  Network,
  PieChart,
  Gauge,
  Hourglass,
  SpellCheck,
  TriangleAlert,
  UserX,
  type LucideIcon,
} from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { RunCheckPanel } from '@/components/assessment/RunCheckPanel';
import { FindingsTable } from '@/components/findings/FindingsTable';
import { Badge, ReleaseBadge } from '@/components/ui/Badges';
import { LinkButton } from '@/components/ui/Button';
import { CategoryTile } from '@/components/ui/CategoryIcon';
import { Notice } from '@/components/ui/Page';
import { InfoTip } from '@/components/ui/HelpTip';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States';
import { Tabs } from '@/components/ui/Tabs';
import { AnimatedNumber, ProgressBar, ScoreRing } from '@/components/ui/Visuals';
import { CATEGORY_COLORS, DIAGNOSTIC_AREAS, getArea, getAreaRelease, getCategory } from '@/config/categories';
import { useAssessment } from '@/api/queries';
import { cardTone } from '@/components/category/DiagnosticAreaCard';
import { DEFAULT_DQ_OBJECTS } from '@/components/assessment/RunCheckPanel';
import { useLatestAssessment } from '@/hooks/useLatestAssessment';
import { cx, fmtDate, fmtNumber } from '@/lib/format';
import { findingsForArea, getAreaResult } from '@/lib/health';
import type { IndicatorValue } from '@/types';
import NotFoundPage from './NotFoundPage';

type Tab = 'indicators' | 'findings' | 'recommendations';

/** The object a measure is about and its title within that object: "Completeness (Leads)" → Leads / Completeness,
 *  "Duplicate Accounts" → Accounts / Duplicates. Null for measures that aren't about one object. */
function objectOf(label: string): { group: string; title: string } | null {
  let m = label.match(/^(.+) \(([^)]+)\)$/);
  if (m) return { group: m[2], title: m[1] };
  m = label.match(/^Duplicate (.+)$/);
  if (m) return { group: m[1], title: 'Duplicates' };
  m = label.match(/^(Accounts|Opportunities|Leads) (Without .+)$/) ?? label.match(/^Stale (Leads)$/);
  if (m) return { group: m[1], title: label };
  return null;
}

/** How a card looks for its score: healthy, needs a look, needs work, or shown for information only. */
const TONES = {
  good: { label: 'Healthy', chip: 'bg-good-soft text-good', bar: 'rgb(var(--good))' },
  warn: { label: 'Needs a look', chip: 'bg-warn-soft text-warn', bar: 'rgb(var(--warn))' },
  bad: { label: 'Needs work', chip: 'bg-bad-soft text-bad', bar: 'rgb(var(--bad))' },
  info: { label: 'For info', chip: 'bg-brand-soft text-brand', bar: 'rgb(var(--brand))' },
} as const;

function toneOf(v: IndicatorValue): keyof typeof TONES {
  if (v.score == null) return 'info';
  return cardTone(v.score);
}

function iconFor(title: string): LucideIcon {
  if (/^all fields/i.test(title)) return Columns3;
  if (/^unused/i.test(title)) return Archive;
  if (/^outdated/i.test(title)) return History;
  if (/look-alike/i.test(title)) return GitCompare;
  if (/low-completion/i.test(title)) return PieChart;
  if (/depend on/i.test(title)) return Link2;
  if (/scorecard/i.test(title)) return Award;
  if (/duplicate/i.test(title)) return Copy;
  if (/^completeness/i.test(title)) return ListChecks;
  if (/valid & consistent/i.test(title)) return SpellCheck;
  if (/^freshness/i.test(title)) return Clock;
  if (/^linked/i.test(title)) return Network;
  if (/^active owners/i.test(title)) return UserX;
  if (/missing/i.test(title)) return CircleOff;
  if (/standardi/i.test(title)) return SpellCheck;
  if (/activity/i.test(title)) return Clock;
  if (/contacts/i.test(title)) return UserX;
  if (/opportunit/i.test(title)) return Briefcase;
  return Gauge;
}

/** Bar fill: the share of records affected (counts out of the object's records), or the share itself for higher-better %. */
function shareOf(v: IndicatorValue, total: number | null): number {
  if (v.unit === '%') return v.value;
  if (total) return (100 * v.value) / total;
  return v.direction === 'lower-better' ? (v.value === 0 ? 0 : 25) : v.value > 0 ? 100 : 25;
}

export default function DiagnosticAreaPage() {
  const { categoryId = '', areaId = '' } = useParams();
  const area = getArea(areaId);
  const category = getCategory(categoryId);
  const { state, error, refetch, latest, results, findings } = useLatestAssessment();
  const [tab, setTab] = useState<Tab>('indicators');
  const source = useAssessment(getAreaResult(results, areaId)?.sourceAssessmentId ?? latest?.id ?? null);
  const navigate = useNavigate();

  if (!area || !category || area.categoryId !== category.id) return <NotFoundPage />;

  const release = getAreaRelease(area);
  const result = getAreaResult(results, area.id);
  const assessed = result?.status === 'assessed';
  const areaFindings = findingsForArea(findings, area.id);
  const color = CATEGORY_COLORS[category.id];
  const idx = DIAGNOSTIC_AREAS.findIndex((a) => a.id === area.id);
  const prev = DIAGNOSTIC_AREAS[idx - 1];
  const next = DIAGNOSTIC_AREAS[idx + 1];
  // After a check, show what it measured, in its order: checking just Accounts shows the Account measures (including a
  // "Missing …" card per key field), not Contacts or Leads.
  const measured = assessed && result?.indicators.length ? result.indicators.map((x) => x.label) : area.indicators;
  // The objects the check behind these results looked at.
  const checkedObjects = source.data ? (source.data.scope.objects?.length ? source.data.scope.objects : DEFAULT_DQ_OBJECTS) : null;

  // Cards grouped by the object they're about ("Completeness (Leads)" goes under Leads), in the check's order.
  const sections: { name: string; items: { label: string; i: number; title: string }[] }[] = [];
  measured.forEach((label, i) => {
    const o = objectOf(label);
    const name = o?.group ?? '';
    const last = sections[sections.length - 1];
    if (last && last.name === name) last.items.push({ label, i, title: o?.title ?? label });
    else sections.push({ name, items: [{ label, i, title: o?.title ?? label }] });
  });

  const objectOfGroup = (group: string) => results?.objects?.find((x) => x.label === group || x.label === `open ${group}`) ?? null;

  // First card of each object: how many of its records the check looked at.
  const allRecords = (group: string) => {
    if (area.id !== 'area-1') return null; // area 2 is about fields: its All Fields card comes first instead
    const o = objectOfGroup(group);
    if (!o || o.records == null) return null;
    return (
      <motion.button
        key="all-records"
        type="button"
        onClick={() => navigate(`/data/${encodeURIComponent(o.name)}`)}
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        whileHover={{ y: -4 }}
        className="group relative flex flex-col overflow-hidden rounded-2xl bg-brand p-5 text-left text-white shadow-pop"
        title={`Browse your ${group} in Your Data`}
      >
        <span className="pointer-events-none absolute -right-8 -top-10 h-36 w-36 rounded-full bg-white/10" />
        <span className="pointer-events-none absolute -bottom-12 right-10 h-28 w-28 rounded-full bg-white/5" />
        <span className="flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-white/15">
            <Database className="h-4 w-4" />
          </span>
          <span className="text-sm font-semibold">All Records</span>
        </span>
        <span className="mt-4 text-4xl font-bold tabular-nums tracking-tight">
          <AnimatedNumber value={o.records} />
        </span>
        <span className="mt-1 text-xs text-white/80">{o.name === 'Lead' ? 'Open (not converted) Leads' : group} the last check looked at</span>
        {o.problems > 0 && (
          <span className="mt-3 w-fit rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-semibold">
            {o.problems} {o.problems === 1 ? 'problem' : 'problems'} found
          </span>
        )}
        <span className="mt-auto inline-flex items-center gap-1 pt-4 text-xs font-semibold">
          Browse records <ArrowRight className="h-3.5 w-3.5 transition group-hover:translate-x-1" />
        </span>
      </motion.button>
    );
  };

  const card = (label: string, i: number, title: string, group = '') => {
    const v = result?.indicators.find((x) => x.label === label);
    const Icon = iconFor(title);
    if (!v) {
      return (
        <motion.div key={label} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }} className="rounded-2xl border border-dashed border-line p-5">
          <span className="flex items-center gap-2.5">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-muted text-ink-subtle">
              <Icon className="h-4 w-4" />
            </span>
            <span className="text-sm font-semibold text-ink-muted">{title}</span>
          </span>
          <p className="mt-4 text-3xl font-bold text-ink-subtle">—</p>
          <p className="mt-2 text-[11px] text-ink-subtle">{release === 'coming-soon' ? 'Coming Soon' : 'Not measured yet'}</p>
        </motion.div>
      );
    }
    const tone = TONES[toneOf(v)];
    // Out of what: what the card says it's out of (e.g. 225 custom fields), else the object's records.
    const total = v.outOf ?? (area.id === 'area-1' ? (objectOfGroup(group)?.records ?? null) : null);
    const ofWhat = v.outOfLabel ? ` ${v.outOfLabel}` : '';
    const share = shareOf(v, total);
    const decimals = !Number.isInteger(v.value);
    // The exact count when the check saved it ("What's counted: 9,926 of 9,978 …"), else worked out from the rounded %.
    const counted = (v.criteria ?? []).find(([k]) => k === "What's counted")?.[1]?.match(/^([\d,]+) of ([\d,]+)/);
    const exact = counted && total && Number(counted[2].replace(/,/g, '')) === total ? Number(counted[1].replace(/,/g, '')) : null;
    const sub =
      v.unit === '%'
        ? total
          ? exact != null
            ? `${fmtNumber(exact)} of ${fmtNumber(total)}${ofWhat}`
            : `≈ ${fmtNumber(Math.round((v.value * total) / 100))} of ${fmtNumber(total)}${ofWhat}`
          : ''
        : total
          ? `${Math.round(share * 10) / 10}% of ${fmtNumber(total)}${ofWhat}`
          : '';
    return (
      <motion.button
        key={label}
        type="button"
        onClick={() => navigate(`/measures/${area.id}?${new URLSearchParams({ label })}`)}
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: i * 0.04 }}
        whileHover={{ y: -4 }}
        className="group relative flex flex-col overflow-hidden rounded-2xl border border-line bg-surface p-5 text-left shadow-sm transition-shadow hover:border-brand/30 hover:shadow-pop"
        title={`See how this is measured, the scoring rule and the records${v.score != null ? ` · score ${Math.round(v.score)}/100` : ''}`}
      >
        <span className="absolute inset-x-0 top-0 h-1" style={{ background: tone.bar }} />
        <span className="flex items-start justify-between gap-2">
          <span className="flex min-w-0 items-center gap-2.5 pr-1">
            <span className={cx('grid h-9 w-9 shrink-0 place-items-center rounded-xl transition group-hover:scale-110', tone.chip)}>
              <Icon className="h-4 w-4" />
            </span>
            <span className="text-sm font-semibold leading-snug">{title}</span>
          </span>
          <span className={cx('shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide', tone.chip)}>{tone.label}</span>
        </span>
        <span className="mt-4 flex flex-wrap items-baseline gap-x-2">
          <span className="text-3xl font-bold tabular-nums tracking-tight">
            <AnimatedNumber value={v.value} decimals={decimals ? 1 : 0} />
            {v.unit === '%' && <span className="text-lg text-ink-subtle">%</span>}
          </span>
          {sub && <span className="text-xs text-ink-muted">{sub}</span>}
        </span>
        <span className="mt-3 block">
          {/^All Fields/.test(label) ? (
            <span className="block h-1.5" aria-hidden="true" />
          ) : (
            <ProgressBar value={v.direction === 'higher-better' ? share : Math.max(share, v.value > 0 ? 2 : 0)} color={tone.bar} delay={i * 0.04} />
          )}
        </span>
        {v.cause ? (
          <span className="mt-3 text-xs" title={v.how ?? undefined}>
            <span className="font-medium text-ink-subtle">Main cause · </span>
            <span className="font-medium text-ink">{v.cause}</span>
          </span>
        ) : (
          v.how && <span className="mt-3 line-clamp-2 text-xs text-ink-muted">{v.how}</span>
        )}
        <span className="mt-auto inline-flex items-center gap-1 pt-4 text-xs font-semibold text-brand">
          Rule &amp; {v.fieldList ? 'fields' : 'records'} <ArrowRight className="h-3.5 w-3.5 transition group-hover:translate-x-1" />
        </span>
      </motion.button>
    );
  };

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
          <div id="run-check" className="scroll-mt-24" />
          <RunCheckPanel
            areaIds={[area.id]}
            label="this area"
            checked={assessed}
            lastChecked={result?.checkedAt ?? latest?.completedAt}
            objectPicker={category.id === 'data-quality'}
            lastObjects={checkedObjects}
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
              { id: 'indicators', label: 'What we measure', icon: <Gauge className="h-4 w-4" />, count: measured.length },
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
                <div className="space-y-5">
                  {sections.map((sec, si) =>
                    sec.name ? (
                      <section key={sec.name} className="rounded-xl border border-line bg-muted/30 p-4">
                        <h3 className="mb-4 flex items-center gap-2 text-base font-semibold">
                          <span className="h-2.5 w-2.5 rounded-full bg-brand" />
                          {sec.name}
                        </h3>
                        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                          {allRecords(sec.name)}
                          {sec.items.map((it) => card(it.label, it.i, it.title, sec.name))}
                        </div>
                      </section>
                    ) : (
                      <div key={`plain-${si}`} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                        {sec.items.map((it) => card(it.label, it.i, it.title))}
                      </div>
                    ),
                  )}
                </div>
              )}

              {tab === 'findings' &&
                (areaFindings.length ? (
                  <FindingsTable findings={areaFindings} onSelect={(f) => navigate(`/problems/${encodeURIComponent(f.id)}`)} compact />
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
                            <button onClick={() => navigate(`/problems/${encodeURIComponent(f.id)}`)} className="mt-0.5 text-xs text-brand hover:underline">
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
    </div>
  );
}
