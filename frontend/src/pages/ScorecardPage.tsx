import { motion } from 'framer-motion';
import { Award, Download, Lightbulb, Printer, TrendingDown, TrendingUp } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Cell, LabelList, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useNavigate } from 'react-router-dom';
import { ChartTooltip, SEVERITY_COLORS } from '@/components/charts/Charts';
import { Button } from '@/components/ui/Button';
import { PageHeader, SectionCard } from '@/components/ui/Page';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States';
import { AnimatedNumber } from '@/components/ui/Visuals';
import { useLatestAssessment } from '@/hooks/useLatestAssessment';
import { cx, fmtDate } from '@/lib/format';
import { countBySeverity, getAreaResult, SEVERITIES } from '@/lib/health';
import type { IndicatorValue } from '@/types';

/** The objects graded, in this order. */
const OBJECTS = [
  { name: 'Account', plural: 'Accounts' },
  { name: 'Lead', plural: 'Leads' },
  { name: 'Contact', plural: 'Contacts' },
  { name: 'Opportunity', plural: 'Opportunities' },
] as const;

const grade = (s: number) => (s >= 90 ? 'A' : s >= 80 ? 'B' : s >= 70 ? 'C' : s >= 60 ? 'D' : 'F');
/** Status colour of a grade: A/B good, C/D needs a look, F needs work. */
const gradeTone = (g: string) => (g === 'A' || g === 'B' ? 'good' : g === 'F' ? 'bad' : 'warn');
const TONE_FILL = { good: 'rgb(var(--good))', warn: 'rgb(var(--warn))', bad: 'rgb(var(--bad))' } as const;
const TONE_CLASS = { good: 'bg-good-soft text-good ring-good/30', warn: 'bg-warn-soft text-warn ring-warn/30', bad: 'bg-bad-soft text-bad ring-bad/30' } as const;
const AREA_COLORS = { a1: 'rgb(var(--brand))', a2: 'rgb(var(--accent))' };

/** The object a scored card is about ("Missing Key Fields (Leads)", "Duplicate Leads", "Stale Leads", "Accounts Without Contacts"). */
function objectOf(label: string): string | null {
  for (const o of OBJECTS) {
    if (label.endsWith(`(${o.plural})`) || label === `Duplicate ${o.plural}` || label === `Stale ${o.plural}` || label.startsWith(`${o.plural} Without`)) return o.name;
  }
  return null;
}
/** The card's name without its object: "Missing Key Fields (Leads)" → "Missing Key Fields", "Duplicate Leads" → "Duplicates". */
function cardName(label: string): string {
  return label
    .replace(/ \([^)]+\)$/, '')
    .replace(/^Duplicate \w+$/, 'Duplicates')
    .replace(/^(Accounts|Opportunities|Leads) (Without .+)$/, '$2');
}

type Card = { label: string; card: string; score: number; area: 'area-1' | 'area-2' };
type Row = { name: string; plural: string; cards: Card[]; a1: number | null; a2: number | null; score: number; grade: string };

const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
/** Object score = (average of its Area 1 cards + average of its Area 2 cards) ÷ 2 (one area if only one has cards). */
function scoreOf(cards: Card[]): { a1: number | null; a2: number | null; score: number } {
  const a1 = avg(cards.filter((c) => c.area === 'area-1').map((c) => c.score));
  const a2 = avg(cards.filter((c) => c.area === 'area-2').map((c) => c.score));
  const halves = [a1, a2].filter((x): x is number => x != null);
  return { a1, a2, score: halves.reduce((a, b) => a + b, 0) / halves.length };
}

