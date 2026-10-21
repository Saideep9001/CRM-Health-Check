import { SCORE_BANDS } from '@/config/glossary';
import { cx } from '@/lib/format';

/** "What do the score colours mean?" — shown wherever scores appear. */
export function ScoreLegend({ className }: { className?: string }) {
  return (
    <div className={cx('flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted', className)} aria-label="Score guide">
      <span className="font-medium text-ink-subtle">Score guide:</span>
      {SCORE_BANDS.map((b) => (
        <span key={b.label} className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ background: b.color }} />
          <span>
            <span className="font-medium text-ink">{b.label}</span> {b.text}
          </span>
        </span>
      ))}
    </div>
  );
}
