import { objectLabel } from '@/components/category/DiagnosticAreaCard';
import { motion } from 'framer-motion';
import { ChangeBadge } from './AffectedRecords';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useState } from 'react';
import { getArea, getCategory } from '@/config/categories';
import { useSort } from '@/hooks/useSort';
import { fmtNumber } from '@/lib/format';
import { SEVERITY_RANK } from '@/lib/health';
import type { Finding } from '@/types';
import { FindingStatusBadge, SeverityBadge } from '../ui/Badges';
import { CategoryTile } from '../ui/CategoryIcon';
import { SortableTh } from '../ui/Table';

const PAGE_SIZE = 25;

type Key = 'id' | 'name' | 'category' | 'area' | 'severity' | 'affected' | 'status';

const value = (f: Finding, k: Key): string | number => {
  switch (k) {
    case 'id':       return f.id;
    case 'name':     return f.name;
    case 'category': return getCategory(f.categoryId)?.order ?? 0;
    case 'area':     return getArea(f.areaId)?.number ?? 0;
    case 'severity': return SEVERITY_RANK[f.severity];
    case 'affected': return f.affectedRecords;
    case 'status':   return f.status;
  }
};

export function FindingsTable({
  findings,
  onSelect,
  compact,
}: {
  findings: Finding[];
  onSelect: (f: Finding) => void;
  compact?: boolean;
}) {
  const { sorted, sortKey, sortDir, toggle } = useSort<Finding, Key>(findings, 'severity', value);
  const th = { activeKey: sortKey, dir: sortDir, onSort: toggle };
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  useEffect(() => setPage(0), [findings, sortKey, sortDir]);
  const visible = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <div>
      <div className="scrollbar-thin relative overflow-x-auto">
        <table className={`w-full border-collapse ${compact ? 'min-w-[760px]' : 'min-w-[1100px]'}`}>
          <thead className="border-b border-line bg-muted/50">
            <tr>
              <SortableTh label="Problem" sortKey="name" {...th} />
              {!compact && <SortableTh label="Topic Area" sortKey="category" {...th} />}
              <SortableTh label="Check" sortKey="area" {...th} />
              <SortableTh label="Urgency" sortKey="severity" {...th} />
              <SortableTh label="What's Affected" sortKey="affected" {...th} />
              {!compact && <th className="th">Why It Matters</th>}
              {!compact && <th className="th">What to Do</th>}
              <SortableTh label="Progress" sortKey="status" {...th} />
              <th className="th w-8"><span className="sr-only">Open</span></th>
            </tr>
          </thead>
          <tbody>
            {visible.map((f, i) => {
              const cat  = getCategory(f.categoryId);
              const area = getArea(f.areaId);
              return (
                <motion.tr
                  key={f.id}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(i * 0.025, 0.4) }}
                  onClick={() => onSelect(f)}
                  onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onSelect(f))}
                  tabIndex={0}
                  className="group cursor-pointer border-b border-line last:border-0 transition-colors hover:bg-muted/60 focus-visible:bg-muted/60"
                >
                  <td className="td min-w-[220px] max-w-[320px] font-medium">
                    <span className="block">{f.name}</span>
                    {f.description && <span className="mt-0.5 line-clamp-2 block text-xs font-normal text-ink-muted" title={f.description}>{f.description}</span>}
                    {f.change && f.change !== 'same' && <ChangeBadge finding={f} className="mt-1" />}
                  </td>
                  {!compact && (
                    <td className="td">
                      <span className="flex items-center gap-2">
                        {cat && <CategoryTile id={cat.id} size="sm" />}
                        <span className="whitespace-nowrap text-xs text-ink-muted">{cat?.shortName ?? f.categoryId}</span>
                      </span>
                    </td>
                  )}
                  <td className="td min-w-[180px] max-w-[220px] text-xs text-ink-muted">
                    {area ? (
                      <>
                        <span className="font-semibold text-ink">#{area.number}</span> · {area.name}
                      </>
                    ) : (
                      f.areaId
                    )}
                    {f.measure && <span className="mt-0.5 block text-[11px] text-ink-subtle" title="The measure that raised this problem">Measure: {f.measure}</span>}
                  </td>
                  <td className="td"><SeverityBadge severity={f.severity} /></td>
                  <td className="td whitespace-nowrap text-right tabular-nums">
                    {f.affectedRecords > 0 ? (
                      <>
                        {fmtNumber(f.affectedRecords)}
                        {f.objectName && <span className="block text-[11px] text-ink-subtle">{objectLabel(f.objectName)}</span>}
                      </>
                    ) : (
                      <span className="text-xs text-ink-subtle">{f.objectName ? objectLabel(f.objectName) : 'Org setting'}</span>
                    )}
                  </td>
                  {!compact && <td className="td min-w-[200px] max-w-[240px] text-xs text-ink-muted">{f.businessImpact}</td>}
                  {!compact && <td className="td min-w-[200px] max-w-[240px] text-xs text-ink-muted">{f.recommendedAction}</td>}
                  <td className="td"><FindingStatusBadge status={f.status} /></td>
                  <td className="td">
                    <ChevronRight className="h-4 w-4 text-ink-subtle transition-transform group-hover:translate-x-0.5" />
                  </td>
                </motion.tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-xs text-ink-muted">
          <span>
            {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, sorted.length)} of {sorted.length}
          </span>
          <div className="flex items-center gap-1">
            <button
              className="rounded-md p-1.5 hover:bg-muted disabled:opacity-40"
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
              aria-label="Previous page"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="px-2 tabular-nums">Page {page + 1} / {pages}</span>
            <button
              className="rounded-md p-1.5 hover:bg-muted disabled:opacity-40"
              disabled={page >= pages - 1}
              onClick={() => setPage((p) => p + 1)}
              aria-label="Next page"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
