import { motion } from 'framer-motion';
import { Award, Download, Lightbulb, Printer, TrendingDown, TrendingUp } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useNavigate } from 'react-router-dom';
import { ChartTooltip } from '@/components/charts/Charts';
import { cardTone } from '@/components/category/DiagnosticAreaCard';
import { Button } from '@/components/ui/Button';
import { PageHeader, SectionCard } from '@/components/ui/Page';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States';
import { AnimatedNumber } from '@/components/ui/Visuals';
import { useLatestAssessment } from '@/hooks/useLatestAssessment';
import { cx, fmtDate } from '@/lib/format';
import { countBySeverity, getAreaResult } from '@/lib/health';
import type { IndicatorValue } from '@/types';

/** The objects scored, in this order. */
const OBJECTS = [
  { name: 'Account', plural: 'Accounts' },
  { name: 'Lead', plural: 'Leads' },
  { name: 'Contact', plural: 'Contacts' },
  { name: 'Opportunity', plural: 'Opportunities' },
] as const;

/** Three colours, the same as the cards: green 80+, orange 40–79, red below 40. */
type Tone = 'good' | 'warn' | 'bad';
const toneOf = (score: number): Tone => cardTone(score);
// Light shades, so the page stays easy on the eye: bars and swatches in the light colour, numbers in the strong one.
const TONE_FILL = { good: '#86efac', warn: '#fdba74', bad: '#fca5a5' } as const;
const TONE_PALE = { good: '#dcfce7', warn: '#ffedd5', bad: '#fee2e2' } as const;
const TONE_TEXT = { good: 'rgb(var(--good))', warn: 'rgb(var(--warn))', bad: 'rgb(var(--bad))' } as const;
const TONE_CLASS = { good: 'bg-good-soft text-good ring-good/30', warn: 'bg-warn-soft text-warn ring-warn/30', bad: 'bg-bad-soft text-bad ring-bad/30' } as const;
const SCALE: { tone: Tone; range: string; name: string; line: string }[] = [
  { tone: 'good', range: '80–100%', name: 'Healthy', line: 'Little to fix; keep it this way.' },
  { tone: 'warn', range: '40–79%', name: 'Needs a look', line: 'Some clean-up needed; plan it in.' },
  { tone: 'bad', range: '0–39%', name: 'Needs work', line: 'Serious gaps; fix these first.' },
];
const statusOf = (score: number) => SCALE.find((s) => s.tone === toneOf(score))!.name;
const pctText = (score: number) => `${Math.round(score)}%`;

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
type Row = { name: string; plural: string; cards: Card[]; a1: number | null; a2: number | null; score: number };

const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
/** Object score = (average of its Area 1 cards + average of its Area 2 cards) ÷ 2 (one area if only one has cards). */
function scoreOf(cards: Card[]): { a1: number | null; a2: number | null; score: number } {
  const a1 = avg(cards.filter((c) => c.area === 'area-1').map((c) => c.score));
  const a2 = avg(cards.filter((c) => c.area === 'area-2').map((c) => c.score));
  const halves = [a1, a2].filter((x): x is number => x != null);
  return { a1, a2, score: halves.reduce((a, b) => a + b, 0) / halves.length };
}

const AXIS = { tickLine: false, axisLine: false } as const;

/** Data Quality Scorecard: a score (%) per object and overall, from the latest check's Area 1 and Area 2 results,
 *  for the objects that check was run on. */
