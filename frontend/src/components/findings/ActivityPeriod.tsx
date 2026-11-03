import { useState } from 'react';

/** YYYY-MM-DD in the viewer's own time zone (what a date input shows). */
const day = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const ago = (months: number) => {
  const d = new Date();
  d.setMonth(d.getMonth() - months);
  return day(d);
};

/** The period a No Activity table covers: no activity in the last 6 months (the health check's own) or 3, or the last
 *  activity between two picked dates. `onChange` gets the API's `period`: undefined (6 months), "90", or
 *  "range:YYYY-MM-DD:YYYY-MM-DD". */
export function ActivityPeriod({ onChange }: { onChange: (period: string | undefined) => void }) {
  const today = day(new Date());
  const [choice, setChoice] = useState<'180' | '90' | 'custom'>('180');
  const [from, setFrom] = useState(ago(12));
  const [to, setTo] = useState(ago(6));
  const valid = (f: string, t: string) => !!f && !!t && f <= t && f <= today;
  const apply = (c: typeof choice, f = from, t = to) => {
    setChoice(c);
    if (c === 'custom' && !valid(f, t)) return; // keep showing the last good period until both dates make sense
    onChange(c === '180' ? undefined : c === '90' ? '90' : `range:${f}:${t}`);
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
      <select className="input h-7 w-auto py-0 text-xs" value={choice} onChange={(e) => apply(e.target.value as typeof choice)} aria-label="Period">
        <option value="180">Last 6 months</option>
        <option value="90">Last 3 months</option>
        <option value="custom">Custom dates…</option>
      </select>
      {choice === 'custom' && (
        <>
          <span title="Records whose last activity falls between these dates (both included)">Last activity from</span>
          <input
            type="date"
            className="input h-7 w-auto py-0 text-xs"
            value={from}
            max={to || today}
            onChange={(e) => {
              setFrom(e.target.value);
              apply('custom', e.target.value, to);
            }}
            aria-label="Last activity from"
          />
          <span>to</span>
          <input
            type="date"
            className="input h-7 w-auto py-0 text-xs"
            value={to}
            min={from || undefined}
            max={today}
            onChange={(e) => {
              setTo(e.target.value);
              apply('custom', from, e.target.value);
            }}
            aria-label="Last activity to"
          />
          {!valid(from, to) && <span className="text-bad">From must be on or before To</span>}
        </>
      )}
    </span>
  );
}
