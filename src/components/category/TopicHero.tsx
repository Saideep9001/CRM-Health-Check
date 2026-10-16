import { motion } from 'framer-motion';
import { CalendarDays, Database, Layers, Siren, TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';
import { CoverageBadge, ReleaseBadge } from '@/components/ui/Badges';
import { CategoryTile } from '@/components/ui/CategoryIcon';
import { InfoTip } from '@/components/ui/HelpTip';
import { AnimatedNumber, ScoreRing } from '@/components/ui/Visuals';
import { fmtDate, scoreBand } from '@/lib/format';
import type { CoverageStatus } from '@/lib/health';
import type { Category } from '@/types';

/** Topic header: glowing backdrop in the topic's colour, live stats, and the big score ring. */
export function TopicHero({
  category,
  color,
  score,
  coverage,
  areas,
  problems,
  critical,
  records,
  lastChecked,
}: {
  category: Category;
  color: string;
  score: number | null;
  coverage: CoverageStatus;
  areas: number;
  problems: number | null;
  critical: number | null;
  records: number | null;
  lastChecked: string | null;
}) {
  const band = scoreBand(score);
  return (
    <section className="card relative mb-6 overflow-hidden">
      {/* Backdrop: soft colour wash with two slowly drifting glows. */}
      <div className="pointer-events-none absolute inset-0" style={{ background: `linear-gradient(120deg, ${color}1f 0%, transparent 55%)` }} />
      <motion.div
        className="pointer-events-none absolute -right-24 -top-28 h-80 w-80 rounded-full blur-3xl"
        style={{ background: color, opacity: 0.16 }}
        animate={{ x: [0, -24, 0], y: [0, 18, 0], scale: [1, 1.08, 1] }}
        transition={{ duration: 12, repeat: Infinity, ease: 'easeInOut' }}
      />
      <motion.div
        className="pointer-events-none absolute -bottom-32 left-1/3 h-72 w-72 rounded-full blur-3xl"
        style={{ background: band.color, opacity: score === null ? 0 : 0.1 }}
        animate={{ x: [0, 30, 0], y: [0, -12, 0] }}
        transition={{ duration: 14, repeat: Infinity, ease: 'easeInOut' }}
      />
      <span className="absolute inset-y-0 left-0 w-1" style={{ background: color }} />

      <div className="relative flex flex-col gap-6 p-6 lg:flex-row lg:items-center">
        <div className="min-w-0 flex-1">
          <div className="flex gap-4">
            <motion.div initial={{ scale: 0.6, rotate: -12, opacity: 0 }} animate={{ scale: 1, rotate: 0, opacity: 1 }} transition={{ type: 'spring', stiffness: 260, damping: 18 }}>
              <CategoryTile id={category.id} size="lg" />
            </motion.div>
            <div className="min-w-0">
              <div className="mb-1.5 flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">Topic {category.order} of 6</span>
                <ReleaseBadge release={category.release} />
                <CoverageBadge status={coverage} />
              </div>
              <motion.h1
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4 }}
                className="flex items-center gap-2 text-2xl font-semibold tracking-tight sm:text-3xl"
              >
                {category.name}
                <InfoTip size="md" label="About this topic">
                  {category.purpose}
                </InfoTip>
              </motion.h1>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-ink-muted">
            <Stat icon={<Layers className="h-4 w-4" />} label={areas === 1 ? 'area' : 'areas'} value={areas} />
            <Stat icon={<TriangleAlert className="h-4 w-4" />} label="problems" value={problems} />
            <Stat icon={<Siren className="h-4 w-4" />} label="critical" value={critical} tone={critical ? 'bad' : undefined} />
            <Stat icon={<Database className="h-4 w-4" />} label="records checked" value={records} />
          </div>
        </div>

        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="relative flex shrink-0 flex-col items-center self-center"
        >
          <div className="absolute inset-4 rounded-full blur-2xl" style={{ background: band.color, opacity: score === null ? 0 : 0.18 }} />
          <div className="relative rounded-full bg-surface/70 p-3 shadow-card backdrop-blur">
            <ScoreRing score={score} size={128} stroke={11} label={score === null ? 'Not checked' : 'Health score'} showBand={false} />
          </div>
          <span className="mt-3 rounded-full px-3 py-1 text-xs font-semibold" style={{ color: band.color, background: `color-mix(in srgb, ${band.color} 12%, transparent)` }}>
            {band.label}
          </span>
          {lastChecked && (
            <span className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-ink-subtle">
              <CalendarDays className="h-3 w-3" /> Last checked {fmtDate(lastChecked)}
            </span>
          )}
        </motion.div>
      </div>
    </section>
  );
}

function Stat({ icon, label, value, tone }: { icon: ReactNode; label: string; value: number | null; tone?: 'bad' }) {
  if (value === null) return null;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={tone === 'bad' ? 'text-bad' : 'text-ink-subtle'}>{icon}</span>
      <span className={`font-semibold text-ink ${tone === 'bad' ? 'text-bad' : ''}`}>
        <AnimatedNumber value={value} />
      </span>
      {label}
    </span>
  );
}
