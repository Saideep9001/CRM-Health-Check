import { motion } from 'framer-motion';
import { CalendarCheck2, Gauge, Layers, TriangleAlert, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { RunCheckPanel } from '@/components/assessment/RunCheckPanel';
import { CategoryCard } from '@/components/dashboard/CategoryCard';
import { InfoTip } from '@/components/ui/HelpTip';
import { PageHeader, StaggerGrid, StaggerItem } from '@/components/ui/Page';
import { AnimatedNumber } from '@/components/ui/Visuals';
import { CATEGORIES, DIAGNOSTIC_AREAS, MVP_AREA_IDS } from '@/config/categories';
import { useLatestAssessment } from '@/hooks/useLatestAssessment';
import { cx, fmtDate, scoreBand } from '@/lib/format';

/** One headline number: icon, label with an info tip, the number, and a line or bar underneath. */
function Stat({ icon: Icon, label, tip, value, suffix, color, children, index }: {
  icon: LucideIcon; label: string; tip: string; value: number | null; suffix?: string; color: string; children: ReactNode; index: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: index * 0.07, ease: [0.16, 1, 0.3, 1] }}
      className="card group relative overflow-hidden p-4 transition-shadow hover:shadow-md"
    >
      <span className="absolute inset-x-0 top-0 h-[3px]" style={{ background: color }} />
      <span className="pointer-events-none absolute -right-6 -top-6 h-20 w-20 rounded-full opacity-[0.08] transition-transform duration-500 group-hover:scale-125" style={{ background: color }} />
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white shadow-sm" style={{ background: color }}>
          <Icon className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1 text-xs font-medium text-ink-subtle">
            {label}
            <InfoTip>{tip}</InfoTip>
          </p>
          <p className="text-[26px] font-semibold leading-tight tracking-tight tabular-nums">
            {value === null ? '—' : <AnimatedNumber value={value} />}
            {value !== null && suffix && <span className="ml-0.5 text-base font-medium text-ink-subtle">{suffix}</span>}
          </p>
        </div>
      </div>
      <div className="mt-3 text-[11px] text-ink-muted">{children}</div>
    </motion.div>
  );
}

/** A thin bar that grows to `pct`. */
function Bar({ pct, color }: { pct: number; color: string }) {
  return (
    <span className="mb-1.5 block h-1.5 overflow-hidden rounded-full bg-muted">
      <motion.span
        className="block h-full rounded-full"
        style={{ background: color }}
        initial={{ width: 0 }}
        animate={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
        transition={{ duration: 1.1, delay: 0.2, ease: [0.16, 1, 0.3, 1] }}
      />
    </span>
  );
}

export default function AssessmentOverviewPage() {
  const { latest, results, findings } = useLatestAssessment();
  const assessed = results ? results.areas.filter((a) => a.status === 'assessed').length : 0;
  const total = DIAGNOSTIC_AREAS.length;
  const score = latest?.overallScore ?? null;
  const band = scoreBand(score);
  const critical = findings.filter((f) => f.severity === 'critical').length;
  const high = findings.filter((f) => f.severity === 'high').length;
  const brand = 'rgb(var(--brand))';

  return (
    <div>
      <PageHeader
        title="What We Check"
        description="6 topics, 21 areas. Click a topic to learn more."
      />

      <RunCheckPanel areaIds={MVP_AREA_IDS} label="everything that’s ready" checked={!!latest} lastChecked={latest?.completedAt} objectPicker />

      <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat index={0} icon={Layers} label="Areas we check" tip="Every area the platform checks, grouped into topics." value={total} color={brand}>
          <Bar pct={100} color={brand} />
          Across {CATEGORIES.length} topics, all available now
        </Stat>
        <Stat index={1} icon={CalendarCheck2} label="Checked last time" tip="Areas covered by your latest health check." value={latest ? assessed : null} suffix={`/ ${total}`} color="rgb(var(--good))">
          <Bar pct={latest ? (assessed / total) * 100 : 0} color="rgb(var(--good))" />
          {latest ? <span title={latest.name}>Last checked {fmtDate(latest.completedAt ?? latest.createdAt)}</span> : 'You haven’t run a health check yet.'}
        </Stat>
        <Stat index={2} icon={Gauge} label="Health score" tip="Your latest overall score. 100% means no problems were found." value={score} suffix="%" color={band.color}>
          <Bar pct={score ?? 0} color={band.color} />
          <span style={{ color: score === null ? undefined : band.color }} className={cx(score !== null && 'font-medium')}>{band.label}</span>
        </Stat>
        <Stat index={3} icon={TriangleAlert} label="Problems found" tip="Problems raised by your latest health check, across every topic." value={latest ? findings.length : null} color={critical ? 'rgb(var(--sev-critical))' : 'rgb(var(--warn))'}>
          {latest ? (
            <span className="flex flex-wrap gap-1.5">
              <span className="rounded-full bg-sev-critical/10 px-2 py-px font-medium text-sev-critical">{critical} critical</span>
              <span className="rounded-full bg-sev-high/10 px-2 py-px font-medium text-sev-high">{high} high</span>
            </span>
          ) : 'Run a health check to see them.'}
        </Stat>
      </div>

      <StaggerGrid className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {CATEGORIES.map((c) => (
          <StaggerItem key={c.id}>
            <CategoryCard category={c} results={results} findings={findings} />
          </StaggerItem>
        ))}
      </StaggerGrid>
    </div>
  );
}
