import { useState } from 'react';

export const CLOSE_PERIODS = [
  { value: 'all', label: 'All dates' },
  { value: 'this_month', label: 'This month' },
  { value: 'last_month', label: 'Last month' },
  { value: 'this_quarter', label: 'This quarter' },
  { value: 'last_quarter', label: 'Last quarter' },
  { value: 'this_half', label: 'This half year' },
  { value: 'last_half', label: 'Last half year' },
  { value: 'this_year', label: 'This year' },
  { value: 'last_year', label: 'Last year' },
  { value: 'custom', label: 'Custom dates…' },
];
const today = () => new Date().toISOString().slice(0, 10);

/** Customer support leadership: when the cases were created. */
export const CREATED_PERIODS = [
  { value: 'all', label: 'All dates' },
  { value: 'today', label: 'Today' },
  { value: 'last_week', label: 'Last week' },
  { value: 'last_14', label: 'Last 14 days' },
  { value: 'this_month', label: 'This month' },
  { value: 'custom', label: 'Custom dates…' },
];

/** A date filter above a leadership table: Close Date for opportunities (Closed Won / Closed Lost), Created Date for cases.
 *  `onChange` gets the API's `period`: undefined (all dates), a period name, or "range:YYYY-MM-DD:YYYY-MM-DD". */
export function CloseDateFilter({ onChange, label = 'Close Date', periods = CLOSE_PERIODS }: {
  onChange: (period: string | undefined) => void;
  label?: string;
  periods?: { value: string; label: string }[];
}) {
  const [choice, setChoice] = useState('all');
  const [from, setFrom] = useState(`${new Date().getFullYear()}-01-01`);
  const [to, setTo] = useState(today());
  const valid = (f: string, t: string) => !!f && !!t && f <= t;
  const apply = (c: string, f = from, t = to) => {
    setChoice(c);
    if (c === 'custom') {
      if (valid(f, t)) onChange(`range:${f}:${t}`); // keep the last good period until both dates make sense
      return;
    }
    onChange(c === 'all' ? undefined : c);
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
      {label}
      <select className="input h-7 w-auto py-0 text-xs" value={choice} onChange={(e) => apply(e.target.value)} aria-label={label}>
        {periods.map((p) => (
          <option key={p.value} value={p.value}>{p.label}</option>
        ))}
      </select>
      {choice === 'custom' && (
        <>
          <span>from</span>
          <input type="date" className="input h-7 w-auto py-0 text-xs" value={from} max={to || undefined} aria-label={`${label} from`}
            onChange={(e) => { setFrom(e.target.value); apply('custom', e.target.value, to); }} />
          <span>to</span>
          <input type="date" className="input h-7 w-auto py-0 text-xs" value={to} min={from || undefined} aria-label={`${label} to`}
            onChange={(e) => { setTo(e.target.value); apply('custom', from, e.target.value); }} />
          {!valid(from, to) && <span className="text-bad">From must be on or before To</span>}
        </>
      )}
    </span>
  );
}
