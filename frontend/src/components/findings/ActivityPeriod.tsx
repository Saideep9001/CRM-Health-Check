import { useState } from 'react';

/** YYYY-MM-DD in the viewer's own time zone (what a date input shows). */
const day = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const ago = (months: number) => {
  const d = new Date();
  d.setMonth(d.getMonth() - months);
  return day(d);
};

type Choice = '30' | '90' | '180' | 'custom';

/** The period a No Activity (or Stale Leads) table covers: nothing in the last 1, 3 or 6 months, or between two picked
 *  dates. `own` is the card's own period (sent as undefined); `onChange` gets the API's `period`: undefined, "30", "90",
 *  "180" or "range:YYYY-MM-DD:YYYY-MM-DD". `what` names the dates ("Last activity", "No status change"). */
export function ActivityPeriod({ onChange, own = '180', what = 'Last activity' }: {
  onChange: (period: string | undefined) => void;
  own?: '30' | '90' | '180';
  what?: string;
}) {
  const today = day(new Date());
  const [choice, setChoice] = useState<Choice>(own);
  const [from, setFrom] = useState(ago(12));
  const [to, setTo] = useState(ago(6));
  const valid = (f: string, t: string) => !!f && !!t && f <= t && f <= today;
  const apply = (c: Choice, f = from, t = to) => {
    setChoice(c);
    if (c === 'custom' && !valid(f, t)) return; // keep showing the last good period until both dates make sense
    onChange(c === own ? undefined : c === 'custom' ? `range:${f}:${t}` : c);
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
      <select className="input h-7 w-auto py-0 text-xs" value={choice} onChange={(e) => apply(e.target.value as typeof choice)} aria-label="Period">
        <option value="30">Last 1 month</option>
        <option value="90">Last 3 months</option>
        <option value="180">Last 6 months</option>
        <option value="custom">Custom dates…</option>
      </select>
      {choice === 'custom' && (
        <>
          <span title="Between these dates (both included)">{what} from</span>
          <input
            type="date"
            className="input h-7 w-auto py-0 text-xs"
            value={from}
            max={to || today}
            onChange={(e) => {
              setFrom(e.target.value);
              apply('custom', e.target.value, to);
            }}
            aria-label={`${what} from`}
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
            aria-label={`${what} to`}
          />
          {!valid(from, to) && <span className="text-bad">From must be on or before To</span>}
        </>
      )}
    </span>
  );
}
