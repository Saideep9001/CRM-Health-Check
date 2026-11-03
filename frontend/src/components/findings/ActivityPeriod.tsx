import { useState } from 'react';

/** YYYY-MM-DD in the viewer's own time zone (what a date input shows). */
const day = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const ago = (months: number) => {
  const d = new Date();
  d.setMonth(d.getMonth() - months);
  return day(d);
};

/** The period a No Activity table covers: the last 6 months (the health check's own), the last 3, or no activity since a
 *  picked date. `onChange` gets the API's `period`: undefined (6 months), "90", or "since:YYYY-MM-DD". */
export function ActivityPeriod({ onChange }: { onChange: (period: string | undefined) => void }) {
  const [choice, setChoice] = useState<'180' | '90' | 'custom'>('180');
  const [since, setSince] = useState(ago(6));
  const today = day(new Date());
  const pick = (c: typeof choice, from = since) => {
    setChoice(c);
    onChange(c === '180' ? undefined : c === '90' ? '90' : from ? `since:${from}` : undefined);
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
      <select className="input h-7 w-auto py-0 text-xs" value={choice} onChange={(e) => pick(e.target.value as typeof choice)} aria-label="No activity in">
        <option value="180">Last 6 months</option>
        <option value="90">Last 3 months</option>
        <option value="custom">Custom date…</option>
      </select>
      {choice === 'custom' && (
        <label className="inline-flex items-center gap-1.5">
          since
          <input
            type="date"
            className="input h-7 w-auto py-0 text-xs"
            value={since}
            max={today}
            onChange={(e) => {
              setSince(e.target.value);
              if (e.target.value && e.target.value <= today) pick('custom', e.target.value);
            }}
            aria-label="No activity since"
          />
        </label>
      )}
    </span>
  );
}
