import { motion } from 'framer-motion';
import { ResponsiveContainer, Tooltip, Treemap } from 'recharts';
import { SEVERITY_COLORS } from '@/components/charts/Charts';
import { EmptyState } from '@/components/ui/States';
import { CATEGORIES } from '@/config/categories';
import { fmtNumber } from '@/lib/format';
import { SEVERITIES } from '@/lib/health';
import type { CategoryId, Finding, Severity } from '@/types';

const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

/** Topics × urgency grid. Darker cells hold more problems; click a cell to open those problems. */
export function ProblemHeatmap({
  findings,
  topics,
  onSelect,
}: {
  findings: Finding[];
  topics: CategoryId[];
  onSelect: (category: CategoryId, severity: Severity) => void;
}) {
  const rows = CATEGORIES.filter((c) => topics.includes(c.id));
  const count = (c: CategoryId, s: Severity) => findings.filter((f) => f.categoryId === c && f.severity === s).length;
  const max = Math.max(1, ...rows.flatMap((r) => SEVERITIES.map((s) => count(r.id, s))));

  if (!findings.length) return <EmptyState className="py-10" title="No problems" description="Nothing to map — nice!" />;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] border-separate" style={{ borderSpacing: 6 }}>
        <thead>
          <tr>
            <th />
            {SEVERITIES.map((s) => (
              <th key={s} className="pb-1 text-center text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full" style={{ background: SEVERITY_COLORS[s] }} />
                  {cap(s)}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={r.id}>
              <th className="whitespace-nowrap pr-2 text-left text-xs font-medium text-ink-muted">{r.shortName}</th>
              {SEVERITIES.map((s, si) => {
                const n = count(r.id, s);
                const strength = n ? 0.18 + 0.82 * (n / max) : 0;
                return (
                  <td key={s} className="p-0">
                    <motion.button
                      initial={{ opacity: 0, scale: 0.8 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ delay: 0.04 * (ri * SEVERITIES.length + si) }}
                      whileHover={n ? { scale: 1.06 } : undefined}
                      disabled={!n}
                      onClick={() => onSelect(r.id, s)}
                      title={n ? `${n} ${s} problem${n === 1 ? '' : 's'} in ${r.name} — click to open` : `No ${s} problems in ${r.name}`}
                      className="flex h-11 w-full items-center justify-center rounded-lg border border-line text-sm font-semibold tabular-nums transition disabled:cursor-default"
                      style={
                        n
                          ? { background: `color-mix(in srgb, ${SEVERITY_COLORS[s]} ${Math.round(strength * 100)}%, transparent)`, color: strength > 0.55 ? 'white' : undefined }
                          : { color: 'rgb(var(--ink-subtle))' }
                      }
                    >
                      {n || '·'}
                    </motion.button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface TileProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  name?: string;
  size?: number;
  fill?: string;
  depth?: number;
}

function Tile({ x = 0, y = 0, width = 0, height = 0, name, size, fill, depth }: TileProps) {
  if (depth !== 1) return null;
  const showName = width > 80 && height > 34;
  const showSize = width > 56 && height > 20;
  return (
    <g className="cursor-pointer">
      <rect x={x} y={y} width={width} height={height} rx={6} ry={6} fill={fill} stroke="rgb(var(--surface))" strokeWidth={3} className="transition-opacity hover:opacity-85" />
      {showName && (
        <foreignObject x={x + 8} y={y + 6} width={width - 16} height={height - 12} style={{ pointerEvents: 'none' }}>
          <div className="flex h-full flex-col text-white">
            <span className="line-clamp-2 text-[11px] font-semibold leading-tight">{name}</span>
            <span className="mt-auto text-[11px] opacity-90">{fmtNumber(size ?? 0)} records</span>
          </div>
        </foreignObject>
      )}
      {!showName && showSize && (
        <text x={x + width / 2} y={y + height / 2 + 4} textAnchor="middle" fill="white" fontSize={10} fontWeight={600} style={{ pointerEvents: 'none' }}>
          {fmtNumber(size ?? 0)}
        </text>
      )}
    </g>
  );
}

/** Each problem as a box sized by how many records it affects, coloured by urgency. Click to open it. */
export function ProblemTreemap({ findings, onSelect, height = 280 }: { findings: Finding[]; onSelect: (f: Finding) => void; height?: number }) {
  const data = findings
    .filter((f) => f.affectedRecords > 0)
    .sort((a, b) => b.affectedRecords - a.affectedRecords)
    .slice(0, 18)
    .map((f) => ({ name: f.name, size: f.affectedRecords, fill: SEVERITY_COLORS[f.severity], finding: f }));
  if (!data.length) return <EmptyState className="py-10" title="No records affected" description="No problems point at specific records." />;

  return (
    <div style={{ height }}>
      <ResponsiveContainer>
        <Treemap
          data={data}
          dataKey="size"
          aspectRatio={4 / 3}
          isAnimationActive
          animationDuration={900}
          content={<Tile />}
          onClick={(node) => {
            const f = (node as unknown as { finding?: Finding } | undefined)?.finding;
            if (f) onSelect(f);
          }}
        >
          <Tooltip
            content={({ active, payload }) => {
              const p = payload?.[0]?.payload as { name?: string; size?: number; finding?: Finding } | undefined;
              if (!active || !p?.finding) return null;
              return (
                <div className="max-w-xs rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-pop">
                  <p className="font-semibold text-ink">{p.name}</p>
                  <p className="mt-0.5 text-ink-muted">
                    {fmtNumber(p.size ?? 0)} records · <span className="capitalize">{p.finding.severity}</span>
                    {p.finding.objectName ? ` · ${p.finding.objectName}` : ''}
                  </p>
                  <p className="mt-1 text-[11px] text-brand">Click to see how to fix it</p>
                </div>
              );
            }}
          />
        </Treemap>
      </ResponsiveContainer>
    </div>
  );
}
