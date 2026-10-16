import { motion } from 'framer-motion';
import { ArrowDownRight, ArrowUpRight, Database, Gauge, History, Siren, TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';
import { AnimatedNumber, Sparkline } from '@/components/ui/Visuals';
import { cx, scoreBand } from '@/lib/format';

/** Headline numbers for the Reports page, with change since the previous check where it makes sense. */
export function KpiCards({
  score,
  previousScore,
  problems,
  previousProblems,
  urgent,
  records,
  checks,
  trend,
}: {
  score: number | null;
  previousScore: number | null;
  problems: number;
  previousProblems: number | null;
  urgent: number;
  records: number;
  checks: number;
  /** Overall scores, oldest to newest. */
  trend: number[];
}) {
  const band = scoreBand(score);
  return (
    <motion.div
      className="no-print mb-6 grid grid-cols-2 gap-4 lg:grid-cols-5"
      initial="hidden"
      animate="show"
      variants={{ hidden: {}, show: { transition: { staggerChildren: 0.06 } } }}
    >
      <Card icon={<Gauge className="h-[18px] w-[18px]" />} tint={band.color} label="Health score" value={score} suffix="/100"
        change={score !== null && previousScore !== null ? score - previousScore : null} higherIsBetter bar={score} />
      <Card icon={<TriangleAlert className="h-[18px] w-[18px]" />} tint="rgb(var(--brand))" label="Problems" value={problems}
        change={previousProblems !== null ? problems - previousProblems : null} higherIsBetter={false} />
      <Card icon={<Siren className="h-[18px] w-[18px]" />} tint="rgb(var(--sev-critical))" label="Urgent (critical + high)" value={urgent}
        bar={problems ? (urgent / problems) * 100 : 0} barLabel={problems ? `${Math.round((urgent / problems) * 100)}% of problems` : undefined} />
      <Card icon={<Database className="h-[18px] w-[18px]" />} tint="rgb(var(--sev-high))" label="Records affected" value={records} />
      <Card icon={<History className="h-[18px] w-[18px]" />} tint="rgb(var(--good))" label="Health checks in period" value={checks}
        extra={trend.length >= 2 ? <Sparkline data={trend} color="rgb(var(--good))" /> : undefined} />
    </motion.div>
  );
}

function Card({
  icon,
  tint,
  label,
  value,
  suffix,
  change,
  higherIsBetter,
  bar,
  barLabel,
  extra,
}: {
  icon: ReactNode;
  tint: string;
  label: string;
  value: number | null;
  suffix?: string;
  change?: number | null;
  higherIsBetter?: boolean;
  bar?: number | null;
  barLabel?: string;
  extra?: ReactNode;
}) {
  const good = change !== null && change !== undefined && change !== 0 ? (change > 0) === higherIsBetter : null;
  return (
    <motion.div
      variants={{ hidden: { opacity: 0, y: 12 }, show: { opacity: 1, y: 0 } }}
      whileHover={{ y: -3 }}
      className="card relative overflow-hidden p-4 transition-shadow hover:shadow-pop"
    >
      <span className="pointer-events-none absolute -right-8 -top-8 h-24 w-24 rounded-full blur-2xl" style={{ background: tint, opacity: 0.14 }} />
      <div className="flex items-start justify-between gap-2">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg" style={{ color: tint, background: `color-mix(in srgb, ${tint} 14%, transparent)` }}>
          {icon}
        </span>
        {good !== null && change !== null && change !== undefined && (
          <span
            className={cx('inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-semibold', good ? 'bg-good-soft text-good' : 'bg-bad-soft text-bad')}
            title="Change since the previous health check"
          >
            {change > 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
            {Math.abs(change)}
          </span>
        )}
        {extra}
      </div>
      <p className="mt-3 text-[13px] font-medium text-ink-muted">{label}</p>
      <p className="mt-0.5 text-[26px] font-semibold leading-none">
        {value === null ? '—' : <AnimatedNumber value={value} duration={0.8} />}
        {value !== null && suffix && <span className="ml-0.5 text-sm font-medium text-ink-subtle">{suffix}</span>}
      </p>
      {bar !== undefined && bar !== null && (
        <div className="mt-3">
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <motion.div
              className="h-full rounded-full"
              style={{ background: tint }}
              initial={{ width: 0 }}
              animate={{ width: `${Math.max(0, Math.min(100, bar))}%` }}
              transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}
            />
          </div>
          {barLabel && <p className="mt-1 text-[11px] text-ink-subtle">{barLabel}</p>}
        </div>
      )}
    </motion.div>
  );
}