/** Data Quality Scorecard: an A–F grade per object and overall, from the latest Area 1 and Area 2 results. */
export default function ScorecardPage() {
  const navigate = useNavigate();
  const { state, error, refetch, results, findings, latest } = useLatestAssessment();
  if (state === 'loading') return <LoadingState rows={6} label="Loading the scorecard…" />;
  if (state === 'error') return <ErrorState error={error} onRetry={refetch} />;

  const areas = (['area-1', 'area-2'] as const).map((id) => ({ id, r: getAreaResult(results, id) }));
  const cards: (Card & { object: string })[] = areas.flatMap(({ id, r }) =>
    (r?.indicators ?? []).flatMap((v: IndicatorValue) => {
      const object = v.score != null ? objectOf(v.label) : null;
      return object ? [{ label: v.label, card: cardName(v.label), score: v.score!, area: id, object }] : [];
    }),
  );
  const rows: Row[] = OBJECTS.flatMap((o) => {
    const mine = cards.filter((c) => c.object === o.name);
    if (!mine.length) return [];
    const s = scoreOf(mine);
    return [{ name: o.name, plural: o.plural, cards: mine, ...s, grade: grade(s.score) }];
  });
  if (!rows.length) {
    return (
      <>
        <PageHeader eyebrow="Data Quality & Optimization" title="Data Quality Scorecard" />
        <EmptyState className="py-16" icon={<Award className="h-5 w-5" />} title="No grades yet"
          description="Run a health check of Area 1 (Record Data Quality) and Area 2 (Redundant Fields) to grade Accounts, Leads, Contacts and Opportunities." />
      </>
    );
  }
  const overall = rows.reduce((a, r) => a + r.score, 0) / rows.length;
  const checkedAt = [getAreaResult(results, 'area-1')?.checkedAt, getAreaResult(results, 'area-2')?.checkedAt].filter(Boolean) as string[];

  // Problems per object and urgency (Areas 1 and 2)
  const problems = rows.map((r) => ({
    name: r.plural,
    ...countBySeverity(findings.filter((f) => (f.areaId === 'area-1' || f.areaId === 'area-2') && f.objectName === r.name && f.status !== 'resolved')),
  }));

  // Analysis, worked out from the numbers: what drags each object down and what would lift the overall grade most.
  const ranked = [...rows].sort((a, b) => a.score - b.score);
  const lifts = rows
    .flatMap((r) =>
      r.cards
        .filter((c) => c.score < 80)
        .map((c) => {
          const lifted = scoreOf(r.cards.map((x) => (x === c ? { ...x, score: 80 } : x))).score;
          const newOverall = overall + (lifted - r.score) / rows.length;
          return { r, c, lifted, gain: newOverall - overall };
        }),
    )
    .sort((a, b) => b.gain - a.gain)
    .slice(0, 3);
  const gapRows = rows.filter((r) => r.a1 != null && r.a2 != null && Math.abs(r.a1 - r.a2) >= 15);
  const allCardNames = [...new Set(cards.map((c) => c.card))];

  const downloadCsv = () => {
    const head = ['Object', 'Grade', 'Score', 'Area 1 average', 'Area 2 average', ...allCardNames];
    const lines = [
      head,
      ...rows.map((r) => [r.plural, r.grade, r.score.toFixed(0), r.a1?.toFixed(0) ?? '', r.a2?.toFixed(0) ?? '',
        ...allCardNames.map((n) => r.cards.find((c) => c.card === n)?.score.toFixed(0) ?? '')]),
      ['Overall', grade(overall), overall.toFixed(0)],
    ];
    const csv = lines.map((l) => l.map((x) => `"${String(x).replace(/"/g, '""')}"`).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    Object.assign(document.createElement('a'), { href: url, download: 'data-quality-scorecard.csv' }).click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Data Quality & Optimization"
        title="Data Quality Scorecard"
        description={`A grade for each object and for the organization, from the latest Area 1 and Area 2 results${checkedAt.length ? ` (checked ${[...new Set(checkedAt.map(fmtDate))].join(' and ')})` : ''}.`}
        actions={
          <div className="flex gap-2 print:hidden">
            <Button size="sm" icon={<Download className="h-4 w-4" />} onClick={downloadCsv}>Download CSV</Button>
            <Button size="sm" variant="ghost" icon={<Printer className="h-4 w-4" />} onClick={() => window.print()}>Print / Save as PDF</Button>
          </div>
        }
      />

      {/* Grades */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="relative overflow-hidden rounded-2xl bg-brand p-5 text-white shadow-pop lg:row-span-1">
          <span className="text-sm font-semibold text-white/85">Overall Data Quality</span>
          <span className="mt-3 flex items-end gap-3">
            <span className="text-5xl font-bold">{grade(overall)}</span>
            <span className="pb-1 text-lg tabular-nums text-white/85"><AnimatedNumber value={Math.round(overall)} />/100</span>
          </span>
          <span className="mt-2 block text-xs text-white/75">The average of the {rows.length} objects</span>
        </motion.div>
        {rows.map((r, i) => {
          const t = gradeTone(r.grade);
          return (
            <motion.div key={r.name} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * (i + 1) }}
              className="rounded-2xl border border-line bg-surface p-5 shadow-sm">
              <span className="text-sm font-semibold text-ink-muted">{r.name}</span>
              <span className="mt-3 flex items-center gap-3">
                <span className={cx('grid h-12 w-12 place-items-center rounded-xl text-2xl font-bold ring-1', TONE_CLASS[t])}>{r.grade}</span>
                <span className="text-lg font-semibold tabular-nums text-ink"><AnimatedNumber value={Math.round(r.score)} /><span className="text-sm text-ink-subtle">/100</span></span>
              </span>
              <span className="mt-2 block text-[11px] text-ink-muted">
                Area 1: {r.a1 == null ? '—' : Math.round(r.a1)} · Area 2: {r.a2 == null ? '—' : Math.round(r.a2)} · {r.cards.length} cards
              </span>
            </motion.div>
          );
        })}
      </div>

      {/* Charts */}
      <div className="grid gap-6 lg:grid-cols-2">
        <SectionCard title="Score by object" description="Out of 100, coloured by grade: A–B healthy, C–D needs a look, F needs work.">
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={rows.map((r) => ({ name: r.plural, score: Math.round(r.score), grade: r.grade }))} layout="vertical" margin={{ left: 8, right: 40, top: 4, bottom: 4 }} barCategoryGap={14}>
                <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="rgb(var(--line))" />
                <XAxis type="number" domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fill: 'rgb(var(--ink-subtle))', fontSize: 11 }} />
                <YAxis type="category" dataKey="name" width={96} tickLine={false} axisLine={false} tick={{ fill: 'rgb(var(--ink-muted))', fontSize: 12 }} />
                <Tooltip cursor={{ fill: 'rgb(var(--muted))' }} content={<ChartTooltip unit="/100" />} />
                <Bar dataKey="score" name="Score" radius={[0, 4, 4, 0]} animationDuration={900}>
                  {rows.map((r) => <Cell key={r.name} fill={TONE_FILL[gradeTone(r.grade)]} />)}
                  <LabelList dataKey="grade" position="right" style={{ fill: 'rgb(var(--ink))', fontSize: 12, fontWeight: 700 }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>

        <SectionCard title="Area 1 vs Area 2" description="Area 1: the data in the records. Area 2: the fields. Each counts for half of an object’s score.">
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={rows.map((r) => ({ name: r.plural, a1: r.a1 == null ? null : Math.round(r.a1), a2: r.a2 == null ? null : Math.round(r.a2) }))} margin={{ left: -12, right: 8, top: 16, bottom: 4 }} barGap={2} barCategoryGap={22}>
                <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="rgb(var(--line))" />
                <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fill: 'rgb(var(--ink-muted))', fontSize: 12 }} />
                <YAxis domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fill: 'rgb(var(--ink-subtle))', fontSize: 11 }} />
                <Tooltip cursor={{ fill: 'rgb(var(--muted))' }} content={<ChartTooltip unit="/100" />} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="a1" name="Area 1 · records" fill={AREA_COLORS.a1} radius={[4, 4, 0, 0]} animationDuration={900}>
                  <LabelList dataKey="a1" position="top" style={{ fill: 'rgb(var(--ink-muted))', fontSize: 11 }} />
                </Bar>
                <Bar dataKey="a2" name="Area 2 · fields" fill={AREA_COLORS.a2} radius={[4, 4, 0, 0]} animationDuration={900}>
                  <LabelList dataKey="a2" position="top" style={{ fill: 'rgb(var(--ink-muted))', fontSize: 11 }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>

        <SectionCard title="Open problems by object" description="Problems raised by Areas 1 and 2, by urgency.">
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={problems} margin={{ left: -12, right: 8, top: 8, bottom: 4 }} barCategoryGap={26}>
                <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="rgb(var(--line))" />
                <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fill: 'rgb(var(--ink-muted))', fontSize: 12 }} />
                <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: 'rgb(var(--ink-subtle))', fontSize: 11 }} />
                <Tooltip cursor={{ fill: 'rgb(var(--muted))' }} content={<ChartTooltip />} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} formatter={(v: string) => v.charAt(0).toUpperCase() + v.slice(1)} />
                {SEVERITIES.map((s, i) => (
                  <Bar key={s} dataKey={s} name={s} stackId="p" fill={SEVERITY_COLORS[s]} stroke="rgb(var(--surface))" strokeWidth={2}
                    radius={i === SEVERITIES.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]} animationDuration={900} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>
        <SectionCard title="Cards by grade" description="How many of the scored cards get each grade, across all objects.">
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={['A', 'B', 'C', 'D', 'F'].map((g) => ({ name: g, cards: cards.filter((c) => grade(c.score) === g).length }))} margin={{ left: -12, right: 8, top: 16, bottom: 4 }} barCategoryGap={18}>
                <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="rgb(var(--line))" />
                <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fill: 'rgb(var(--ink-muted))', fontSize: 12, fontWeight: 600 }} />
                <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: 'rgb(var(--ink-subtle))', fontSize: 11 }} />
                <Tooltip cursor={{ fill: 'rgb(var(--muted))' }} content={<ChartTooltip unit=" cards" />} />
                <Bar dataKey="cards" name="Cards" radius={[4, 4, 0, 0]} animationDuration={900}>
                  {['A', 'B', 'C', 'D', 'F'].map((g) => <Cell key={g} fill={TONE_FILL[gradeTone(g)]} />)}
                  <LabelList dataKey="cards" position="top" style={{ fill: 'rgb(var(--ink-muted))', fontSize: 11 }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>

        <SectionCard className="lg:col-span-2" title="Every card’s score" description="Each object’s cards out of 100 (— = not a card for that object). Click a score to open the card.">
          <div className="scrollbar-thin overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-xs">
              <thead className="text-[11px] uppercase tracking-wide text-ink-subtle">
                <tr>
                  <th className="px-2 py-2">Card</th>
                  {rows.map((r) => <th key={r.name} className="px-2 py-2 text-center">{r.plural}</th>)}
                </tr>
              </thead>
              <tbody>
                {allCardNames.map((n) => (
                  <tr key={n} className="border-t border-line">
                    <td className="px-2 py-1.5 text-ink-muted">{n}</td>
                    {rows.map((r) => {
                      const c = r.cards.find((x) => x.card === n);
                      if (!c) return <td key={r.name} className="px-2 py-1.5 text-center text-ink-subtle">—</td>;
                      const t = gradeTone(grade(c.score));
                      return (
                        <td key={r.name} className="px-1 py-1">
                          <button type="button" title={`${c.label}: ${Math.round(c.score)}/100 (grade ${grade(c.score)})`}
                            onClick={() => navigate(`/measures/${c.area}?label=${encodeURIComponent(c.label)}&object=${r.name}`)}
                            className={cx('w-full rounded-md py-1.5 text-center font-semibold tabular-nums ring-1 transition hover:brightness-95', TONE_CLASS[t])}>
                            {Math.round(c.score)}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>
      </div>

      {/* Analysis */}
      <SectionCard title="Analysis" description="Worked out from the scores above.">
        <div className="grid gap-5 lg:grid-cols-2">
          <ul className="space-y-3 text-sm">
            <li className="flex gap-2">
              <Award className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
              <span>
                Overall the organization grades <b>{grade(overall)}</b> ({Math.round(overall)}/100) across {rows.length} objects and {cards.length} scored cards.
              </span>
            </li>
            <li className="flex gap-2">
              <TrendingDown className="mt-0.5 h-4 w-4 shrink-0 text-bad" />
              <span>
                Weakest: <b>{ranked[0].plural}</b> ({ranked[0].grade}, {Math.round(ranked[0].score)}), held down most by{' '}
                {[...ranked[0].cards].sort((a, b) => a.score - b.score).slice(0, 2).map((c) => `${c.card} (${Math.round(c.score)})`).join(' and ')}.
              </span>
            </li>
            {ranked.length > 1 && (
              <li className="flex gap-2">
                <TrendingUp className="mt-0.5 h-4 w-4 shrink-0 text-good" />
                <span>
                  Strongest: <b>{ranked[ranked.length - 1].plural}</b> ({ranked[ranked.length - 1].grade}, {Math.round(ranked[ranked.length - 1].score)}), best on{' '}
                  {[...ranked[ranked.length - 1].cards].sort((a, b) => b.score - a.score).slice(0, 2).map((c) => `${c.card} (${Math.round(c.score)})`).join(' and ')}.
                </span>
              </li>
            )}
            {gapRows.map((r) => (
              <li key={r.name} className="flex gap-2">
                <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
                <span>
                  {r.plural}: {r.a1! > r.a2!
                    ? `the records (Area 1, ${Math.round(r.a1!)}) are in better shape than the fields (Area 2, ${Math.round(r.a2!)}) — tidying unused and rarely filled fields lifts it most.`
                    : `the fields (Area 2, ${Math.round(r.a2!)}) are in better shape than the data in the records (Area 1, ${Math.round(r.a1!)}) — duplicates, missing and invalid values are the work.`}
                </span>
              </li>
            ))}
          </ul>
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-subtle">What would lift the overall grade most</p>
            {lifts.length ? (
              <ol className="space-y-2">
                {lifts.map(({ r, c, lifted, gain }, i) => (
                  <li key={c.label}>
                    <button type="button" onClick={() => navigate(`/measures/${c.area}?label=${encodeURIComponent(c.label)}&object=${r.name}`)}
                      className="flex w-full items-start gap-3 rounded-xl border border-line p-3 text-left text-sm transition hover:border-brand/40 hover:bg-muted/40">
                      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand-soft text-xs font-bold text-brand-ink">{i + 1}</span>
                      <span>
                        <b>{r.plural}: {c.card}</b> is at {Math.round(c.score)}. Bringing it to 80 lifts {r.plural} from {Math.round(r.score)} ({r.grade}) to{' '}
                        {Math.round(lifted)} ({grade(lifted)}) and the overall score by {gain.toFixed(1)} points.
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="rounded-lg bg-good-soft/50 px-3 py-4 text-sm text-good">Every card scores 80 or more.</p>
            )}
          </div>
        </div>
        <p className="mt-5 border-t border-line pt-3 text-xs text-ink-muted">
          How it’s worked out: object score = (average of its Area 1 cards + average of its Area 2 cards) ÷ 2 — one area if only one has been checked.
          Overall = the average of the object scores. Grades: A 90+, B 80–89, C 70–79, D 60–69, F below 60. Cards shown for information (All Fields) aren’t scored.
          {latest ? ` Latest check: ${fmtDate(latest.completedAt ?? latest.createdAt)}.` : ''}
        </p>
      </SectionCard>
    </div>
  );
}
