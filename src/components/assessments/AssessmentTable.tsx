import { motion } from 'framer-motion';
import { ArrowRight, Ban } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useCancelAssessment } from '@/api/queries';
import { CATEGORIES } from '@/config/categories';
import { useToast } from '@/context/ToastContext';
import { useSort } from '@/hooks/useSort';
import { errorMessage } from '@/api/client';
import { fmtDate, fmtNumber } from '@/lib/format';
import type { Assessment } from '@/types';
import { AssessmentStatusBadge } from '../ui/Badges';
import { Button } from '../ui/Button';
import { CategoryTile } from '../ui/CategoryIcon';
import { SortableTh } from '../ui/Table';
import { Tooltip } from '../ui/Tooltip';

type Key = 'id' | 'name' | 'organization' | 'date' | 'categories' | 'records' | 'findings' | 'status';

const value = (a: Assessment, k: Key): string | number | null => {
  switch (k) {
    case 'id':
      return a.id;
    case 'name':
      return a.name;
    case 'organization':
      return a.organizationName;
    case 'date':
      return a.completedAt ?? a.startedAt ?? a.createdAt;
    case 'categories':
      return a.scope.categoryIds.length;
    case 'records':
      return a.recordsAssessed;
    case 'findings':
      return a.findingsCount;
    case 'status':
      return a.status;
  }
};

function CategoryStack({ ids }: { ids: Assessment['scope']['categoryIds'] }) {
  return (
    <div className="flex items-center -space-x-1.5">
      {ids.map((id) => (
        <Tooltip key={id} content={CATEGORIES.find((c) => c.id === id)?.name ?? id}>
          <span className="rounded-lg ring-2 ring-surface">
            <CategoryTile id={id} size="sm" />
          </span>
        </Tooltip>
      ))}
    </div>
  );
}

function StatusCell({ a }: { a: Assessment }) {
  if (a.status !== 'running' && a.status !== 'queued') return <AssessmentStatusBadge status={a.status} />;
  return (
    <div className="w-36">
      <AssessmentStatusBadge status={a.status} />
      {a.status === 'running' && a.progress !== null && (
        <div className="mt-1.5">
          <div className="h-1 overflow-hidden rounded-full bg-muted">
            <motion.div className="h-full rounded-full bg-brand" animate={{ width: `${a.progress}%` }} transition={{ duration: 0.6 }} />
          </div>
          <p className="mt-1 truncate text-[11px] text-ink-subtle">{a.currentStep ?? `${a.progress}%`}</p>
        </div>
      )}
    </div>
  );
}

/**
 * Shared table for Recent Assessments (dashboard) and Assessment History.
 * `variant="recent"` shows records assessed; `"history"` shows the assessment ID.
 */
export function AssessmentTable({ rows, variant }: { rows: Assessment[]; variant: 'recent' | 'history' }) {
  const navigate = useNavigate();
  const { notify } = useToast();
  const cancel = useCancelAssessment();
  const { sorted, sortKey, sortDir, toggle } = useSort<Assessment, Key>(rows, 'date', value);
  const th = { activeKey: sortKey, dir: sortDir, onSort: toggle };
  const history = variant === 'history';

  return (
    <div className="scrollbar-thin relative overflow-x-auto">
      <table className="w-full min-w-[960px] border-collapse">
        <thead className="border-b border-line bg-muted/50">
          <tr>
            {history && <SortableTh label="Check ID" sortKey="id" {...th} />}
            <SortableTh label="Health check" sortKey="name" {...th} />
            <SortableTh label="Salesforce" sortKey="organization" {...th} />
            <SortableTh label="Date" sortKey="date" {...th} />
            <SortableTh label="Topics checked" sortKey="categories" {...th} />
            {!history && <SortableTh label="Records checked" sortKey="records" {...th} />}
            <SortableTh label="Problems found" sortKey="findings" {...th} />
            <SortableTh label="Status" sortKey="status" {...th} />
            <th className="th text-right">Action</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((a, i) => {
            const active = a.status === 'running' || a.status === 'queued';
            return (
              <motion.tr
                key={a.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: Math.min(i * 0.03, 0.3) }}
                className="border-b border-line last:border-0 transition-colors hover:bg-muted/50"
              >
                {history && <td className="td whitespace-nowrap font-mono text-xs text-ink-muted">{a.id}</td>}
                <td className="td font-medium">{a.name}</td>
                <td className="td text-ink-muted">{a.organizationName}</td>
                <td className="td whitespace-nowrap text-ink-muted">{fmtDate(a.completedAt ?? a.startedAt ?? a.createdAt)}</td>
                <td className="td">
                  <CategoryStack ids={a.scope.categoryIds} />
                </td>
                {!history && <td className="td tabular-nums">{a.recordsAssessed !== null ? fmtNumber(a.recordsAssessed) : '—'}</td>}
                <td className="td tabular-nums">{a.status === 'completed' && a.findingsCount !== null ? a.findingsCount : '—'}</td>
                <td className="td">
                  <StatusCell a={a} />
                </td>
                <td className="td whitespace-nowrap text-right">
                  {active && (
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<Ban className="h-3.5 w-3.5" />}
                      disabled={cancel.isPending}
                      onClick={() =>
                        cancel.mutate(a.id, {
                          onSuccess: () => notify('Health check cancelled', a.name),
                          onError: (e) => notify('Could not cancel the health check', errorMessage(e), 'warning'),
                        })
                      }
                    >
                      Cancel
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => navigate(`/results?assessment=${encodeURIComponent(a.id)}`)}
                    iconRight={<ArrowRight className="h-3.5 w-3.5" />}
                  >
                    {active ? 'See progress' : 'See results'}
                  </Button>
                </td>
              </motion.tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