export default function ScorecardPage() {
  const navigate = useNavigate();
  const { state, error, refetch, results, findings, latest } = useLatestAssessment();
  if (state === 'loading') return <LoadingState rows={6} label="Loading the scorecard…" />;
  if (state === 'error') return <ErrorState error={error} onRetry={refetch} />;

  // Only the objects the user chose for the latest check (all four when the check didn't narrow them).
  const chosen = latest?.scope?.objects?.length ? new Set(latest.scope.objects) : null;
  const objects = OBJECTS.filter((o) => !chosen || chosen.has(o.name));
  const areas = (['area-1', 'area-2'] as const).map((id) => ({ id, r: getAreaResult(results, id) }));
  const cards: (Card & { object: string })[] = areas.flatMap(({ id, r }) =>
    (r?.indicators ?? []).flatMap((v: IndicatorValue) => {
      const object = v.score != null ? objectOf(v.label) : null;
      return object && objects.some((o) => o.name === object) ? [{ label: v.label, card: cardName(v.label), score: v.score!, area: id, object }] : [];
    }),
  );
  const rows: Row[] = objects.flatMap((o) => {
    const mine = cards.filter((c) => c.object === o.name);
    if (!mine.length) return [];
    const s = scoreOf(mine);
    return [{ name: o.name, plural: o.plural, cards: mine, ...s }];
  });
  if (!rows.length) {
    return (
      <>
        <PageHeader eyebrow="Data Quality & Optimization" title="Data Quality Scorecard" />
        <EmptyState className="py-16" icon={<Award className="h-5 w-5" />} title="No scores yet"
          description="Run a health check of Area 1 (Record Data Quality) and Area 2 (Redundant Fields) to score the objects you choose." />
      </>
    );
  }
  const overall = rows.reduce((a, r) => a + r.score, 0) / rows.length;
  const overallTone = toneOf(overall);
  const checkedAt = [getAreaResult(results, 'area-1')?.checkedAt, getAreaResult(results, 'area-2')?.checkedAt].filter(Boolean) as string[];

  // Open problems per object, in three colours by urgency (Areas 1 and 2)
  const problems = rows.map((r) => {
    const c = countBySeverity(findings.filter((f) => (f.areaId === 'area-1' || f.areaId === 'area-2') && f.objectName === r.name && f.status !== 'resolved'));
    return { name: r.plural, bad: c.critical, warn: c.high, good: c.medium + c.low };
  });
  const byStatus = SCALE.map((s) => ({ ...s, cards: cards.filter((c) => toneOf(c.score) === s.tone).length }));

  // Analysis, worked out from the numbers: what drags each object down and what would lift the overall score most.
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
  const open = (c: Card, obj: string) => navigate(`/measures/${c.area}?label=${encodeURIComponent(c.label)}&object=${obj}`);

  const downloadCsv = () => {
    const head = ['Object', 'Score (%)', 'Status', 'Area 1 average', 'Area 2 average', ...allCardNames];
    const lines = [
      head,
      ...rows.map((r) => [r.plural, r.score.toFixed(0), statusOf(r.score), r.a1?.toFixed(0) ?? '', r.a2?.toFixed(0) ?? '',
        ...allCardNames.map((n) => r.cards.find((c) => c.card === n)?.score.toFixed(0) ?? '')]),
      ['Overall', overall.toFixed(0), statusOf(overall)],
    ];
    const csv = lines.map((l) => l.map((x) => `"${String(x).replace(/"/g, '""')}"`).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    Object.assign(document.createElement('a'), { href: url, download: 'data-quality-scorecard.csv' }).click();
    URL.revokeObjectURL(url);
  };

  const chartH = Math.max(180, 70 + rows.length * 46); // horizontal bars: grows with the objects checked

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Data Quality & Optimization"
        title="Data Quality Scorecard"
        description={`${rows.map((r) => r.plural).join(', ')} — scored from the latest Area 1 and Area 2 results${checkedAt.length ? ` (checked ${[...new Set(checkedAt.map(fmtDate))].join(' and ')})` : ''}.`}
        actions={
          <div className="flex gap-2 print:hidden">
            <Button size="sm" icon={<Download className="h-4 w-4" />} onClick={downloadCsv}>Download CSV</Button>
            <Button size="sm" variant="ghost" icon={<Printer className="h-4 w-4" />} onClick={() => window.print()}>Print / Save as PDF</Button>
          </div>
        }
      />

      {/* Grades, with the colour scale beside them */}
      <div className="flex flex-col gap-4 xl:flex-row">
        <div className="grid flex-1 gap-4 sm:grid-cols-2 lg:grid-cols-[repeat(auto-fit,minmax(190px,1fr))]">
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
            className="relative overflow-hidden rounded-2xl border p-5 shadow-sm"
            style={{ background: TONE_PALE[overallTone], borderColor: TONE_FILL[overallTone] }}>
            <span className="pointer-events-none absolute -right-8 -top-10 h-32 w-32 rounded-full bg-white/40" />
            <span className="pointer-events-none absolute -bottom-12 right-8 h-24 w-24 rounded-full bg-white/30" />
            <span className="text-sm font-semibold text-slate-700">Overall Data Quality</span>
            <span className="mt-3 flex items-baseline gap-0.5" style={{ color: TONE_TEXT[overallTone] }}>
              <span className="text-5xl font-bold tabular-nums"><AnimatedNumber value={Math.round(overall)} /></span>
              <span className="text-2xl font-semibold">%</span>
            </span>
            <span className="mt-3 block h-1.5 overflow-hidden rounded-full bg-white/70">
              <motion.span className="block h-full rounded-full" style={{ background: TONE_FILL[overallTone] }}
                initial={{ width: 0 }} animate={{ width: `${Math.max(overall, 2)}%` }} transition={{ duration: 0.9 }} />
            </span>
            <span className="mt-2 block text-xs text-slate-600">
              {statusOf(overall)} · {rows.length === 1 ? `${rows[0].plural} only` : `average of ${rows.length} objects`}
            </span>
          </motion.div>
          {rows.map((r, i) => {
            const t = toneOf(r.score);
            return (
              <motion.div key={r.name} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * (i + 1) }}
                className="relative overflow-hidden rounded-2xl border border-line bg-surface p-5 shadow-sm">
                <span className="absolute inset-x-0 top-0 h-1" style={{ background: TONE_FILL[t] }} />
                <span className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-ink">{r.plural}</span>
                  <span className={cx('rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide', TONE_CLASS[t])}>{statusOf(r.score)}</span>
                </span>
                <span className="mt-3 flex items-baseline gap-0.5" style={{ color: TONE_TEXT[t] }}>
                  <span className="text-4xl font-bold tabular-nums"><AnimatedNumber value={Math.round(r.score)} /></span>
                  <span className="text-xl font-semibold">%</span>
                </span>
                <span className="mt-3 block h-1.5 overflow-hidden rounded-full bg-muted">
                  <motion.span className="block h-full rounded-full" style={{ background: TONE_FILL[t] }}
                    initial={{ width: 0 }} animate={{ width: `${Math.max(r.score, 2)}%` }} transition={{ duration: 0.9 }} />
                </span>
                <span className="mt-2 block text-[11px] text-ink-muted">
                  Records {r.a1 == null ? '—' : pctText(r.a1)} · Fields {r.a2 == null ? '—' : pctText(r.a2)} · {r.cards.length} cards
                </span>
              </motion.div>
            );
          })}
        </div>
        <div className="rounded-2xl border border-line bg-surface p-4 shadow-sm xl:w-64">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-ink-subtle">Colour scale</p>
          <ul className="space-y-3">
            {SCALE.map((s) => (
              <li key={s.tone} className="flex gap-3">
                <span className="mt-0.5 h-9 w-1.5 shrink-0 rounded-full" style={{ background: TONE_FILL[s.tone] }} />
                <span className="text-xs">
                  <span className="block font-semibold text-ink">{s.name} <span className="font-normal text-ink-subtle">· {s.range}</span></span>
                  <span className="block text-ink-muted">{s.line}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 border-t border-line pt-2 text-[11px] text-ink-subtle">Every score is out of 100%: the higher, the better.</p>
        </div>
      </div>

      {/* Charts */}
      <div className="grid gap-6 lg:grid-cols-2">
        <SectionCard title="Score by object" description="Out of 100%, the higher the better.">
          <div style={{ height: chartH }}>
            <ResponsiveContainer>
              <BarChart data={rows.map((r) => ({ name: r.plural, score: Math.round(r.score) }))} layout="vertical"
                margin={{ left: 8, right: 36, top: 4, bottom: 4 }} barCategoryGap={12} maxBarSize={28}>
                <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="rgb(var(--line))" />
                <XAxis type="number" domain={[0, 100]} ticks={[0, 40, 80, 100]} tickFormatter={(v: number) => `${v}%`} {...AXIS} tick={{ fill: 'rgb(var(--ink-subtle))', fontSize: 11 }} />
                <YAxis type="category" dataKey="name" width={96} {...AXIS} tick={{ fill: 'rgb(var(--ink-muted))', fontSize: 12 }} />
                <Tooltip cursor={{ fill: 'rgb(var(--muted))' }} content={<ChartTooltip unit="%" />} />
                <Bar dataKey="score" name="Score" radius={[0, 6, 6, 0]} background={{ fill: 'rgb(var(--muted))' }} animationDuration={900}>
                  {rows.map((r) => <Cell key={r.name} fill={TONE_FILL[toneOf(r.score)]} />)}
                  <LabelList dataKey="score" position="right" formatter={(v: number) => `${v}%`} style={{ fill: 'rgb(var(--ink))', fontSize: 12, fontWeight: 700 }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>

        <SectionCard title="Records vs fields" description="Area 1 (the data in the records) and Area 2 (the fields): each is half of an object’s score.">
          <div style={{ height: chartH }}>
            <ResponsiveContainer>
              <BarChart data={rows.map((r) => ({ name: r.plural, a1: r.a1 == null ? null : Math.round(r.a1), a2: r.a2 == null ? null : Math.round(r.a2) }))}
                layout="vertical" margin={{ left: 8, right: 40, top: 4, bottom: 4 }} barGap={3} barCategoryGap={12} maxBarSize={16}>
                <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="rgb(var(--line))" />
                <XAxis type="number" domain={[0, 100]} ticks={[0, 40, 80, 100]} tickFormatter={(v: number) => `${v}%`} {...AXIS} tick={{ fill: 'rgb(var(--ink-subtle))', fontSize: 11 }} />
                <YAxis type="category" dataKey="name" width={96} {...AXIS} tick={{ fill: 'rgb(var(--ink-muted))', fontSize: 12 }} />
                <Tooltip cursor={{ fill: 'rgb(var(--muted))' }} content={<ChartTooltip unit="%" />} />
                {(['a1', 'a2'] as const).map((k) => (
                  <Bar key={k} dataKey={k} name={k === 'a1' ? 'Records (Area 1)' : 'Fields (Area 2)'} radius={[0, 4, 4, 0]} animationDuration={900}>
                    {rows.map((r) => <Cell key={r.name} fill={(k === 'a1' ? TONE_FILL : TONE_PALE)[toneOf(r[k] ?? 0)]} stroke={TONE_FILL[toneOf(r[k] ?? 0)]} />)}
                    <LabelList dataKey={k} position="right" formatter={(v: number) => `${v}%`}
                      style={{ fill: 'rgb(var(--ink-muted))', fontSize: 10 }} />
                  </Bar>
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-1 text-[11px] text-ink-subtle">Solid bar: records · light bar: fields. The colour follows the scale.</p>
        </SectionCard>

        <SectionCard title="Open problems by object" description="Problems raised by Areas 1 and 2: red critical, orange high, green medium or low.">
          <div style={{ height: chartH }}>
            <ResponsiveContainer>
              <BarChart data={problems} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }} barCategoryGap={12} maxBarSize={28}>
                <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="rgb(var(--line))" />
                <XAxis type="number" allowDecimals={false} {...AXIS} tick={{ fill: 'rgb(var(--ink-subtle))', fontSize: 11 }} />
                <YAxis type="category" dataKey="name" width={96} {...AXIS} tick={{ fill: 'rgb(var(--ink-muted))', fontSize: 12 }} />
                <Tooltip cursor={{ fill: 'rgb(var(--muted))' }} content={<ChartTooltip />} />
                {(['bad', 'warn', 'good'] as const).map((t, i) => (
                  <Bar key={t} dataKey={t} name={t === 'bad' ? 'Critical' : t === 'warn' ? 'High' : 'Medium or low'} stackId="p" fill={TONE_FILL[t]}
                    stroke="rgb(var(--surface))" strokeWidth={2} radius={i === 2 ? [0, 4, 4, 0] : [0, 0, 0, 0]} animationDuration={900} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>

        <SectionCard title="Cards by status" description="How many of the scored cards fall in each colour, across the objects checked.">
          <div className="flex flex-col justify-center gap-3 py-2" style={{ minHeight: chartH }}>
            {byStatus.map((s) => (
              <div key={s.tone} className="flex items-center gap-3">
                <span className="w-24 shrink-0 text-xs font-medium text-ink-muted">{s.name}</span>
                <span className="h-7 flex-1 overflow-hidden rounded-lg bg-muted">
                  <motion.span className="flex h-full items-center justify-end rounded-lg pr-2 text-xs font-bold text-slate-800" style={{ background: TONE_FILL[s.tone] }}
                    initial={{ width: 0 }} animate={{ width: `${cards.length ? Math.max((100 * s.cards) / cards.length, s.cards ? 8 : 0) : 0}%` }} transition={{ duration: 0.9 }}>
                    {s.cards || ''}
                  </motion.span>
                </span>
                <span className="w-10 shrink-0 text-right text-xs tabular-nums text-ink-subtle">{cards.length ? Math.round((100 * s.cards) / cards.length) : 0}%</span>
              </div>
            ))}
            <p className="text-[11px] text-ink-subtle">{cards.length} scored cards in all.</p>
          </div>
        </SectionCard>

        <SectionCard className="lg:col-span-2" title="Every card’s score" description="Each object’s cards out of 100% (— = not a card for that object). Click a score to open the card.">
          <div className="scrollbar-thin overflow-x-auto">
            <table className="w-full text-left text-xs" style={{ minWidth: 240 + rows.length * 120 }}>
              <thead className="text-[11px] uppercase tracking-wide text-ink-subtle">
                <tr>
                  <th className="px-2 py-2">Card</th>
                  {rows.map((r) => <th key={r.name} className="w-36 px-2 py-2 text-center">{r.plural}</th>)}
                </tr>
              </thead>
              <tbody>
                {allCardNames.map((n) => (
                  <tr key={n} className="border-t border-line">
                    <td className="px-2 py-1.5 text-ink-muted">{n}</td>
                    {rows.map((r) => {
                      const c = r.cards.find((x) => x.card === n);
                      if (!c) return <td key={r.name} className="px-2 py-1.5 text-center text-ink-subtle">—</td>;
                      return (
                        <td key={r.name} className="px-1 py-1">
                          <button type="button" title={`${c.label}: ${pctText(c.score)} (${statusOf(c.score).toLowerCase()})`} onClick={() => open(c, r.name)}
                            className={cx('w-full rounded-md py-1.5 text-center font-semibold tabular-nums ring-1 transition hover:brightness-95', TONE_CLASS[toneOf(c.score)])}>
                            {pctText(c.score)}
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
                Overall the organization scores <b>{pctText(overall)}</b> ({statusOf(overall).toLowerCase()}) across{' '}
                {rows.length === 1 ? rows[0].plural : `${rows.length} objects`} and {cards.length} scored cards.
              </span>
            </li>
            <li className="flex gap-2">
              <TrendingDown className="mt-0.5 h-4 w-4 shrink-0 text-bad" />
              <span>
                {rows.length > 1 ? <>Weakest: <b>{ranked[0].plural}</b> ({pctText(ranked[0].score)}), held down most by </> : <>Held down most by </>}
                {[...ranked[0].cards].sort((a, b) => a.score - b.score).slice(0, 2).map((c) => `${c.card} (${pctText(c.score)})`).join(' and ')}.
              </span>
            </li>
            <li className="flex gap-2">
              <TrendingUp className="mt-0.5 h-4 w-4 shrink-0 text-good" />
              <span>
                {rows.length > 1 ? (
                  <>Strongest: <b>{ranked[ranked.length - 1].plural}</b> ({pctText(ranked[ranked.length - 1].score)}), best on </>
                ) : (
                  <>Best on </>
                )}
                {[...ranked[ranked.length - 1].cards].sort((a, b) => b.score - a.score).slice(0, 2).map((c) => `${c.card} (${pctText(c.score)})`).join(' and ')}.
              </span>
            </li>
            {gapRows.map((r) => (
              <li key={r.name} className="flex gap-2">
                <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
                <span>
                  {r.plural}: {r.a1! > r.a2!
                    ? `the records (${pctText(r.a1!)}) are in better shape than the fields (${pctText(r.a2!)}) — tidying unused and low-completion fields lifts it most.`
                    : `the fields (${pctText(r.a2!)}) are in better shape than the data in the records (${pctText(r.a1!)}) — duplicates, missing and invalid values are the work.`}
                </span>
              </li>
            ))}
          </ul>
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-subtle">What would lift the overall score most</p>
            {lifts.length ? (
              <ol className="space-y-2">
                {lifts.map(({ r, c, lifted, gain }, i) => (
                  <li key={c.label}>
                    <button type="button" onClick={() => open(c, r.name)}
                      className="flex w-full items-start gap-3 rounded-xl border border-line p-3 text-left text-sm transition hover:border-brand/40 hover:bg-muted/40">
                      <span className={cx('grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-bold ring-1', TONE_CLASS[toneOf(c.score)])}>{i + 1}</span>
                      <span>
                        <b>{r.plural}: {c.card}</b> is at {pctText(c.score)}. Bringing it to 80% (green) lifts {r.plural} from {pctText(r.score)} to{' '}
                        {pctText(lifted)} and the overall score by {gain.toFixed(1)} points.
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="rounded-lg bg-good-soft/50 px-3 py-4 text-sm text-good">Every card scores 80% or more.</p>
            )}
          </div>
        </div>
        <p className="mt-5 border-t border-line pt-3 text-xs text-ink-muted">
          How it’s worked out: object score = (average of its Area 1 cards + average of its Area 2 cards) ÷ 2 — one area if only one has been checked.
          Overall = the average of the objects checked. Colours: green 80–100%, orange 40–79%, red below 40%.
          Cards shown for information (All Fields) aren’t scored.
          {latest ? ` Latest check: ${fmtDate(latest.completedAt ?? latest.createdAt)}.` : ''}
        </p>
      </SectionCard>
    </div>
  );
}
