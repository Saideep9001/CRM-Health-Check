import { motion } from 'framer-motion';
import { Minus, TrendingDown, TrendingUp, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { cx, fmtCompact, fmtNumber } from '@/lib/format';
import type { HealthMetric } from '@/types';
import { HelpTip } from '../ui/HelpTip';
import { AnimatedNumber, ProgressBar, Sparkline } from '../ui/Visuals';

/**
 * KPI tile. `lowerIsBetter` flips how the trend is colored (fewer issues = improvement).
 * Score trends are in points; count trends are percentage change.
 */
export function HealthScoreCard({
  metric,
  icon: Icon,
  accent,
  lowerIsBetter,
  spark,
  hint,
  note,
  footer,
  onClick,
}: {
  metric: HealthMetric;
  icon: LucideIcon;
  accent: string;
  lowerIsBetter?: boolean;
  spark?: number[];
  hint?: string;
  /** A short line under the label saying what the number is made of. */
  note?: string;
  /** Extra detail under the number (e.g. which topics the problems are in). */
  footer?: ReactNode;
  onClick?: () => void;
}) {
  const isScore = metric.unit === 'score';
  const { trend, value } = metric;
  const improved = trend !== null && (lowerIsBetter ? trend < 0 : trend > 0);
  const TrendIcon = trend === null || trend === 0 ? Minus : trend > 0 ? TrendingUp : TrendingDown;

  const body = (
    <>
      <div className="flex items-start justify-between gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg" style={{ background: `${accent}1f`, color: accent }}>
          <Icon className="h-[18px] w-[18px]" />
        </span>
        {spark && spark.length > 1 ? <Sparkline data={spark} color={accent} /> : null}
      </div>

      {/* Label row — always shows a HelpTip when hint text is provided */}
      <p className="mt-4 flex items-center gap-1.5 text-[13px] font-medium text-ink-muted">
        <span>{metric.label}</span>
        {hint && <HelpTip side="top">{hint}</HelpTip>}
      </p>
      {note && <p className="text-[11px] text-ink-subtle">{note}</p>}

      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-[28px] font-semibold leading-none tracking-tight">
          {value === null ? '—' : <AnimatedNumber value={value} format={value > 99_999 ? fmtCompact : fmtNumber} />}
        </span>
        {isScore && value !== null && (
          <span className="text-sm text-ink-subtle" title="A score from 0 to 100 (not a percentage): 100 means no problems were found">
            score out of 100
          </span>
        )}
      </div>

      {isScore && (
        <div className="mt-3">
          <ProgressBar value={value ?? 0} />
        </div>
      )}

      {footer && <div className="mt-3 text-xs">{footer}</div>}

      <div className="mt-3 flex items-center justify-between text-xs">
        {trend === null ? (
          <span className="text-ink-subtle">No previous check to compare</span>
        ) : (
          <>
            <span className={cx('inline-flex items-center gap-1 font-medium', trend === 0 ? 'text-ink-subtle' : improved ? 'text-good' : 'text-bad')}>
              <TrendIcon className="h-3.5 w-3.5" />
              {trend > 0 ? '+' : ''}
              {trend}
              {isScore ? ' pts' : '%'}
            </span>
            <span className="text-ink-subtle">vs. previous check</span>
          </>
        )}
      </div>
    </>
  );

  return (
    <motion.div whileHover={{ y: -3 }} transition={{ type: 'spring', stiffness: 400, damping: 25 }} className="h-full">
      {onClick ? (
        // A div (not <button>) so the "i" info button inside stays valid, separately clickable HTML.
        <div
          role="button"
          tabIndex={0}
          onClick={onClick}
          onKeyDown={(e) => {
            if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
              e.preventDefault();
              onClick();
            }
          }}
          className="card card-pad block h-full w-full cursor-pointer text-left transition-shadow hover:shadow-pop"
        >
          {body}
        </div>
      ) : (
        <div className="card card-pad h-full">{body}</div>
      )}
    </motion.div>
  );
}
