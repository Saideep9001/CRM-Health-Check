import { Search } from 'lucide-react';
import { useState } from 'react';
import { cx, fmtNumber } from '@/lib/format';
import type { FieldListItem } from '@/types';

/** The fields behind a card about fields (unused, outdated, look-alike…): fill rate and why each is listed. */
export function FieldListTable({ items }: { items: FieldListItem[] }) {
  const [query, setQuery] = useState('');
  const term = query.trim().toLowerCase();
  const rows = term ? items.filter((f) => `${f.label} ${f.name} ${f.type} ${f.note}`.toLowerCase().includes(term)) : items;
  const notes = items.some((f) => f.note);

  if (!items.length) return <p className="rounded-lg bg-good-soft/50 px-4 py-6 text-center text-sm text-good">No fields to list — nothing was found here.</p>;
  return (
    <div className="overflow-hidden rounded-xl border border-line">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-muted/40 px-3 py-2">
        <div className="relative min-w-[200px] flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-subtle" />
          <input className="input h-8 pl-8 text-xs" placeholder="Filter fields…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <span className="text-xs text-ink-muted">{term ? `${fmtNumber(rows.length)} of ${fmtNumber(items.length)} fields` : `${fmtNumber(items.length)} fields`}</span>
      </div>
      <div className="scrollbar-thin max-h-[32rem] overflow-auto">
        <table className="w-full min-w-[640px] text-left text-xs">
          <thead className="sticky top-0 z-10 bg-surface text-[11px] uppercase tracking-wide text-ink-subtle shadow-[0_1px_0_rgb(var(--line))]">
            <tr>
              <th className="px-3 py-2">Field</th>
              <th className="px-3 py-2">Type</th>
              <th className="w-56 px-3 py-2">Filled in</th>
              {notes && <th className="px-3 py-2">Why it’s listed</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((f, i) => (
              <tr key={`${f.name}-${i}`} className="hover:bg-muted/50">
                <td className="px-3 py-2">
                  <span className="flex items-center gap-1.5 font-medium text-ink">
                    {f.label}
                    {f.custom && <span className="rounded bg-brand-soft px-1.5 py-px text-[10px] font-semibold text-brand-ink">Custom</span>}
                  </span>
                  <span className="font-mono text-[11px] text-ink-subtle">{f.name}</span>
                </td>
                <td className="px-3 py-2 text-ink-muted">{f.type}</td>
                <td className="px-3 py-2">
                  {f.pct == null ? (
                    <span className="text-ink-subtle">Can’t be counted</span>
                  ) : (
                    <span className="flex items-center gap-2">
                      <span className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
                        <span
                          className={cx('block h-full rounded-full', f.pct < 1 ? 'bg-bad' : f.pct < 20 ? 'bg-warn' : 'bg-good')}
                          style={{ width: `${Math.max(f.pct, f.filled ? 2 : 0)}%` }}
                        />
                      </span>
                      <span className="tabular-nums text-ink">{f.pct % 1 ? f.pct.toFixed(1) : f.pct}%</span>
                      <span className="tabular-nums text-ink-subtle">
                        {fmtNumber(f.filled ?? 0)} of {fmtNumber(f.of ?? 0)}
                      </span>
                    </span>
                  )}
                </td>
                {notes && <td className="px-3 py-2 text-ink-muted">{f.note}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
