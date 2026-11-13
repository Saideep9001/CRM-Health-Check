import { useState } from 'react';
import { ActivityPeriod } from './ActivityPeriod';

type Show = 'all' | 'used' | 'unused';

/** Report usage / Dashboard usage: All, Used, or Unused, and only for Unused, the period (the last 30 / 90 / 180 days, or between two
 *  dates). `onChange` gets the API's `period`: undefined (All), "used", or the Unused period ("30", "90", "180", "range:…"). */
export function UsageFilter({ onChange }: { onChange: (period: string | undefined) => void }) {
  const [show, setShow] = useState<Show>('all');
  const [unusedFor, setUnusedFor] = useState('180');
  const pick = (next: Show) => {
    setShow(next);
    onChange(next === 'all' ? undefined : next === 'used' ? 'used' : unusedFor);
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <select className="input h-7 w-auto py-0 text-xs" value={show} onChange={(e) => pick(e.target.value as Show)} aria-label="Show">
        <option value="all">All</option>
        <option value="used">Used</option>
        <option value="unused">Unused</option>
      </select>
      {show === 'unused' && (
        // not used in the last 30 / 90 / 180 days (180 = the card's own), or last used between two dates
        <ActivityPeriod
          inDays
          what="Last used"
          onChange={(p) => {
            const period = p ?? '180';
            setUnusedFor(period);
            onChange(period);
          }}
        />
      )}
    </span>
  );
}
