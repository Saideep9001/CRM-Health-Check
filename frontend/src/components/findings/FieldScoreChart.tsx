import { BarChart3, Table2 } from 'lucide-react';
import { useState } from 'react';
import { cx, fmtNumber } from '@/lib/format';
import type { FieldScore } from '@/types';

/** What a card's per-field number means, in words. */
const KINDS = {
  duplicates: { title: 'Duplicates by field', what: 'share their value with another record', of: 'with a value' },
  missing: { title: 'Empty by field', what: 'are empty', of: 'records' },
  standardization: { title: 'Odd values by field', what: 'are in an odd format or spelling', of: 'with a value' },
  filled: { title: 'Filled in by field', what: 'have it filled in', of: 'records', higher: true },
  grade: { title: 'Score by object', what: 'points', of: '', higher: true },
} as const;
export type FieldChartKind = keyof typeof KINDS;

export function chartKindFor(label: string): FieldChartKind | null {
  if (/^duplicate/i.test(label)) return 'duplicates';
  if (/missing/i.test(label)) return 'missing';
  if (/standardi/i.test(label)) return 'standardization';
  if (/low-completion/i.test(label)) return 'filled';
  if (/scorecard/i.test(label)) return 'grade';
  return null;
}

const PLOT = 176; // px height of the plot area
const pct = (n: number) => `${n % 1 ? n.toFixed(1) : n}%`;

/** A scale that fits the data (e.g. 0–10% when the worst field is 7%), so small numbers stay readable. */
function scaleMax(max: number): number {
  return [5, 10, 20, 25, 50, 100].find((m) => max <= m) ?? 100;
}

/** This card's number for each field (duplicated, empty or odd), as bars on a % scale with the counts on top. */
export function FieldScoreChart({ scores, kind }: { scores: FieldScore[]; kind: FieldChartKind }) {
  const [table, setTable] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const k = KINDS[kind];
  const top = scaleMax(Math.max(...scores.map((s) => s.pct), 0));
  const ticks = [top, (top * 3) / 4, top / 2, top / 4, 0];
  const higher = 'higher' in k && k.higher;
  const say = (f: FieldScore) => (kind === 'grade' ? `score ${fmtNumber(f.count)} of 100` : `${fmtNumber(f.count)} of ${fmtNumber(f.of)} ${k.of} (${pct(f.pct)}) ${k.what}`);

  return (
    <div className="mb-6 rounded-xl border border-line bg-muted/40 p-4">
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-ink-subtle">
          <BarChart3 className="h-3.5 w-3.5" /> {k.title}
        </p>
        <span className="text-xs text-ink-muted">
          {kind === 'grade' ? 'Bars and numbers: score out of 100' : 'Bars: % of records · on top: how many'} · {higher ? 'higher' : 'lower'} is better
        </span>
        <button
          type="button"
          onClick={() => setTable((t) => !t)}
          className="ml-auto inline-flex items-center gap-1 rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink-muted hover:text-ink"
        >
          {table ? <BarChart3 className="h-3.5 w-3.5" /> : <Table2 className="h-3.5 w-3.5" />}
          {table ? 'Chart' : 'Table'}
        </button>
      </div>

      {table ? (
        <div className="overflow-x-auto rounded-lg border border-line bg-surface">
          <table className="w-full text-left text-xs">
            <thead className="bg-muted/50 text-[11px] uppercase tracking-wide text-ink-subtle">
              <tr>
                <th className="px-3 py-2">Field</th>
                <th className="px-3 py-2 text-right">Count</th>
                <th className="px-3 py-2 text-right">Out of</th>
                <th className="px-3 py-2 text-right">%</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {scores.map((f) => (
                <tr key={f.field}>
                  <td className="px-3 py-1.5 font-medium">{f.label}</td>
                  <td className="px-3 py-1.5 text-right font-semibold tabular-nums">{fmtNumber(f.count)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-ink-muted">{fmtNumber(f.of)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{pct(f.pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="flex">
          {/* scale */}
          <div className="relative mr-2 mt-4 w-9 shrink-0 text-right text-[10px] tabular-nums text-ink-subtle" style={{ height: PLOT }} aria-hidden="true">
            {ticks.map((t) => (
              <span key={t} className="absolute right-0 -translate-y-1/2" style={{ top: `${100 - (100 * t) / top}%` }}>{pct(t)}</span>
            ))}
          </div>
          <div className="scrollbar-thin min-w-0 flex-1 overflow-x-auto">
            <div className="relative pt-4" style={{ minWidth: scores.length * 64 }}>
              {/* gridlines */}
              <div className="pointer-events-none absolute inset-x-0 top-4" style={{ height: PLOT }} aria-hidden="true">
                {ticks.map((t) => (
                  <span key={t} className={cx('absolute inset-x-0 border-t', t === 0 ? 'border-ink-subtle/40' : 'border-dashed border-line')} style={{ top: `${100 - (100 * t) / top}%` }} />
                ))}
              </div>
              <div className="relative flex" role="img" aria-label={`${k.title}: ${scores.map((f) => `${f.label} ${say(f)}`).join('; ')}`}>
                {scores.map((f, i) => (
                  <div key={f.field} className="relative flex min-w-[64px] flex-1 flex-col items-center" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                    <div className={cx('flex w-full items-end justify-center rounded-t-md transition-colors', hover === i && 'bg-ink/5')} style={{ height: PLOT }}>
                      <span className="flex w-7 flex-col items-center justify-end" style={{ height: `${Math.min(100, (100 * f.pct) / top)}%` }}>
                        <span className="-mt-4 mb-0.5 whitespace-nowrap text-[11px] font-semibold tabular-nums text-ink">{fmtNumber(f.count)}</span>
                        <span className="w-full flex-1 rounded-t-[4px] transition-[height] duration-700" style={{ minHeight: f.count ? 2 : 0, background: 'var(--series-1)' }} />
                      </span>
                    </div>
                    <span className="mt-1.5 line-clamp-2 w-full px-1 text-center text-[10px] leading-tight text-ink-muted" title={f.label}>
                      {f.label}
                    </span>
                    {hover === i && (
                      <div className="pointer-events-none absolute bottom-full z-10 mb-1 w-48 rounded-lg border border-line bg-surface p-2 text-xs shadow-pop">
                        <p className="font-semibold text-ink">{f.label}</p>
                        <p className="mt-0.5 text-ink-muted">
                          {kind === 'grade' ? (
                            <>Score <span className="font-semibold tabular-nums text-ink">{fmtNumber(f.count)}</span> of 100</>
                          ) : (
                            <>
                              <span className="font-semibold tabular-nums text-ink">{fmtNumber(f.count)}</span> of {fmtNumber(f.of)} {k.of} ({pct(f.pct)}) {k.what}
                            </>
                          )}
                        </p>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
      {kind === 'duplicates' && (
        <p className="mt-2 text-[11px] text-ink-subtle">Identifying fields only (email, phone, website, company, name); places, titles and surnames are shared by design.</p>
      )}
    </div>
  );
}
