import { ArrowRight, CheckCircle2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { SEVERITY_COLORS } from '@/components/charts/Charts';
import { getArea } from '@/config/categories';
import { cx, fmtNumber } from '@/lib/format';
import { SEVERITY_RANK } from '@/lib/health';
import type { Finding } from '@/types';
import { FindingStatusBadge } from '../ui/Badges';
import { Drawer } from '../ui/Overlay';
import type { ObjectChip } from './DiagnosticAreaCard';

const DOT = { good: 'bg-good', warn: 'bg-warn', bad: 'bg-bad' };

/** One object's problems in one area, opened from a card's "By object" chip. */
export function ObjectProblemsDrawer({
  view,
  findings,
  assessmentId,
  onClose,
  onSelectFinding,
}: {
  view: { areaId: string; object: ObjectChip } | null;
  findings: Finding[];
  assessmentId?: string;
  onClose: () => void;
  onSelectFinding: (f: Finding) => void;
}) {
  const area = view ? getArea(view.areaId) : undefined;
  const list = view
    ? findings
        .filter((f) => f.areaId === view.areaId && f.objectName === view.object.name)
        .sort((a, b) => Number(b.status === 'open') - Number(a.status === 'open') || SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || b.affectedRecords - a.affectedRecords)
    : [];
  const affected = list.filter((f) => f.status === 'open' || f.status === 'in-review').reduce((n, f) => n + f.affectedRecords, 0);

  return (
    <Drawer
      open={!!view}
      onClose={onClose}
      title={view?.object.label ?? ''}
      subtitle={area ? `Area ${area.number}: ${area.name}` : undefined}
    >
      {view && (
        <div className="space-y-5">
          <div className="flex items-center gap-3 rounded-xl border border-line bg-muted/40 p-4">
            <span className={cx('h-2.5 w-2.5 shrink-0 rounded-full', DOT[view.object.tone])} />
            <div className="min-w-0">
              <p className="font-semibold">{list.length ? `${list.length} problem${list.length === 1 ? '' : 's'} in this area` : 'No problems in this area'}</p>
              <p className="text-xs text-ink-muted">
                {[/problems?$/.test(view.object.text) ? null : view.object.text, affected ? `${fmtNumber(affected)} records affected` : null].filter(Boolean).join(' · ') ||
                  'Measured in the latest health check'}
              </p>
            </div>
          </div>

          {list.length === 0 ? (
            <div className="flex flex-col items-center py-8 text-center">
              <CheckCircle2 className="h-9 w-9 text-good" />
              <p className="mt-2 text-sm font-medium">Nothing to fix here</p>
              <p className="mt-0.5 text-xs text-ink-muted">This area found no problems with {view.object.label}.</p>
            </div>
          ) : (
            <ul className="space-y-2">
              {list.map((f) => (
                <li key={f.id}>
                  <button
                    type="button"
                    onClick={() => onSelectFinding(f)}
                    className="group flex w-full items-start gap-3 rounded-xl border border-line p-3 text-left transition hover:border-brand/40 hover:bg-brand-soft/40"
                  >
                    <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: SEVERITY_COLORS[f.severity] }} title={f.severity} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium group-hover:text-brand">{f.name}</span>
                      <span className="mt-0.5 block text-xs text-ink-muted">
                        <span className="capitalize">{f.severity}</span>
                        {f.affectedRecords > 0 && ` · ${fmtNumber(f.affectedRecords)} records`}
                      </span>
                    </span>
                    <FindingStatusBadge status={f.status} />
                    <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-ink-subtle transition group-hover:translate-x-0.5 group-hover:text-brand" />
                  </button>
                </li>
              ))}
            </ul>
          )}

          {assessmentId && (
            <Link
              to={`/results?assessment=${encodeURIComponent(assessmentId)}&object=${encodeURIComponent(view.object.name)}`}
              className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
            >
              See all {view.object.label} problems in My Results <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          )}
        </div>
      )}
    </Drawer>
  );
}
