import { motion } from 'framer-motion';
import { MousePointerClick } from 'lucide-react';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { ChartTooltip, FindingsBySeverityChart, ScoreTrendChart } from '@/components/charts/Charts';
import { InfoTip } from '@/components/ui/HelpTip';
import { EmptyState } from '@/components/ui/States';
import { ScoreRing } from '@/components/ui/Visuals';
import { CATEGORIES, CATEGORY_COLORS, getArea } from '@/config/categories';
import { cx, fmtCompact, fmtDate, fmtNumber, scoreBand } from '@/lib/format';
import { getCategoryScore } from '@/lib/health';
import type { Assessment, AssessmentResults, CategoryId, Finding } from '@/types';
import { ProblemHeatmap, ProblemTreemap } from './DashboardCharts';

/** Charts-first, clickable view of one health check: the "Dashboard" tab on the Reports page. */
export function ReportDashboard({
  assessment,
  results,
  findings,
  history,
  category,
  onCategory,
}: {
  assessment: Assessment;
  results: AssessmentResults;
  findings: Finding[];
  history: Assessment[];
  category: 'all' | CategoryId;
  onCategory: (c: 'all' | CategoryId) => void;
}) {
  const navigate = useNavigate();
  const base = `/results?assessment=${encodeURIComponent(assessment.id)}`;
  const topics = CATEGORIES.filter((c) => category === 'all' || c.id === category);
  const score = category === 'all' ? results.overallScore : getCategoryScore(results, category);
  const band = scoreBand(score);

  const radar = CATEGORIES.map((c) => ({ topic: c.shortName, score: getCategoryScore(results, c.id) ?? 0 }));

  const areaData = results.areas
    .filter((a) => a.status === 'assessed' && a.score !== null)
    .map((a) => ({ area: getArea(a.areaId), score: a.score as number }))
    .filter((x) => x.area && topics.some((t) => t.id === x.area!.categoryId))
    .sort((a, b) => a.score - b.score)
    .map(({ area, score: s }) => ({ id: area!.id, cat: area!.categoryId, name: `#${area!.number} ${area!.name}`, short: `Area ${area!.number}`, score: s, fill: CATEGORY_COLORS[area!.categoryId] }));

  const byObject = Object.entries(
    findings.reduce<Record<string, number>>((acc, f) => {
      if (f.objectName && f.affectedRecords > 0) acc[f.objectName] = (acc[f.objectName] ?? 0) + f.affectedRecords;
      return acc;
    }, {}),
  )
    .map(([name, records]) => ({ name, records }))
    .sort((a, b) => b.records - a.records)
    .slice(0, 7);

  const trend = history.filter((a) => a.organizationName === assessment.organizationName);
  const chartHeight = Math.max(240, areaData.length * 28 + 30);

  return (
    <motion.div initial="hidden" animate="show" variants={{ hidden: {}, show: { transition: { staggerChildren: 0.06 } } }} className="space-y-6">
      <p className="no-print flex items-center gap-1.5 text-xs text-ink-subtle">
        <MousePointerClick className="h-3.5 w-3.5" /> Charts are clickable — open an area, a group of problems, or filter by topic.
      </p>

      {/* Row 1: the headline */}
      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title={category === 'all' ? 'Overall health' : 'Topic health'} info="The score from this health check. Areas checked earlier are included.">
          <div className="relative flex h-[250px] flex-col items-center justify-center">
            <div className="absolute h-40 w-40 rounded-full blur-3xl" style={{ background: band.color, opacity: score === null ? 0 : 0.18 }} />
            <ScoreRing score={score} size={170} stroke={14} label="out of 100" showBand={false} />
            <span className="relative mt-3 rounded-full px-3 py-1 text-xs font-semibold" style={{ color: band.color, background: `color-mix(in srgb, ${band.color} 12%, transparent)` }}>
              {band.label}
            </span>
            <span className="relative mt-1.5 text-xs text-ink-subtle">
              {assessment.organizationName} · {fmtDate(assessment.completedAt ?? assessment.createdAt)}
            </span>
          </div>
        </Panel>

        <Panel title="Score by topic" info="How each topic scored. Click a topic below to focus the whole dashboard on it.">
          <div className="h-[200px]">
            <ResponsiveContainer>
              <RadarChart data={radar} outerRadius="74%">
                <PolarGrid stroke="rgb(var(--line))" />
                <PolarAngleAxis dataKey="topic" tick={{ fontSize: 11, fill: 'rgb(var(--ink-muted))' }} />
                <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                <Tooltip content={<ChartTooltip />} />
                <Radar name="Score" dataKey="score" stroke="rgb(var(--brand))" fill="rgb(var(--brand))" fillOpacity={0.25} strokeWidth={2} animationDuration={1100} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 flex flex-wrap justify-center gap-1.5">
            {CATEGORIES.map((c) => {
              const s = getCategoryScore(results, c.id);
              const active = category === c.id;
              return (
                <button
                  key={c.id}
                  disabled={s === null}
                  onClick={() => onCategory(active ? 'all' : c.id)}
                  aria-pressed={active}
                  className={cx(
                    'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition disabled:cursor-default disabled:opacity-40',
                    active ? 'border-transparent text-white' : 'border-line hover:border-ink-subtle/40',
                  )}
                  style={active ? { background: CATEGORY_COLORS[c.id] } : undefined}
                  title={s === null ? 'Not checked yet' : active ? 'Show all topics' : `Focus on ${c.name}`}
                >
                  {!active && <span className="h-2 w-2 rounded-full" style={{ background: CATEGORY_COLORS[c.id] }} />}
                  {c.shortName}
                  <span className={cx('tabular-nums', !active && 'text-ink-subtle')}>{s ?? '—'}</span>
                </button>
              );
            })}
          </div>
        </Panel>

        <Panel title="Problems by urgency" info="How urgent the problems are. Click a slice or a row to open those problems.">
          <FindingsBySeverityChart findings={findings} size={170} onSelect={(s) => navigate(`${base}&severity=${s}${category === 'all' ? '' : `&category=${category}`}`)} />
        </Panel>
      </div>

      {/* Row 2: where scores are low, and where problems concentrate */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Score for each area" info="Every area that was checked, lowest score first. Click a bar to open the area.">
          {areaData.length === 0 ? (
            <EmptyState className="py-10" title="No areas checked" description="Run a health check for this topic." />
          ) : (
            <div style={{ height: chartHeight }}>
              <ResponsiveContainer>
                <BarChart data={areaData} layout="vertical" margin={{ left: 4, right: 30, top: 4, bottom: 4 }} barCategoryGap="22%">
                  <CartesianGrid horizontal={false} strokeDasharray="3 3" />
                  <XAxis type="number" domain={[0, 100]} tickLine={false} axisLine={false} />
                  <YAxis type="category" dataKey="short" width={64} tickLine={false} axisLine={false} tick={{ fontSize: 11 }} />
                  <Tooltip
                    cursor={{ fill: 'rgb(var(--muted))' }}
                    content={({ active, payload }) => (
                      <ChartTooltip active={active} payload={payload} label={(payload?.[0]?.payload as { name?: string } | undefined)?.name} />
                    )}
                  />
                  <Bar
                    dataKey="score"
                    name="Score"
                    radius={[0, 4, 4, 0]}
                    animationDuration={1000}
                    className="cursor-pointer"
                    onClick={(d: { id?: string; cat?: string }) => d?.id && navigate(`/assessment/${d.cat}/${d.id}`)}
                    label={{ position: 'right', fontSize: 11, fill: 'rgb(var(--ink))' }}
                  >
                    {areaData.map((d) => (
                      <Cell key={d.id} fill={d.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>

        <Panel title="Problem heatmap" info="Topics down the side, urgency across the top. Darker means more problems. Click a cell to open them.">
          <ProblemHeatmap
            findings={findings}
            topics={topics.map((t) => t.id)}
            onSelect={(c, s) => navigate(`${base}&category=${c}&severity=${s}`)}
          />
        </Panel>
      </div>

      {/* Row 3: what to fix, by size */}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Panel title="Where the problems are" info="Each box is one problem, sized by how many records it affects and coloured by urgency. Click a box to see how to fix it.">
            <ProblemTreemap findings={findings} onSelect={(f) => navigate(`${base}&finding=${encodeURIComponent(f.id)}`)} height={300} />
          </Panel>
        </div>
        <Panel title="Records affected by object" info="How many records the problems touch, per Salesforce object. Click a bar to see that object’s problems.">
          {byObject.length === 0 ? (
            <EmptyState className="py-10" title="No records affected" description="No problems point at specific records." />
          ) : (
            <div className="h-[300px]">
              <ResponsiveContainer>
                <BarChart data={byObject} layout="vertical" margin={{ left: 4, right: 40, top: 4, bottom: 4 }} barCategoryGap="25%">
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="name" width={88} tickLine={false} axisLine={false} tick={{ fontSize: 11 }} />
                  <Tooltip cursor={{ fill: 'rgb(var(--muted))' }} content={<ChartTooltip />} />
                  <Bar
                    dataKey="records"
                    name="Records affected"
                    fill="rgb(var(--brand))"
                    radius={[0, 4, 4, 0]}
                    animationDuration={1000}
                    className="cursor-pointer"
                    onClick={(d: { name?: string }) => d?.name && navigate(`${base}&object=${encodeURIComponent(d.name)}`)}
                    label={{ position: 'right', fontSize: 11, fill: 'rgb(var(--ink))', formatter: (v: number) => fmtCompact(v) }}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>
      </div>

      {/* Row 4: progress over time */}
      <Panel title="Health over time" info="Your overall score after each health check of this Salesforce.">
        <ScoreTrendChart assessments={trend} height={220} />
        {trend.length >= 2 && (
          <p className="mt-2 text-center text-xs text-ink-subtle">
            {fmtNumber(trend.filter((a) => a.status === 'completed').length)} checks since {fmtDate(trend[trend.length - 1].completedAt ?? trend[trend.length - 1].createdAt)}
          </p>
        )}
      </Panel>
    </motion.div>
  );
}

function Panel({ title, info, children }: { title: string; info: string; children: ReactNode }) {
  return (
    <motion.section
      variants={{ hidden: { opacity: 0, y: 14 }, show: { opacity: 1, y: 0 } }}
      whileHover={{ y: -2 }}
      transition={{ type: 'spring', stiffness: 300, damping: 26 }}
      className="card print-break-avoid flex h-full flex-col p-5 transition-shadow hover:shadow-pop"
    >
      <h3 className="mb-3 flex items-center gap-1.5 text-sm font-semibold">
        {title}
        <InfoTip label={`About: ${title}`}>{info}</InfoTip>
      </h3>
      <div className="flex-1">{children}</div>
    </motion.section>
  );
}
