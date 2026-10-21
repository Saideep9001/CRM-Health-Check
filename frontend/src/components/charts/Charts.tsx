import { LineChart as LineIcon } from 'lucide-react';
import { useState } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from 'recharts';
import type { NameType, ValueType } from 'recharts/types/component/DefaultTooltipContent';
import { CATEGORIES, CATEGORY_COLORS } from '@/config/categories';
import { cx, fmtDate } from '@/lib/format';
import { countBySeverity, findingsForCategory, getCategoryScore, SEVERITIES } from '@/lib/health';
import type { Assessment, AssessmentResults, Finding, Severity } from '@/types';
import { EmptyState } from '../ui/States';
import { AnimatedNumber } from '../ui/Visuals';

export const SEVERITY_COLORS: Record<Severity, string> = {
  critical: 'rgb(var(--sev-critical))',
  high: 'rgb(var(--sev-high))',
  medium: 'rgb(var(--sev-medium))',
  low: 'rgb(var(--sev-low))',
};

/** Shared tooltip so every chart reads the same in both themes. */
export function ChartTooltip({ active, payload, label, unit = '' }: TooltipProps<ValueType, NameType> & { unit?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-pop">
      {label !== undefined && <p className="mb-1 font-semibold text-ink">{label}</p>}
      {payload.map((p) => (
        <div key={String(p.dataKey) + String(p.name)} className="flex items-center gap-2 text-ink-muted">
          <span className="h-2 w-2 rounded-full" style={{ background: (p.payload?.fill as string) ?? p.color }} />
          <span>{p.name}</span>
          <span className="ml-auto pl-3 font-semibold tabular-nums text-ink">
            {p.value}
            {unit}
          </span>
        </div>
      ))}
    </div>
  );
}

const NoData = ({ text }: { text: string }) => (
  <EmptyState className="py-10" icon={<LineIcon className="h-5 w-5" />} title="No data yet" description={text} />
);

