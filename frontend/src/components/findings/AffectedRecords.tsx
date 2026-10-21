import { ArrowDownRight, ArrowUpRight, Minus, Sparkles } from 'lucide-react';
import { cx, fmtNumber } from '@/lib/format';
import type { Finding } from '@/types';

/** How a problem changed since the previous health check. */
export function ChangeBadge({ finding, className }: { finding: Finding; className?: string }) {
  const change = finding.change ?? 'new';
  const diff = finding.previousAffected != null ? finding.affectedRecords - finding.previousAffected : 0;
  const look = {
    new: { cls: 'bg-brand-soft text-brand-ink', icon: <Sparkles className="h-3 w-3" />, text: 'New' },
    worse: { cls: 'bg-bad-soft text-bad', icon: <ArrowUpRight className="h-3 w-3" />, text: `Worse +${fmtNumber(diff)}` },
    better: { cls: 'bg-good-soft text-good', icon: <ArrowDownRight className="h-3 w-3" />, text: `Better ${fmtNumber(diff)}` },
    same: { cls: 'bg-muted text-ink-muted', icon: <Minus className="h-3 w-3" />, text: 'No change' },
  }[change];
  return (
    <span
      className={cx('inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold', look.cls, className)}
      title={finding.previousAffected != null ? `${fmtNumber(finding.previousAffected)} in the previous check` : 'Not in the previous check'}
    >
      {look.icon}
      {look.text}
    </span>
  );
}
