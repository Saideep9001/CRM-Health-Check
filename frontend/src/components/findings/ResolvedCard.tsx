import { motion } from 'framer-motion';
import { PartyPopper } from 'lucide-react';
import { useState } from 'react';
import { SeverityBadge } from '@/components/ui/Badges';
import { getArea } from '@/config/categories';
import { fmtNumber } from '@/lib/format';
import type { ResolvedFinding } from '@/types';

const SHOWN = 4;

/** Problems from the previous check that are gone now — progress worth seeing. */
export function ResolvedCard({ resolved }: { resolved: ResolvedFinding[] }) {
  const [all, setAll] = useState(false);
  const records = resolved.reduce((n, r) => n + r.previousAffected, 0);
  const shown = all ? resolved : resolved.slice(0, SHOWN);
  return (
    <motion.section initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="mb-6 rounded-xl border border-good/30 bg-good-soft p-4">
      <div className="flex flex-wrap items-center gap-2">
        <PartyPopper className="h-5 w-5 text-good" />
        <h2 className="text-sm font-semibold">
          {resolved.length} {resolved.length === 1 ? 'problem' : 'problems'} fixed since the last check
        </h2>
        <span className="text-xs text-ink-muted">· {fmtNumber(records)} records cleaned up</span>
      </div>
      <ul className="mt-3 grid gap-2 sm:grid-cols-2">
        {shown.map((r) => {
          const area = getArea(r.areaId);
          return (
            <li key={`${r.areaId}-${r.name}`} className="flex items-center gap-2 rounded-lg bg-surface/70 px-3 py-2 text-sm">
              <SeverityBadge severity={r.severity} />
              <span className="min-w-0 flex-1 truncate line-through decoration-good/60" title={r.name}>
                {r.name}
              </span>
              <span className="shrink-0 text-[11px] text-ink-subtle">{area ? `Area ${area.number}` : ''}</span>
            </li>
          );
        })}
      </ul>
      {resolved.length > SHOWN && (
        <button onClick={() => setAll((v) => !v)} className="mt-2 text-xs font-medium text-good hover:underline">
          {all ? 'Show fewer' : `Show all ${resolved.length}`}
        </button>
      )}
    </motion.section>
  );
}