/** Category scores as horizontal bars. Unscored categories are listed underneath. */
export function CategoryHealthChart({ results, height = 260 }: { results: AssessmentResults | null; height?: number }) {
  const data = CATEGORIES.map((c) => ({ name: c.shortName, score: getCategoryScore(results, c.id), fill: CATEGORY_COLORS[c.id] }));
  const scored = data.filter((d) => d.score !== null) as { name: string; score: number; fill: string }[];
  const unscored = data.filter((d) => d.score === null);
  if (!scored.length) return <NoData text="Scores for each topic appear after your first health check finishes." />;
  return (
    <div>
      <div style={{ height }}>
        <ResponsiveContainer>
          <BarChart data={scored} layout="vertical" margin={{ left: 8, right: 36, top: 4, bottom: 4 }} barCategoryGap={10}>
            <CartesianGrid horizontal={false} strokeDasharray="3 3" />
            <XAxis type="number" domain={[0, 100]} tickLine={false} axisLine={false} />
            <YAxis type="category" dataKey="name" width={92} tickLine={false} axisLine={false} />
            <Tooltip cursor={{ fill: 'rgb(var(--muted))' }} content={<ChartTooltip />} />
            <Bar
              dataKey="score"
              name="Score"
              radius={[0, 4, 4, 0]}
              animationDuration={1100}
              label={{ position: 'right', fill: 'rgb(var(--ink))', fontSize: 12, fontWeight: 600 }}
            >
              {scored.map((d) => (
                <Cell key={d.name} fill={d.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      {unscored.length > 0 && (
        <p className="mt-2 text-xs text-ink-subtle">Not scored: {unscored.map((u) => u.name).join(', ')}</p>
      )}
    </div>
  );
}

/** Donut of findings by severity with a hoverable legend. */
export function FindingsBySeverityChart({ findings, size = 190, onSelect }: { findings: Finding[]; size?: number; onSelect?: (s: Severity) => void }) {
  const counts = countBySeverity(findings);
  const total = findings.length;
  const data = SEVERITIES.map((s) => ({ name: s, value: counts[s], fill: SEVERITY_COLORS[s] }));
  const [hover, setHover] = useState<number | null>(null);
  if (!total) return <NoData text="No problems to show — nice!" />;

  return (
    // Wraps by the space it has (not the screen size), so it fits narrow dashboard panels too.
    <div className="flex flex-wrap items-center justify-center gap-5">
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <ResponsiveContainer>
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              innerRadius="68%"
              outerRadius="100%"
              paddingAngle={2}
              stroke="rgb(var(--surface))"
              strokeWidth={2}
              animationDuration={1100}
              onMouseEnter={(_, i) => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onClick={(_, i) => onSelect?.(data[i].name)}
              className={onSelect ? 'cursor-pointer' : undefined}
            >
              {data.map((d, i) => (
                <Cell key={d.name} fill={d.fill} opacity={hover === null || hover === i ? 1 : 0.35} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-3xl font-semibold tracking-tight">
            <AnimatedNumber value={hover === null ? total : data[hover].value} duration={0.5} />
          </span>
          <span className="text-xs capitalize text-ink-subtle">{hover === null ? 'Total findings' : data[hover].name}</span>
        </div>
      </div>
      <ul className="min-w-[12rem] flex-1 space-y-2">
        {data.map((d, i) => (
          <li
            key={d.name}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
            onClick={() => d.value && onSelect?.(d.name)}
            className={cx('flex items-center gap-3 rounded-md px-2 py-1.5 text-sm transition', hover === i && 'bg-muted', onSelect && d.value > 0 && 'cursor-pointer')}
          >
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: d.fill }} />
            <span className="flex-1 capitalize text-ink-muted">{d.name}</span>
            <span className="font-semibold tabular-nums">{d.value}</span>
            <span className="w-10 text-right text-xs tabular-nums text-ink-subtle">{Math.round((d.value / total) * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Stacked bars: findings per category split by severity. */
export function IssuesByCategoryChart({ findings, height = 260 }: { findings: Finding[]; height?: number }) {
  if (!findings.length) return <NoData text="No problems to show — nice!" />;
  const data = CATEGORIES.map((c) => ({ name: c.shortName, ...countBySeverity(findingsForCategory(findings, c.id)) }));
  return (
    <div>
      <div style={{ height }}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ left: -16, right: 8, top: 8, bottom: 0 }} barCategoryGap="28%">
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="name" tickLine={false} axisLine={false} interval={0} tick={{ fontSize: 11 }} />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} />
            <Tooltip cursor={{ fill: 'rgb(var(--muted))' }} content={<ChartTooltip />} />
            {SEVERITIES.map((s, i) => (
              <Bar
                key={s}
                dataKey={s}
                name={s[0].toUpperCase() + s.slice(1)}
                stackId="a"
                fill={SEVERITY_COLORS[s]}
                stroke="rgb(var(--surface))"
                strokeWidth={1}
                radius={i === SEVERITIES.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]}
                animationDuration={900}
                animationBegin={i * 120}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <SeverityLegend />
    </div>
  );
}

export function SeverityLegend() {
  return (
    <div className="mt-3 flex flex-wrap justify-center gap-4 text-xs text-ink-muted">
      {SEVERITIES.map((s) => (
        <span key={s} className="flex items-center gap-1.5 capitalize">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: SEVERITY_COLORS[s] }} />
          {s}
        </span>
      ))}
    </div>
  );
}

/** Overall score across completed assessments (oldest → newest). */
export function ScoreTrendChart({ assessments, height = 240 }: { assessments: Assessment[]; height?: number }) {
  const data = assessments
    .filter((a) => a.status === 'completed' && a.overallScore !== null)
    .sort((a, b) => (a.completedAt ?? a.createdAt).localeCompare(b.completedAt ?? b.createdAt))
    .map((a) => ({ label: fmtDate(a.completedAt ?? a.createdAt), name: a.name, overall: a.overallScore }));
  if (data.length < 2) return <NoData text="Run two or more checks to see a trend." />;
  return (
    <div style={{ height }}>
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ left: -20, right: 8, top: 8, bottom: 0 }}>
          <defs>
            <linearGradient id="grad-overall" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgb(var(--brand))" stopOpacity={0.25} />
              <stop offset="100%" stopColor="rgb(var(--brand))" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis dataKey="label" tickLine={false} axisLine={false} />
          <YAxis domain={[0, 100]} tickLine={false} axisLine={false} />
          <Tooltip cursor={{ stroke: 'rgb(var(--ink-subtle))', strokeDasharray: '3 3' }} content={<ChartTooltip />} />
          <Area
            type="monotone"
            dataKey="overall"
            name="Overall health"
            stroke="rgb(var(--brand))"
            strokeWidth={2}
            fill="url(#grad-overall)"
            dot={{ r: 3, strokeWidth: 0, fill: 'rgb(var(--brand))' }}
            activeDot={{ r: 5, strokeWidth: 2, stroke: 'rgb(var(--surface))' }}
            animationDuration={1300}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
